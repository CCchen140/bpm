import sqlite3
import json
import threading
import os
import time
import re
from utils.file.fingerprint import get_unique_id
from utils.log_manager import LogManager
from utils.paths import PathManager


def get_default_db_path():
    return str(PathManager.instance().get_user_db_path())

class BirdLibraryDB:
    """数据库管理类"""
    _lock = threading.Lock() # 用于多线程写入时的互斥锁
    _fastid_uuid_sync_guard = threading.Lock()
    _fastid_uuid_sync_started = False

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = get_default_db_path()
        
        self.db_path = db_path
        
        # 确保目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            try:
                os.makedirs(db_dir, exist_ok=True)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"创建数据库目录失败 {db_dir}: {e}")
                except Exception:
                    pass

        self._init_db()
        self._schedule_fastid_uuid_sync_on_first_load()

    def _normalize_bbox_json_str(self, v):
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            if len(v) < 4:
                return None
            try:
                return json.dumps([float(v[0]), float(v[1]), float(v[2]), float(v[3])])
            except Exception:
                return None
        if isinstance(v, dict):
            try:
                if "x" in v and "y" in v and "w" in v and "h" in v:
                    x = float(v.get("x"))
                    y = float(v.get("y"))
                    w = float(v.get("w"))
                    h = float(v.get("h"))
                    return json.dumps([x, y, x + w, y + h])
            except Exception:
                return None
            try:
                if "x" in v and "y" in v and "width" in v and "height" in v:
                    x = float(v.get("x"))
                    y = float(v.get("y"))
                    w = float(v.get("width"))
                    h = float(v.get("height"))
                    return json.dumps([x, y, x + w, y + h])
            except Exception:
                return None
            try:
                if "x1" in v and "y1" in v and "x2" in v and "y2" in v:
                    return json.dumps([float(v.get("x1")), float(v.get("y1")), float(v.get("x2")), float(v.get("y2"))])
            except Exception:
                return None
            try:
                if "left" in v and "top" in v and "right" in v and "bottom" in v:
                    return json.dumps([float(v.get("left")), float(v.get("top")), float(v.get("right")), float(v.get("bottom"))])
            except Exception:
                return None
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                obj = json.loads(s)
                return self._normalize_bbox_json_str(obj)
            except Exception:
                nums = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", s)
                if len(nums) >= 4:
                    try:
                        return json.dumps([float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])])
                    except Exception:
                        return None
            return None
        try:
            return self._normalize_bbox_json_str(str(v))
        except Exception:
            return None

    def _normalize_focus_point_json_str(self, v):
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            if len(v) < 2:
                return None
            try:
                return json.dumps([float(v[0]), float(v[1])])
            except Exception:
                return None
        if isinstance(v, dict):
            try:
                if "x" in v and "y" in v:
                    return json.dumps([float(v.get("x")), float(v.get("y"))])
            except Exception:
                return None
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                obj = json.loads(s)
                return self._normalize_focus_point_json_str(obj)
            except Exception:
                nums = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", s)
                if len(nums) >= 2:
                    try:
                        return json.dumps([float(nums[0]), float(nums[1])])
                    except Exception:
                        return None
            return None
        try:
            return self._normalize_focus_point_json_str(str(v))
        except Exception:
            return None

    def _schedule_fastid_uuid_sync_on_first_load(self):
        """
        第一次加载数据库时，强制补齐并对齐 fast_id 与 uuid：
        - 数据库：根据文件现状更新 fast_id（以 uuid 为主键更新）
        - Exif：若缺失或不一致，则写回 uuid/fast_id 到原文件
        
        注意：
        - 该同步会扫描 bird_results 全表，必须放在后台线程，避免阻塞 UI
        - 只启动一次，防止多个页面/组件重复触发全库同步
        """
        try:
            from utils.setting.settings_manager import SettingsManager
            settings = SettingsManager()
            is_first_run = settings.get("general/first_run", False)
            if isinstance(is_first_run, str):
                is_first_run = is_first_run.lower() == "true"
            if not bool(is_first_run):
                return
        except Exception:
            return

        with BirdLibraryDB._fastid_uuid_sync_guard:
            if BirdLibraryDB._fastid_uuid_sync_started:
                return
            BirdLibraryDB._fastid_uuid_sync_started = True

        t = threading.Thread(target=self._sync_fastid_uuid_for_existing_records, daemon=True)
        t.start()

    def _sync_fastid_uuid_for_existing_records(self):
        """
        后台执行：遍历 bird_results，强制将 uuid/fast_id 写回 Exif，并把 fast_id 写回数据库。
        
        同步策略：
        - 以数据库 uuid 为最终权威值（因为业务逻辑围绕 uuid 作为主键）
        - fast_id 使用文件系统快速计算值（优先 Windows 文件ID / inode 等）
        - Exif 缺失或不一致时更新；数据库 fast_id 不一致时更新
        """
        try:
            from utils.file.file_util import get_fast_id
            from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG, run_exiftool, get_exiftool_path
        except Exception:
            return

        try:
            conn = self._get_connection()
        except Exception:
            return

        try:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT uuid, fast_id, file_path FROM bird_results")
                rows = cursor.fetchall() or []
            except Exception:
                rows = []

            if not rows:
                return

            worker = ExifHandleWorker.get_instance()
            uuid_tag = EXIF_TAG.Uuid.value
            fastid_tag = EXIF_TAG.Fastid.value

            batch_size = 200
            exif_chunk_size = 50

            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]

                batch_paths = []
                batch_items = []
                for r in batch:
                    try:
                        uuid_val = r["uuid"]
                        db_fastid = r["fast_id"]
                        path = r["file_path"]
                    except Exception:
                        continue
                    if not uuid_val or not path:
                        continue
                    if not os.path.exists(path):
                        continue
                    computed_fastid = None
                    try:
                        computed_fastid = get_fast_id(path)
                    except Exception:
                        computed_fastid = None
                    batch_paths.append(path)
                    batch_items.append({
                        "uuid": uuid_val,
                        "db_fast_id": db_fastid,
                        "path": path,
                        "computed_fast_id": computed_fastid,
                    })

                if not batch_items:
                    continue

                path_exif_map = {}
                for j in range(0, len(batch_paths), exif_chunk_size):
                    chunk_paths = batch_paths[j:j + exif_chunk_size]
                    try:
                        cmd = [
                            get_exiftool_path(),
                            "-j",
                            "-charset",
                            "utf8",
                            "-" + uuid_tag,
                            "-" + fastid_tag,
                        ] + chunk_paths
                        res = run_exiftool(cmd)
                        if res.returncode != 0:
                            continue
                        data = json.loads(res.stdout or "[]")
                        if not isinstance(data, list):
                            continue
                        for entry in data:
                            src = entry.get("SourceFile")
                            if not src:
                                continue
                            path_exif_map[os.path.normpath(src)] = {
                                "uuid": entry.get(uuid_tag) or entry.get("Uuid"),
                                "fast_id": entry.get(fastid_tag) or entry.get("Fastid"),
                            }
                    except Exception:
                        continue

                exif_tasks = []
                db_updates = []

                for it in batch_items:
                    path = it["path"]
                    db_uuid = it["uuid"]
                    computed_fastid = it["computed_fast_id"]
                    db_fastid = it["db_fast_id"]

                    exif_info = path_exif_map.get(os.path.normpath(path)) or {}
                    exif_uuid = exif_info.get("uuid")
                    exif_fastid = exif_info.get("fast_id")

                    tags_to_write = {}
                    if not exif_uuid or str(exif_uuid) != str(db_uuid):
                        tags_to_write[uuid_tag] = db_uuid
                    if computed_fastid and (not exif_fastid or str(exif_fastid) != str(computed_fastid)):
                        tags_to_write[fastid_tag] = computed_fastid
                    if tags_to_write:
                        exif_tasks.append((path, tags_to_write))

                    if computed_fastid and str(db_fastid or "") != str(computed_fastid):
                        db_updates.append((computed_fastid, db_uuid))

                if db_updates:
                    with self._lock:
                        try:
                            cursor.executemany("UPDATE bird_results SET fast_id = ? WHERE uuid = ?", db_updates)
                            conn.commit()
                        except Exception:
                            pass

                if exif_tasks:
                    try:
                        worker.enqueue_update_tags(exif_tasks)
                    except Exception:
                        pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_user_fields_map(self, file_paths, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return {}
        if not file_paths:
            return {}

        norm_keys = []
        for p in file_paths:
            p_db = self._normalize_file_path_for_db(p)
            k = self._norm_path_key(p_db)
            if k:
                norm_keys.append(k)

        if not norm_keys:
            return {}

        uniq_keys = list(dict.fromkeys(norm_keys))

        results = {}
        # 移除只读锁，利用 SQLite WAL 并发读特性，避免阻塞 UI
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            batch_size = 200
            for i in range(0, len(uniq_keys), batch_size):
                batch = uniq_keys[i:i + batch_size]
                placeholders = ",".join(["?"] * len(batch))
                if os.name == 'nt':
                    cursor.execute(
                        f"SELECT file_path, is_favorite, rating, label, description, tags, location FROM {table_name} "
                        f"WHERE lower(replace(file_path, '/', '\\\\')) IN ({placeholders})",
                        batch
                    )
                else:
                    batch_lower = [b.lower() for b in batch]
                    cursor.execute(
                        f"SELECT file_path, is_favorite, rating, label, description, tags, location FROM {table_name} "
                        f"WHERE lower(file_path) IN ({placeholders})",
                        batch_lower
                    )

                for row in cursor.fetchall():
                    try:
                        key = self._norm_path_key(row['file_path'])
                    except Exception:
                        key = None
                    if not key:
                        continue
                    results[key] = {
                        'file_path': row['file_path'],
                        'is_favorite': int(row['is_favorite'] or 0) if row['is_favorite'] is not None else 0,
                        'rating': int(row['rating'] or 0) if row['rating'] is not None else 0,
                        'label': row['label'],
                        'description': row['description'],
                        'tags': row['tags'],
                        'location': row['location'],
                    }
        finally:
            conn.close()

        return results

    def _normalize_file_path_for_db(self, file_path):
        if not file_path:
            return None
        p = str(file_path)
        try:
            p = os.path.normpath(p)
        except Exception:
            pass
        if os.name == 'nt':
            try:
                p = p.replace("/", "\\")
            except Exception:
                pass
        return p

    def _norm_path_key(self, file_path):
        p = self._normalize_file_path_for_db(file_path)
        if not p:
            return None
        if os.name == 'nt':
            try:
                return p.lower()
            except Exception:
                return str(p).lower()
        return p

    def _dedupe_specific_normalized_paths(self, cursor, table_name, norm_keys):
        if not norm_keys:
            return

        if table_name not in ['bird_results', 'import_cache']:
            return

        if os.name != 'nt':
            return

        keys = [k for k in norm_keys if k]
        if not keys:
            return

        uniq_keys = list(dict.fromkeys(keys))
        batch_size = 200

        def row_quality(row_dict):
            score = 0
            for k in ('order_cls', 'family_cls', 'genus_cls', 'species_cls'):
                if row_dict.get(k):
                    score += 10
            if row_dict.get('shot_time'):
                score += 2
            if row_dict.get('score') is not None:
                try:
                    if float(row_dict.get('score') or 0) > 0:
                        score += 1
                except Exception:
                    pass
            if row_dict.get('bbox'):
                score += 1
            if row_dict.get('description'):
                score += 1
            return score

        for i in range(0, len(uniq_keys), batch_size):
            batch = uniq_keys[i:i + batch_size]
            placeholders = ','.join(['?'] * len(batch))
            cursor.execute(
                f"SELECT * FROM {table_name} WHERE lower(replace(file_path, '/', '\\')) IN ({placeholders})",
                batch
            )
            rows = cursor.fetchall()
            if not rows:
                continue

            groups = {}
            for r in rows:
                rd = dict(r)
                k = self._norm_path_key(rd.get('file_path'))
                if not k:
                    continue
                groups.setdefault(k, []).append(rd)

            for norm_key, items in groups.items():
                if len(items) <= 1:
                    one = items[0]
                    canonical = self._normalize_file_path_for_db(one.get('file_path'))
                    if canonical and one.get('file_path') != canonical:
                        try:
                            cursor.execute(
                                f"UPDATE {table_name} SET file_path = ?, file_name = ? WHERE uuid = ?",
                                (canonical, os.path.basename(canonical), one.get('uuid'))
                            )
                        except sqlite3.IntegrityError:
                            pass
                    continue

                keep = max(items, key=row_quality)
                canonical = self._normalize_file_path_for_db(keep.get('file_path')) or keep.get('file_path')

                merged_is_favorite = 0
                merged_rating = 0
                merged_label = keep.get('label') or ''
                merged_description = keep.get('description') or ''

                merged_order = keep.get('order_cls') or ''
                merged_family = keep.get('family_cls') or ''
                merged_genus = keep.get('genus_cls') or ''
                merged_species = keep.get('species_cls') or ''
                
                # Merge tags (union of all tags)
                tags_set = set()
                if keep.get('tags'):
                    tags_set.update(str(keep.get('tags')).split('|'))
                
                merged_location = keep.get('location') or ''

                for it in items:
                    try:
                        merged_is_favorite = max(merged_is_favorite, int(it.get('is_favorite') or 0))
                    except Exception:
                        pass
                    try:
                        merged_rating = max(merged_rating, int(it.get('rating') or 0))
                    except Exception:
                        pass

                    if not merged_label and it.get('label'):
                        merged_label = it.get('label')
                    if not merged_description and it.get('description'):
                        merged_description = it.get('description')
                    
                    if it.get('tags'):
                        tags_set.update(str(it.get('tags')).split('|'))
                    
                    if not merged_location and it.get('location'):
                        merged_location = it.get('location')

                    if not merged_order and it.get('order_cls'):
                        merged_order = it.get('order_cls')
                    if not merged_family and it.get('family_cls'):
                        merged_family = it.get('family_cls')
                    if not merged_genus and it.get('genus_cls'):
                        merged_genus = it.get('genus_cls')
                    if not merged_species and it.get('species_cls'):
                        merged_species = it.get('species_cls')

                merged_tags_str = '|'.join(sorted([t for t in tags_set if t]))
                keep_uuid = keep.get('uuid')
                cursor.execute(
                    f"""
                    UPDATE {table_name} SET
                        file_path = ?,
                        file_name = ?,
                        label = ?,
                        rating = ?,
                        is_favorite = ?,
                        description = ?,
                        order_cls = ?,
                        family_cls = ?,
                        genus_cls = ?,
                        species_cls = ?,
                        tags = ?,
                        location = ?
                    WHERE uuid = ?
                    """,
                    (
                        canonical,
                        os.path.basename(canonical),
                        merged_label,
                        merged_rating,
                        merged_is_favorite,
                        merged_description,
                        merged_order,
                        merged_family,
                        merged_genus,
                        merged_species,
                        merged_tags_str,
                        merged_location,
                        keep_uuid,
                    )
                )

                delete_uuids = [it.get('uuid') for it in items if it.get('uuid') and it.get('uuid') != keep_uuid]
                if delete_uuids:
                    for j in range(0, len(delete_uuids), 200):
                        d_batch = delete_uuids[j:j + 200]
                        d_placeholders = ','.join(['?'] * len(d_batch))
                        cursor.execute(
                            f"DELETE FROM {table_name} WHERE uuid IN ({d_placeholders})",
                            d_batch
                        )

    def _dedupe_all_paths(self, cursor, table_name):
        if table_name not in ['bird_results', 'import_cache']:
            return
        if os.name != 'nt':
            return

        try:
            cursor.execute(
                f"SELECT 1 FROM {table_name} GROUP BY lower(replace(file_path, '/', '\\')) HAVING COUNT(*) > 1 LIMIT 1"
            )
            has_dupe = cursor.fetchone() is not None
        except Exception:
            has_dupe = False

        try:
            cursor.execute(f"SELECT 1 FROM {table_name} WHERE instr(file_path, '/') > 0 LIMIT 1")
            has_slash = cursor.fetchone() is not None
        except Exception:
            has_slash = False

        if not has_dupe and not has_slash:
            return

        cursor.execute(f"SELECT file_path FROM {table_name}")
        rows = cursor.fetchall()
        keys = []
        seen = set()
        for r in rows:
            k = self._norm_path_key(r['file_path'])
            if not k or k in seen:
                continue
            seen.add(k)
            keys.append(k)

        self._dedupe_specific_normalized_paths(cursor, table_name, keys)

    def _get_connection(self):
        # check_same_thread=False 允许在多线程中复用连接（配合锁使用）
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row  # 让 cursor 返回类似字典的对象
        try:
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        return conn

    def _check_database_integrity(self):
        """检查数据库完整性，如果损坏则备份并重建"""
        if not os.path.exists(self.db_path):
            return True
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] == 'ok':
                return True
            
            LogManager.instance().warning(f"[DB] Database integrity check failed: {result}")
            return False
        except Exception as e:
            LogManager.instance().warning(f"[DB] Database integrity check error: {e}")
            return False

    def _backup_and_rebuild_database(self):
        """备份损坏的数据库并重建"""
        try:
            import shutil
            from datetime import datetime
            
            backup_path = f"{self.db_path}.corrupted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            shutil.copy2(self.db_path, backup_path)
            LogManager.instance().info(f"[DB] Corrupted database backed up to: {backup_path}")
            
            os.remove(self.db_path)
            LogManager.instance().info(f"[DB] Corrupted database removed, will create new one")
            return True
        except Exception as e:
            LogManager.instance().warning(f"[DB] Failed to backup/rebuild database: {e}")
            return False

    def _init_db(self):
        """初始化数据库：创建表结构"""
        try:
            LogManager.instance().info(f"[DB] Initializing database at {self.db_path}")
        except Exception:
            pass
        
        if os.path.exists(self.db_path):
            if not self._check_database_integrity():
                self._backup_and_rebuild_database()
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 创建结果表 (图库用)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bird_results (
                    uuid TEXT PRIMARY KEY,      -- 终身唯一 ID
                    fast_id TEXT,               -- 快速指纹 (size_mtime)
                    file_path TEXT UNIQUE,      -- 文件绝对路径
                    file_name TEXT,            -- 文件名
                    label TEXT,                -- 色标 (Green, Blue, Yellow, Red, Purple, White, Orange, Pink, Black)
                    score REAL,                -- 原始得分
                    norm_score REAL,           -- 归一化得分
                    bbox TEXT,                 -- 主体框坐标 [x, y, width, height] (存储为 JSON 字符串)
                    position TEXT,         -- 九宫格位置索引 (Top、Right)
                    pixel_count INTEGER,       -- 像素大小
                    area_ratio REAL DEFAULT 0.0, -- 图像占比
                    focus_point TEXT,          -- 对焦点位置 (JSON 字符串)
                    object TEXT,               -- 物种
                    order_cls TEXT,            -- 目
                    family_cls TEXT,           -- 科
                    genus_cls TEXT,            -- 属
                    species_cls TEXT,          -- 种
                    eye_coordinates TEXT,      -- 眼睛位置 (JSON 字符串)
                    description TEXT,          -- BmpDescription
                    focus_detect_json TEXT DEFAULT '', -- 对焦检测附加信息 (JSON 字符串)
                    is_favorite INTEGER DEFAULT 0, -- 是否收藏 (0: 否, 1: 是)
                    rating INTEGER DEFAULT 0,      -- 评分 (0-5)
                    shot_time TEXT,            -- 拍摄时间
                    fnumber REAL DEFAULT 0, -- 光圈值
                    shutter TEXT DEFAULT '', -- 快门速度
                    iso REAL DEFAULT 0, -- ISO 值
                    focal_length TEXT DEFAULT '', -- 焦距
                    camera_model TEXT DEFAULT '', -- 相机型号
                    lens_model TEXT DEFAULT '', -- 镜头型号
                    focus_distance TEXT DEFAULT '', -- 对焦距离
                    latitude REAL DEFAULT 0,
                    longitude REAL DEFAULT 0,
                    location TEXT DEFAULT '',
                    region_code TEXT DEFAULT '',  -- 区域代码（如 CN, CN-44, US-CA）
                    tags TEXT DEFAULT '',
                    imported_at TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 添加索引以优化查询速度
            try:
                # 针对分类查询的复合索引 (order/family/genus/species)
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bird_results_taxonomy ON bird_results (order_cls, family_cls, genus_cls, species_cls)')
                # 针对拍摄时间的索引（用于排序）
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bird_results_shot_time ON bird_results (shot_time DESC)')
                # 针对导入时间的索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bird_results_imported_at ON bird_results (imported_at DESC)')
                # 针对是否收藏的索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bird_results_favorite ON bird_results (is_favorite)')
                # 针对评分的索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bird_results_rating ON bird_results (rating)')
                # 针对区域代码的索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bird_results_region_code ON bird_results (region_code)')
            except Exception:
                pass
            
            # 创建导入缓存表 (导入页面用，结构与结果表类似，但用于临时存储待导入或正在处理的数据)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS import_cache (
                    uuid TEXT PRIMARY KEY,      -- 终身唯一 ID
                    fast_id TEXT,               -- 快速指纹 (size_mtime)
                    file_path TEXT UNIQUE,      -- 文件绝对路径
                    file_name TEXT,            -- 文件名
                    label TEXT,                -- 色标 (Green, Blue, Yellow, Red, Purple, White, Orange, Pink, Black)
                    score REAL,                -- 原始得分
                    norm_score REAL,           -- 归一化得分
                    bbox TEXT,                 -- 主体框坐标 [x, y, width, height] (存储为 JSON 字符串)
                    position TEXT,         -- 九宫格位置索引 (Top、Right)
                    pixel_count INTEGER,       -- 像素大小
                    area_ratio REAL DEFAULT 0.0, -- 图像占比
                    focus_point TEXT,          -- 对焦点位置 (JSON 字符串)
                    object TEXT,               -- 物种
                    order_cls TEXT,            -- 目
                    family_cls TEXT,           -- 科
                    genus_cls TEXT,            -- 属
                    species_cls TEXT,          -- 种
                    eye_coordinates TEXT,      -- 眼睛位置 (JSON 字符串)
                    description TEXT,          -- BmpDescription
                    focus_detect_json TEXT DEFAULT '', -- 对焦检测附加信息 (JSON 字符串)
                    is_favorite INTEGER DEFAULT 0, -- 是否收藏 (0: 否, 1: 是)
                    rating INTEGER DEFAULT 0,      -- 评分 (0-5)
                    shot_time TEXT,            -- 拍摄时间
                    fnumber REAL DEFAULT 0, -- 光圈值
                    shutter TEXT DEFAULT '', -- 快门速度
                    iso REAL DEFAULT 0, -- ISO 值
                    focal_length TEXT DEFAULT '', -- 焦距
                    camera_model TEXT DEFAULT '', -- 相机型号
                    lens_model TEXT DEFAULT '', -- 镜头型号
                    focus_distance TEXT DEFAULT '', -- 对焦距离
                    latitude REAL DEFAULT 0,
                    longitude REAL DEFAULT 0,
                    location TEXT DEFAULT '',
                    region_code TEXT DEFAULT '',  -- 区域代码（如 CN, CN-44, US-CA）
                    tags TEXT DEFAULT '',
                    imported_at TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            try:
                cursor.execute("ALTER TABLE bird_results ADD COLUMN imported_at TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE import_cache ADD COLUMN imported_at TEXT DEFAULT ''")
            except Exception:
                pass
            # 为现有数据库添加region_code字段
            try:
                cursor.execute("ALTER TABLE bird_results ADD COLUMN region_code TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE import_cache ADD COLUMN region_code TEXT DEFAULT ''")
            except Exception:
                pass

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS thumbnail_disk_cache (
                    cache_key TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    cache_rel_path TEXT NOT NULL,
                    source_size INTEGER DEFAULT 0,
                    source_mtime REAL DEFAULT 0,
                    cache_bytes INTEGER DEFAULT 0,
                    file_path TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_access DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (cache_key, variant)
                )
            ''')

            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_thumbnail_disk_cache_key ON thumbnail_disk_cache(cache_key)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_thumbnail_disk_cache_access ON thumbnail_disk_cache(last_access)')
                cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_thumbnail_disk_cache_rel ON thumbnail_disk_cache(cache_rel_path)')
            except Exception:
                pass

            for t in ["thumbnail_disk_cache_library", "thumbnail_disk_cache_import"]:
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {t} (
                        cache_key TEXT NOT NULL,
                        variant TEXT NOT NULL,
                        cache_rel_path TEXT NOT NULL,
                        source_size INTEGER DEFAULT 0,
                        source_mtime REAL DEFAULT 0,
                        cache_bytes INTEGER DEFAULT 0,
                        file_path TEXT DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        last_access DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (cache_key, variant)
                    )
                ''')
                try:
                    cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_{t}_key ON {t}(cache_key)')
                    cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_{t}_created ON {t}(created_at)')
                    cursor.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{t}_rel ON {t}(cache_rel_path)')
                except Exception:
                    pass
            
            self._migrate_tables(conn)
            try:
                self._dedupe_all_paths(cursor, 'bird_results')
                self._dedupe_all_paths(cursor, 'import_cache')
            except Exception:
                pass

            conn.commit()
            conn.close()

    def _get_thumbnail_disk_cache_table(self, scope):
        s = str(scope or "library").lower()
        if s in ["import", "import_cache"]:
            return "thumbnail_disk_cache_import"
        return "thumbnail_disk_cache_library"

    def get_all_orders(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT order_cls FROM bird_results WHERE order_cls IS NOT NULL AND TRIM(order_cls) != '' ORDER BY order_cls")
            rows = cursor.fetchall() or []
            return [r["order_cls"] for r in rows if r["order_cls"]]
        finally:
            conn.close()

    def get_families_by_order(self, order_name: str):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT family_cls FROM bird_results WHERE order_cls = ? AND family_cls IS NOT NULL AND TRIM(family_cls) != '' ORDER BY family_cls",
                (str(order_name),),
            )
            rows = cursor.fetchall() or []
            return [r["family_cls"] for r in rows if r["family_cls"]]
        finally:
            conn.close()

    def get_genera_by_family(self, family_name: str):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT genus_cls FROM bird_results WHERE family_cls = ? AND genus_cls IS NOT NULL AND TRIM(genus_cls) != '' ORDER BY genus_cls",
                (str(family_name),),
            )
            rows = cursor.fetchall() or []
            return [r["genus_cls"] for r in rows if r["genus_cls"]]
        finally:
            conn.close()

    def get_species_by_genus(self, genus_name: str):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT species_cls FROM bird_results WHERE genus_cls = ? AND species_cls IS NOT NULL AND TRIM(species_cls) != '' ORDER BY species_cls",
                (str(genus_name),),
            )
            rows = cursor.fetchall() or []
            return [r["species_cls"] for r in rows if r["species_cls"]]
        finally:
            conn.close()

    def get_image_count_by_species(self, species_name: str) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(1) AS c FROM bird_results WHERE species_cls = ?",
                (str(species_name),),
            )
            row = cursor.fetchone()
            return int(row["c"] if row and row["c"] is not None else 0)
        finally:
            conn.close()

    def get_thumbnail_disk_cache(self, cache_key, variant, scope="library"):
        if not cache_key or not variant:
            return None
        table = self._get_thumbnail_disk_cache_table(scope)
        # 移除只读锁
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT cache_key, variant, cache_rel_path, source_size, source_mtime, cache_bytes, file_path FROM {table} "
                "WHERE cache_key = ? AND variant = ? LIMIT 1",
                (str(cache_key), str(variant))
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "cache_key": row["cache_key"],
                "variant": row["variant"],
                "cache_rel_path": row["cache_rel_path"],
                "source_size": row["source_size"],
                "source_mtime": row["source_mtime"],
                "cache_bytes": row["cache_bytes"],
                "file_path": row["file_path"],
            }
        finally:
            conn.close()

    def upsert_thumbnail_disk_cache(self, cache_key, variant, cache_rel_path, source_size, source_mtime, cache_bytes=0, file_path="", scope="library"):
        if not cache_key or not variant or not cache_rel_path:
            return
        table = self._get_thumbnail_disk_cache_table(scope)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"INSERT INTO {table}(cache_key, variant, cache_rel_path, source_size, source_mtime, cache_bytes, file_path, last_access) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(cache_key, variant) DO UPDATE SET "
                    "cache_rel_path=excluded.cache_rel_path, "
                    "source_size=excluded.source_size, "
                    "source_mtime=excluded.source_mtime, "
                    "cache_bytes=excluded.cache_bytes, "
                    "file_path=excluded.file_path, "
                    "last_access=CURRENT_TIMESTAMP",
                    (str(cache_key), str(variant), str(cache_rel_path), int(source_size or 0), float(source_mtime or 0.0), int(cache_bytes or 0), str(file_path or ""))
                )
                conn.commit()
            finally:
                conn.close()

    def touch_thumbnail_disk_cache(self, cache_key, variant, scope="library"):
        if not cache_key or not variant:
            return
        table = self._get_thumbnail_disk_cache_table(scope)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE {table} SET last_access=CURRENT_TIMESTAMP WHERE cache_key=? AND variant=?",
                    (str(cache_key), str(variant))
                )
                conn.commit()
            finally:
                conn.close()

    def delete_thumbnail_disk_cache(self, cache_key, variant, scope="library"):
        if not cache_key or not variant:
            return
        table = self._get_thumbnail_disk_cache_table(scope)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM {table} WHERE cache_key=? AND variant=?",
                    (str(cache_key), str(variant))
                )
                conn.commit()
            finally:
                conn.close()

    def clear_thumbnail_disk_cache(self, scope="library"):
        table = self._get_thumbnail_disk_cache_table(scope)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(f"DELETE FROM {table}")
                conn.commit()
            finally:
                conn.close()

    def sum_thumbnail_disk_cache_bytes(self, scope="library"):
        table = self._get_thumbnail_disk_cache_table(scope)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(f"SELECT SUM(cache_bytes) AS total_bytes FROM {table}")
                row = cursor.fetchone()
                if not row or row["total_bytes"] is None:
                    return 0
                try:
                    return int(row["total_bytes"])
                except Exception:
                    return 0
            finally:
                conn.close()

    def list_thumbnail_disk_cache(self, scope="library", order_by_created_asc=True, limit=50000):
        try:
            limit = int(limit)
        except Exception:
            limit = 50000
        order = "ASC" if order_by_created_asc else "DESC"
        table = self._get_thumbnail_disk_cache_table(scope)
        rows = []
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT cache_key, variant, cache_rel_path, source_size, source_mtime, cache_bytes, file_path, created_at, last_access "
                    f"FROM {table} ORDER BY created_at {order} LIMIT ?",
                    (limit,)
                )
                for r in cursor.fetchall() or []:
                    rows.append({
                        "cache_key": r["cache_key"],
                        "variant": r["variant"],
                        "cache_rel_path": r["cache_rel_path"],
                        "source_size": r["source_size"],
                        "source_mtime": r["source_mtime"],
                        "cache_bytes": r["cache_bytes"],
                        "file_path": r["file_path"],
                        "created_at": r["created_at"],
                        "last_access": r["last_access"],
                    })
            finally:
                conn.close()
        return rows

    def list_thumbnail_disk_cache_by_key(self, cache_key: str, scope="library", limit=200000):
        if not cache_key:
            return []
        try:
            limit = int(limit)
        except Exception:
            limit = 200000
        table = self._get_thumbnail_disk_cache_table(scope)
        rows = []
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT cache_key, variant, cache_rel_path FROM {table} WHERE cache_key=? LIMIT ?",
                    (str(cache_key), limit),
                )
                for r in cursor.fetchall() or []:
                    rows.append(
                        {
                            "cache_key": r["cache_key"],
                            "variant": r["variant"],
                            "cache_rel_path": r["cache_rel_path"],
                        }
                    )
            finally:
                conn.close()
        return rows

    def delete_thumbnail_disk_cache_by_key(self, cache_key: str, scope="library"):
        if not cache_key:
            return
        table = self._get_thumbnail_disk_cache_table(scope)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(f"DELETE FROM {table} WHERE cache_key=?", (str(cache_key),))
                conn.commit()
            finally:
                conn.close()

    def _migrate_tables(self, conn):
        """迁移表结构：添加缺失的列"""
        cursor = conn.cursor()
        
        # 需要检查的列定义 {table_name: {column_name: column_def}}
        # 仅列出可能后期添加的字段
        tables_columns = {
            'bird_results': {
                'label': 'TEXT',
                'rating': 'INTEGER DEFAULT 0',
                'is_favorite': 'INTEGER DEFAULT 0',
                'description': 'TEXT',
                'order_cls': 'TEXT',
                'family_cls': 'TEXT',
                'genus_cls': 'TEXT',
                'species_cls': 'TEXT',
                'eye_coordinates': 'TEXT',
                'focus_point': 'TEXT',
                'bbox': 'TEXT',
                'position': 'TEXT',
                'norm_score': 'REAL',
                'score': 'REAL',
                'fast_id': 'TEXT',
                'shot_time': 'TEXT',
                'fnumber': 'REAL DEFAULT 0',
                'shutter': 'TEXT DEFAULT ""',
                'iso': 'REAL DEFAULT 0',
                'focal_length': 'TEXT DEFAULT ""',
                'camera_model': 'TEXT DEFAULT ""',
                'lens_model': 'TEXT DEFAULT ""',
                'focus_distance': 'TEXT DEFAULT ""',
                'latitude': 'REAL DEFAULT 0',
                'longitude': 'REAL DEFAULT 0',
                'location': 'TEXT DEFAULT ""',
                'tags': 'TEXT DEFAULT ""'
                ,
                'focus_detect_json': 'TEXT DEFAULT ""'
            },
            'import_cache': {
                'label': 'TEXT',
                'rating': 'INTEGER DEFAULT 0',
                'is_favorite': 'INTEGER DEFAULT 0',
                'description': 'TEXT',
                'order_cls': 'TEXT',
                'family_cls': 'TEXT',
                'genus_cls': 'TEXT',
                'species_cls': 'TEXT',
                'eye_coordinates': 'TEXT',
                'focus_point': 'TEXT',
                'bbox': 'TEXT',
                'position': 'TEXT',
                'norm_score': 'REAL',
                'score': 'REAL',
                'fast_id': 'TEXT',
                'shot_time': 'TEXT',
                'fnumber': 'REAL DEFAULT 0',
                'shutter': 'TEXT DEFAULT ""',
                'iso': 'REAL DEFAULT 0',
                'focal_length': 'TEXT DEFAULT ""',
                'camera_model': 'TEXT DEFAULT ""',
                'lens_model': 'TEXT DEFAULT ""',
                'focus_distance': 'TEXT DEFAULT ""',
                'latitude': 'REAL DEFAULT 0',
                'longitude': 'REAL DEFAULT 0',
                'location': 'TEXT DEFAULT ""',
                'tags': 'TEXT DEFAULT ""'
                ,
                'focus_detect_json': 'TEXT DEFAULT ""'
            }
        }
        
        for table, columns in tables_columns.items():
            # 先检查表是否存在
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if not cursor.fetchone():
                continue
                
            for col_name, col_def in columns.items():
                self._check_and_add_column(cursor, table, col_name, col_def)

    def _check_and_add_column(self, cursor, table_name, column_name, column_def):
        """检查列是否存在，不存在则添加"""
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [info[1] for info in cursor.fetchall()]
        if column_name not in columns:
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
                try:
                    LogManager.instance().info(f"数据库新增列: {table_name}.{column_name}")
                except Exception:
                    pass
            except Exception as e:
                try:
                    LogManager.instance().warning(f"数据库新增列失败 {table_name}.{column_name}: {e}")
                except Exception:
                    pass

    def get_top_favorite_images(self, limit=200):
        """获取前 N 张收藏图片路径 (用于预加载)"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # 按收藏时间和创建时间倒序
                cursor.execute(f"SELECT file_path FROM bird_results WHERE is_favorite = 1 ORDER BY created_at DESC LIMIT {limit}")
                rows = cursor.fetchall()
                return [row['file_path'] for row in rows]
            except Exception as e:
                try:
                    LogManager.instance().warning(f"获取收藏图片失败: {e}")
                except Exception:
                    pass
                return []
            finally:
                conn.close()

    def get_top_species_images(self, limit=200):
        """获取前 N 张物种图片路径 (按分类法排序，用于预加载)"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # 按分类法排序: 目 -> 科 -> 属 -> 种 -> 分数倒序
                cursor.execute(f"""
                    SELECT file_path FROM bird_results 
                    WHERE species_cls IS NOT NULL AND species_cls != ''
                    ORDER BY order_cls, family_cls, genus_cls, species_cls, score DESC 
                    LIMIT {limit}
                """)
                rows = cursor.fetchall()
                try:
                    LogManager.instance().debug(f"Top species images rows={len(rows)}")
                except Exception:
                    pass
                return [row['file_path'] for row in rows]
            except Exception as e:
                try:
                    LogManager.instance().warning(f"获取物种图片失败: {e}")
                except Exception:
                    pass
                return []
            finally:
                conn.close()

    def get_folder_stats(self, folder_path=None):
        """
        获取文件夹统计信息 (递归)
        Args:
            folder_path: 文件夹路径，如果为 None 则统计所有
        Returns:
            dict: {'image_count': int, 'species_count': int}
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                if folder_path:
                    # 使用 LIKE 进行前缀匹配，模拟递归查询
                    # 注意：Windows 路径分隔符可能是 \ 或 /，最好统一处理
                    # 这里假设数据库中存储的是标准化的路径，或者使用 LIKE 'path%'
                    # 为了更健壮，可以尝试替换分隔符
                    
                    # 确保路径以分隔符结尾，避免部分匹配 (e.g. /foo matching /foobar)
                    normalized_path = os.path.normpath(folder_path)
                    if not normalized_path.endswith(os.sep):
                        normalized_path += os.sep
                        
                    # 在 SQL 中，我们使用 % 来匹配任意字符
                    # 由于路径分隔符问题，可能需要尝试多种匹配方式，或者依赖应用层存储的一致性
                    # 假设存储的是绝对路径，且分隔符一致
                    
                    # 构造查询: 路径以 folder_path 开头
                    # 为了兼容 Windows 反斜杠，在 SQL 中可能比较麻烦，
                    # 建议应用层保证存储路径的一致性。
                    # 这里简单使用 LIKE pattern
                    
                    pattern = f"{normalized_path}%"
                    
                    # 统计图片总数
                    cursor.execute("SELECT COUNT(*) FROM bird_results WHERE file_path LIKE ?", (pattern,))
                    image_count = cursor.fetchone()[0]
                    
                    # 统计物种总数 (去重)
                    # species_cls 字段存储种名
                    cursor.execute("SELECT COUNT(DISTINCT species_cls) FROM bird_results WHERE file_path LIKE ? AND species_cls IS NOT NULL AND species_cls != ''", (pattern,))
                    species_count = cursor.fetchone()[0]
                    
                else:
                    # 统计所有
                    cursor.execute("SELECT COUNT(*) FROM bird_results")
                    image_count = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(DISTINCT species_cls) FROM bird_results WHERE species_cls IS NOT NULL AND species_cls != ''")
                    species_count = cursor.fetchone()[0]
                    
                return {'image_count': image_count, 'species_count': species_count}
                
            except Exception as e:
                try:
                    LogManager.instance().warning(f"获取文件夹统计失败: {e}")
                except Exception:
                    pass
                return {'image_count': 0, 'species_count': 0}
            finally:
                conn.close()

    def get_taxonomy_tree_stats(self, table_name: str = "bird_results", root_path: str | None = None):
        if table_name not in ["bird_results", "import_cache"]:
            table_name = "bird_results"
        root_slash = ""
        root_back = ""
        try:
            rp = str(root_path or "").strip()
        except Exception:
            rp = ""
        if rp:
            try:
                root_slash = rp.replace("\\", "/")
            except Exception:
                root_slash = rp
            try:
                root_back = rp.replace("/", "\\")
            except Exception:
                root_back = rp
            if root_slash and not root_slash.endswith("/"):
                root_slash += "/"
            if root_back and not root_back.endswith("\\"):
                root_back += "\\"
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                classified_sql = f"""
                    SELECT
                        order_cls AS o,
                        family_cls AS f,
                        genus_cls AS g,
                        species_cls AS s,
                        COUNT(*) AS cnt
                    FROM {table_name}
                    WHERE order_cls IS NOT NULL AND order_cls != ''
                      AND family_cls IS NOT NULL AND family_cls != ''
                      AND genus_cls IS NOT NULL AND genus_cls != ''
                      AND species_cls IS NOT NULL AND species_cls != ''
                """
                classified_params = []
                if root_slash or root_back:
                    classified_sql += " AND (file_path LIKE ? OR file_path LIKE ?)"
                    classified_params.extend([f"{root_slash}%", f"{root_back}%"])
                classified_sql += " GROUP BY order_cls, family_cls, genus_cls, species_cls"
                cursor.execute(classified_sql, classified_params)
                rows = cursor.fetchall() or []
                unclassified_sql = f"""
                    SELECT COUNT(*) AS cnt
                    FROM {table_name}
                    WHERE (order_cls IS NULL OR order_cls = ''
                       OR family_cls IS NULL OR family_cls = ''
                       OR genus_cls IS NULL OR genus_cls = ''
                       OR species_cls IS NULL OR species_cls = '')
                """
                unclassified_params = []
                if root_slash or root_back:
                    unclassified_sql += " AND (file_path LIKE ? OR file_path LIKE ?)"
                    unclassified_params.extend([f"{root_slash}%", f"{root_back}%"])
                cursor.execute(unclassified_sql, unclassified_params)
                unclassified = 0
                try:
                    r = cursor.fetchone()
                    if r:
                        unclassified = int(r["cnt"] or 0)
                except Exception:
                    unclassified = 0

                tree = {}
                for r in rows:
                    o = str(r["o"] or "").strip()
                    f = str(r["f"] or "").strip()
                    g = str(r["g"] or "").strip()
                    s = str(r["s"] or "").strip()
                    cnt = int(r["cnt"] or 0)
                    if not (o and f and g and s):
                        continue
                    o_node = tree.setdefault(o, {"_count": 0, "_species": set(), "children": {}})
                    o_node["_count"] += cnt
                    o_node["_species"].add(s)
                    f_node = o_node["children"].setdefault(f, {"_count": 0, "_species": set(), "children": {}})
                    f_node["_count"] += cnt
                    f_node["_species"].add(s)
                    g_node = f_node["children"].setdefault(g, {"_count": 0, "_species": set(), "children": {}})
                    g_node["_count"] += cnt
                    g_node["_species"].add(s)
                    s_node = g_node["children"].setdefault(s, {"_count": 0, "_species": set(), "children": {}})
                    s_node["_count"] += cnt
                    s_node["_species"].add(s)

                def _finalize(node):
                    try:
                        species_count = len(node.get("_species") or set())
                    except Exception:
                        species_count = 0
                    node["species_count"] = int(species_count)
                    node["image_count"] = int(node.get("_count") or 0)
                    try:
                        node.pop("_species", None)
                        node.pop("_count", None)
                    except Exception:
                        pass
                    children = node.get("children") or {}
                    for _k, child in children.items():
                        _finalize(child)

                for _k, n in tree.items():
                    _finalize(n)

                return {"tree": tree, "unclassified_image_count": int(unclassified)}
            except Exception as e:
                try:
                    LogManager.instance().warning(f"获取分类树统计失败: {e}")
                except Exception:
                    pass
                return {"tree": {}, "unclassified_image_count": 0}
            finally:
                conn.close()

    def query_images_by_taxonomy(self, order_cls=None, family_cls=None, genus_cls=None, species_cls=None, unclassified=False, table_name: str = "bird_results", limit=None, root_path: str | None = None):
        if table_name not in ["bird_results", "import_cache"]:
            table_name = "bird_results"
        # 移除只读锁，利用 SQLite WAL 并发读特性，避免阻塞 UI
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            wheres = []
            params = []
            try:
                rp = str(root_path or "").strip()
            except Exception:
                rp = ""
            if rp:
                try:
                    root_slash = rp.replace("\\", "/")
                except Exception:
                    root_slash = rp
                try:
                    root_back = rp.replace("/", "\\")
                except Exception:
                    root_back = rp
                if root_slash and not root_slash.endswith("/"):
                    root_slash += "/"
                if root_back and not root_back.endswith("\\"):
                    root_back += "\\"
                wheres.append("(file_path LIKE ? OR file_path LIKE ?)")
                params.extend([f"{root_slash}%", f"{root_back}%"])
            if unclassified:
                # [Fix] 优化未分类的判断逻辑，确保所有层级缺失或部分缺失的情况都被涵盖
                # 之前的逻辑: (O is null) OR (F is null) OR ... 只要有一个为空就算未分类，这没问题
                # 但需要确认是否有一些特殊字符或空白
                wheres.append("""(
                    order_cls IS NULL OR trim(order_cls) = '' OR 
                    family_cls IS NULL OR trim(family_cls) = '' OR 
                    genus_cls IS NULL OR trim(genus_cls) = '' OR 
                    species_cls IS NULL OR trim(species_cls) = ''
                )""")
            else:
                wheres.append("""(
                    order_cls IS NOT NULL AND trim(order_cls) != '' AND 
                    family_cls IS NOT NULL AND trim(family_cls) != '' AND 
                    genus_cls IS NOT NULL AND trim(genus_cls) != '' AND 
                    species_cls IS NOT NULL AND trim(species_cls) != ''
                )""")
                if order_cls:
                    wheres.append("order_cls = ?")
                    params.append(str(order_cls))
                if family_cls:
                    wheres.append("family_cls = ?")
                    params.append(str(family_cls))
                if genus_cls:
                    wheres.append("genus_cls = ?")
                    params.append(str(genus_cls))
                if species_cls:
                    wheres.append("species_cls = ?")
                    params.append(str(species_cls))
            where_sql = ""
            if wheres:
                where_sql = "WHERE " + " AND ".join(wheres)
            limit_sql = f"LIMIT {int(limit)}" if isinstance(limit, int) and limit > 0 else ""
            cursor.execute(
                f"""
                SELECT
                    file_path, file_name, shot_time, created_at, position, score, norm_score,
                    bbox, focus_point, focus_detect_json,
                    label, order_cls, family_cls, genus_cls, species_cls, is_favorite, rating, uuid,
                    fnumber, shutter, iso, focal_length, camera_model, lens_model, tags, location
                FROM {table_name}
                {where_sql}
                ORDER BY order_cls, family_cls, genus_cls, species_cls, shot_time DESC, created_at DESC
                {limit_sql}
                """,
                params,
            )
            return cursor.fetchall() or []
        except Exception as e:
                try:
                    LogManager.instance().warning(f"按分类查询图片失败: {e}")
                except Exception:
                    pass
                return []
        finally:
            conn.close()

    def get_taxonomy_node_stats(self, order_cls=None, family_cls=None, genus_cls=None, species_cls=None, unclassified=False, table_name: str = "bird_results", root_path: str | None = None):
        if table_name not in ["bird_results", "import_cache"]:
            table_name = "bird_results"
        # 移除只读锁，利用 SQLite WAL 并发读特性，避免阻塞 UI
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            wheres = []
            params = []
            try:
                rp = str(root_path or "").strip()
            except Exception:
                rp = ""
            if rp:
                try:
                    root_slash = rp.replace("\\", "/")
                except Exception:
                    root_slash = rp
                try:
                    root_back = rp.replace("/", "\\")
                except Exception:
                    root_back = rp
                if root_slash and not root_slash.endswith("/"):
                    root_slash += "/"
                if root_back and not root_back.endswith("\\"):
                    root_back += "\\"
                wheres.append("(file_path LIKE ? OR file_path LIKE ?)")
                params.extend([f"{root_slash}%", f"{root_back}%"])
            if unclassified:
                # [Fix] 优化未分类的判断逻辑
                wheres.append("""(
                    order_cls IS NULL OR trim(order_cls) = '' OR 
                    family_cls IS NULL OR trim(family_cls) = '' OR 
                    genus_cls IS NULL OR trim(genus_cls) = '' OR 
                    species_cls IS NULL OR trim(species_cls) = ''
                )""")
            else:
                wheres.append("""(
                    order_cls IS NOT NULL AND trim(order_cls) != '' AND 
                    family_cls IS NOT NULL AND trim(family_cls) != '' AND 
                    genus_cls IS NOT NULL AND trim(genus_cls) != '' AND 
                    species_cls IS NOT NULL AND trim(species_cls) != ''
                )""")
                if order_cls:
                    wheres.append("order_cls = ?")
                    params.append(str(order_cls))
                if family_cls:
                    wheres.append("family_cls = ?")
                    params.append(str(family_cls))
                if genus_cls:
                    wheres.append("genus_cls = ?")
                    params.append(str(genus_cls))
                if species_cls:
                    wheres.append("species_cls = ?")
                    params.append(str(species_cls))
            where_sql = "WHERE " + " AND ".join(wheres) if wheres else ""
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name} {where_sql}", params)
            image_count = 0
            try:
                r = cursor.fetchone()
                if r:
                    image_count = int(r["cnt"] or 0)
            except Exception:
                image_count = 0
            species_count = 0
            if not unclassified:
                cursor.execute(f"SELECT COUNT(DISTINCT species_cls) AS cnt FROM {table_name} {where_sql}", params)
                try:
                    r = cursor.fetchone()
                    if r:
                        species_count = int(r["cnt"] or 0)
                except Exception:
                    species_count = 0
            return {"image_count": int(image_count), "species_count": int(species_count)}
        except Exception as e:
                try:
                    LogManager.instance().warning(f"获取分类节点统计失败: {e}")
                except Exception:
                    pass
                return {"image_count": 0, "species_count": 0}
        finally:
            conn.close()

    def get_unclassified_folder_groups(self, root_path=None, table_name: str = "bird_results", limit: int = 600, sample_limit: int = 20000):
        if table_name not in ["bird_results", "import_cache"]:
            table_name = "bird_results"
        root_norm = ""
        root_slash = ""
        root_back = ""
        try:
            if root_path:
                root_norm = os.path.normcase(os.path.normpath(str(root_path)))
        except Exception:
            root_norm = ""
        if root_norm:
            try:
                root_slash = str(root_path).replace("\\", "/")
            except Exception:
                root_slash = str(root_path)
            try:
                root_back = str(root_path).replace("/", "\\")
            except Exception:
                root_back = str(root_path)
            if root_slash and not root_slash.endswith("/"):
                root_slash += "/"
            if root_back and not root_back.endswith("\\"):
                root_back += "\\"
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                sql = f"""
                    SELECT file_path
                    FROM {table_name}
                    WHERE (order_cls IS NULL OR order_cls = ''
                       OR family_cls IS NULL OR family_cls = ''
                       OR genus_cls IS NULL OR genus_cls = ''
                       OR species_cls IS NULL OR species_cls = '')
                """
                params = []
                if root_slash or root_back:
                    sql += " AND (file_path LIKE ? OR file_path LIKE ?)"
                    params.extend([f"{root_slash}%", f"{root_back}%"])
                sql += f" LIMIT {int(sample_limit) if isinstance(sample_limit, int) and sample_limit > 0 else 50000}"
                cursor.execute(sql, params)
                rows = cursor.fetchall() or []
                groups = {}
                for r in rows:
                    try:
                        fp = str(r["file_path"] or "")
                    except Exception:
                        fp = ""
                    if not fp:
                        continue
                    try:
                        folder = os.path.normpath(os.path.dirname(fp))
                    except Exception:
                        folder = os.path.dirname(fp)
                    if not folder:
                        continue
                    rel = folder
                    if root_norm:
                        try:
                            n_folder = os.path.normcase(os.path.normpath(folder))
                            if n_folder.startswith(root_norm + os.sep):
                                rel = os.path.relpath(folder, root_norm)
                        except Exception:
                            rel = folder
                    try:
                        groups[folder] = groups.get(folder, {"folder": folder, "rel": rel, "count": 0})
                        groups[folder]["count"] += 1
                    except Exception:
                        pass
                out = list(groups.values())
                try:
                    out.sort(key=lambda x: (-(int(x.get("count") or 0)), str(x.get("rel") or "")))
                except Exception:
                    pass
                if isinstance(limit, int) and limit > 0:
                    out = out[: int(limit)]
                return out
            except Exception as e:
                try:
                    LogManager.instance().warning(f"获取未分类目录分组失败: {e}")
                except Exception:
                    pass
                return []
            finally:
                conn.close()

    def query_unclassified_images_in_folder(self, folder_path: str, table_name: str = "bird_results", root_path: str | None = None):
        if table_name not in ["bird_results", "import_cache"]:
            table_name = "bird_results"
        folder = ""
        try:
            folder = os.path.normpath(str(folder_path or ""))
        except Exception:
            folder = str(folder_path or "")
        if not folder:
            return []
        try:
            rp = str(root_path or "").strip()
        except Exception:
            rp = ""
        if rp:
            try:
                folder_norm = os.path.normcase(os.path.normpath(folder))
                root_norm = os.path.normcase(os.path.normpath(rp))
                if not (folder_norm == root_norm or folder_norm.startswith(root_norm + os.sep)):
                    return []
            except Exception:
                pass
        path_slash = folder.replace('\\', '/')
        path_back = folder.replace('/', '\\')
        if not path_slash.endswith('/'):
            path_slash += '/'
        if not path_back.endswith('\\'):
            path_back += '\\'
        # 移除只读锁，利用 SQLite WAL 并发读特性，避免阻塞 UI
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            try:
                if rp:
                    root_slash = rp.replace("\\", "/")
                    root_back = rp.replace("/", "\\")
                    if root_slash and not root_slash.endswith("/"):
                        root_slash += "/"
                    if root_back and not root_back.endswith("\\"):
                        root_back += "\\"
            except Exception:
                root_slash = ""
                root_back = ""
            cursor.execute(
                f"""
                    SELECT
                        file_path, file_name, shot_time, created_at, position, score, norm_score,
                        bbox, focus_point, focus_detect_json,
                        label, order_cls, family_cls, genus_cls, species_cls, is_favorite, rating, uuid,
                        fnumber, shutter, iso, focal_length, camera_model, lens_model, tags, location
                    FROM {table_name}
                    WHERE (file_path LIKE ? OR file_path LIKE ?)
                      {"AND (file_path LIKE ? OR file_path LIKE ?)" if rp else ""}
                      AND (order_cls IS NULL OR order_cls = '' OR family_cls IS NULL OR family_cls = '' OR genus_cls IS NULL OR genus_cls = '' OR species_cls IS NULL OR species_cls = '')
                    ORDER BY created_at DESC
                    """,
                    tuple([f"{path_slash}%", f"{path_back}%"] + ([f"{root_slash}%", f"{root_back}%"] if rp else [])),
                )
            return cursor.fetchall() or []
        except Exception as e:
            try:
                LogManager.instance().warning(f"按未分类目录查询图片失败: {e}")
            except Exception:
                pass
            return []
        finally:
            conn.close()

    def get_folder_stats(self, folder_path=None):
        """
        获取文件夹统计信息（递归）
        :param folder_path: 文件夹路径，如果为 None 则统计所有
        :return: dict {'species_count': int, 'image_count': int}
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 构建查询条件
                where_clause = ""
                params = []
                
                if folder_path:
                    # 处理路径分隔符问题
                    # 数据库中可能存储为 / (如 E:/Photos/...) 或 \ (如 E:\Photos\...)
                    # 为了兼容，我们同时查询两种格式
                    
                    # 1. Forward Slash (/)
                    path_slash = folder_path.replace('\\', '/')
                    if not path_slash.endswith('/'):
                        path_slash += '/'
                        
                    # 2. Backslash (\)
                    path_back = folder_path.replace('/', '\\')
                    if not path_back.endswith('\\'):
                        path_back += '\\'
                    
                    # 构造 WHERE 子句
                    # 匹配子文件 (LIKE path%)
                    # 注意：这里我们主要关心子文件，所以使用 LIKE
                    where_clause = "WHERE (file_path LIKE ? OR file_path LIKE ?)"
                    params = [f"{path_slash}%", f"{path_back}%"]
                
                # 统计图片总数
                count_sql = f"SELECT COUNT(*) FROM bird_results {where_clause}"
                cursor.execute(count_sql, params)
                image_count = cursor.fetchone()[0]
                
                # 统计物种数 (species_cls 不为空且不重复)
                species_sql = f"SELECT COUNT(DISTINCT species_cls) FROM bird_results {where_clause} AND species_cls IS NOT NULL AND species_cls != ''"
                # 如果 where_clause 为空，则需要去掉 AND (注意：这里 params 为空列表，可以直接复用)
                if not where_clause:
                    species_sql = "SELECT COUNT(DISTINCT species_cls) FROM bird_results WHERE species_cls IS NOT NULL AND species_cls != ''"
                
                cursor.execute(species_sql, params)
                species_count = cursor.fetchone()[0]
                
                return {
                    'species_count': species_count,
                    'image_count': image_count
                }
                
            except Exception as e:
                try:
                    LogManager.instance().warning(f"获取文件夹统计失败: {e}")
                except Exception:
                    pass
                return {'species_count': 0, 'image_count': 0}
            finally:
                conn.close()

    def save_results_batch(self, data_list, table_name='bird_results'):
        """
        批量保存或更新检测结果
        :param data_list: list of dict 包含检测结果的字典列表
        :param table_name: 目标表名 ('bird_results' 或 'import_cache')
        """
        if table_name not in ['bird_results', 'import_cache']:
            try:
                LogManager.instance().warning(f"无效表名: {table_name}")
            except Exception:
                pass
            return
        
        if not data_list:
            return

        try:
            LogManager.instance().info(f"[DB] Batch saving {len(data_list)} items to {table_name}")
        except Exception:
            pass

        uuid_updates = {}
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                sql_upsert_by_path = f"""
                    INSERT INTO {table_name}
                    (uuid, fast_id, file_path, file_name, label, score, norm_score, bbox, position, pixel_count, area_ratio,
                    focus_point, object, order_cls, family_cls, genus_cls, species_cls, eye_coordinates, description, focus_detect_json, is_favorite,
                    rating, shot_time, fnumber, shutter, iso, focal_length, camera_model, lens_model, focus_distance,
                    latitude, longitude, location, tags, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        fast_id=excluded.fast_id,
                        file_name=excluded.file_name,
                        label=excluded.label,
                        score=excluded.score,
                        norm_score=excluded.norm_score,
                        bbox=excluded.bbox,
                        position=excluded.position,
                        pixel_count=excluded.pixel_count,
                        area_ratio=excluded.area_ratio,
                        focus_point=excluded.focus_point,
                        object=excluded.object,
                        order_cls=excluded.order_cls,
                        family_cls=excluded.family_cls,
                        genus_cls=excluded.genus_cls,
                        species_cls=excluded.species_cls,
                        eye_coordinates=excluded.eye_coordinates,
                        description=excluded.description,
                        focus_detect_json=excluded.focus_detect_json,
                        is_favorite=excluded.is_favorite,
                        rating=excluded.rating,
                        shot_time=excluded.shot_time,
                        fnumber=excluded.fnumber,
                        shutter=excluded.shutter,
                        iso=excluded.iso,
                        focal_length=excluded.focal_length,
                        camera_model=excluded.camera_model,
                        lens_model=excluded.lens_model,
                        focus_distance=excluded.focus_distance,
                        latitude=excluded.latitude,
                        longitude=excluded.longitude,
                        location=excluded.location,
                        tags=excluded.tags,
                        imported_at=CASE WHEN excluded.imported_at IS NULL OR excluded.imported_at='' THEN {table_name}.imported_at ELSE excluded.imported_at END
                """

                sql_upsert_by_uuid = f"""
                    INSERT INTO {table_name}
                    (uuid, fast_id, file_path, file_name, label, score, norm_score, bbox, position, pixel_count, area_ratio,
                    focus_point, object, order_cls, family_cls, genus_cls, species_cls, eye_coordinates, description, focus_detect_json, is_favorite,
                    rating, shot_time, fnumber, shutter, iso, focal_length, camera_model, lens_model, focus_distance,
                    latitude, longitude, location, tags, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uuid) DO UPDATE SET
                        fast_id=excluded.fast_id,
                        file_path=excluded.file_path,
                        file_name=excluded.file_name,
                        label=excluded.label,
                        score=excluded.score,
                        norm_score=excluded.norm_score,
                        bbox=excluded.bbox,
                        position=excluded.position,
                        pixel_count=excluded.pixel_count,
                        area_ratio=excluded.area_ratio,
                        focus_point=excluded.focus_point,
                        object=excluded.object,
                        order_cls=excluded.order_cls,
                        family_cls=excluded.family_cls,
                        genus_cls=excluded.genus_cls,
                        species_cls=excluded.species_cls,
                        eye_coordinates=excluded.eye_coordinates,
                        description=excluded.description,
                        focus_detect_json=excluded.focus_detect_json,
                        is_favorite=excluded.is_favorite,
                        rating=excluded.rating,
                        shot_time=excluded.shot_time,
                        fnumber=excluded.fnumber,
                        shutter=excluded.shutter,
                        iso=excluded.iso,
                        focal_length=excluded.focal_length,
                        camera_model=excluded.camera_model,
                        lens_model=excluded.lens_model,
                        focus_distance=excluded.focus_distance,
                        latitude=excluded.latitude,
                        longitude=excluded.longitude,
                        location=excluded.location,
                        tags=excluded.tags,
                        imported_at=CASE WHEN excluded.imported_at IS NULL OR excluded.imported_at='' THEN {table_name}.imported_at ELSE excluded.imported_at END
                """

                existing_imported_at_map = {}
                try:
                    paths = []
                    for d in (data_list or []):
                        fp = self._normalize_file_path_for_db((d or {}).get("path"))
                        if fp:
                            paths.append(fp)
                    paths = list(dict.fromkeys(paths))
                    if paths:
                        chunk = 300
                        for i in range(0, len(paths), chunk):
                            sub = paths[i : i + chunk]
                            if not sub:
                                continue
                            q = ",".join(["?"] * len(sub))
                            try:
                                cursor.execute(f"SELECT file_path, imported_at FROM {table_name} WHERE file_path IN ({q})", tuple(sub))
                                rows = cursor.fetchall() or []
                            except Exception:
                                rows = []
                                if os.name == "nt":
                                    try:
                                        cursor.execute(
                                            f"SELECT file_path, imported_at FROM {table_name} WHERE file_path COLLATE NOCASE IN ({q})",
                                            tuple(sub),
                                        )
                                        rows = cursor.fetchall() or []
                                    except Exception:
                                        rows = []
                            for r in rows:
                                try:
                                    k = self._norm_path_key(r["file_path"])
                                    existing_imported_at_map[k] = str(r["imported_at"] or "")
                                except Exception:
                                    continue
                except Exception:
                    existing_imported_at_map = {}

                params_by_norm = {}
                for data in data_list:
                    file_path = self._normalize_file_path_for_db(data.get('path'))
                    if not file_path:
                        continue

                    raw_bbox = None
                    try:
                        raw_bbox = data.get("bbox") if isinstance(data, dict) else None
                    except Exception:
                        raw_bbox = None
                    bbox_json = None
                    try:
                        bbox_json = self._normalize_bbox_json_str(raw_bbox) if raw_bbox not in (None, "", "None") else None
                    except Exception:
                        bbox_json = None

                    raw_fp = None
                    try:
                        raw_fp = data.get("focus_point") if isinstance(data, dict) else None
                    except Exception:
                        raw_fp = None
                    focus_point_value = None
                    try:
                        focus_point_value = self._normalize_focus_point_json_str(raw_fp) if raw_fp not in (None, "", "None") else None
                    except Exception:
                        focus_point_value = None

                    eye_coordinates_value = data.get('eye_coordinates')
                    if isinstance(eye_coordinates_value, (dict, list, tuple)):
                        try:
                            eye_coordinates_value = json.dumps(eye_coordinates_value, ensure_ascii=False)
                        except Exception:
                            eye_coordinates_value = str(eye_coordinates_value)

                    new_uuid = data.get('uuid') or get_unique_id()

                    imported_at_value = None
                    try:
                        if isinstance(data, dict) and "imported_at" in data:
                            imported_at_value = data.get("imported_at")
                    except Exception:
                        imported_at_value = None
                    if not imported_at_value:
                        try:
                            imported_at_value = existing_imported_at_map.get(self._norm_path_key(file_path)) or ""
                        except Exception:
                            imported_at_value = ""

                    params = (
                        new_uuid,
                        data.get('fast_id'),
                        file_path,
                        data.get('file') or os.path.basename(file_path),
                        data.get('label'),
                        data.get('score'),
                        data.get('norm_score'),
                        bbox_json,
                        data.get('position', 0),
                        data.get('pixel_count', 0),
                        data.get('area_ratio', 0.0),
                        focus_point_value,
                        data.get('object'),
                        data.get('order_cls'),
                        data.get('family_cls'),
                        data.get('genus_cls'),
                        data.get('species_cls'),
                        eye_coordinates_value,
                        data.get('description'),
                        data.get('focus_detect_json', ''),
                        data.get('is_favorite', 0),
                        data.get('rating', 0),
                        data.get('shot_time'),
                        data.get('fnumber', 0.0),
                        data.get('shutter', ''),
                        data.get('iso', 0),
                        data.get('focal_length', ''),
                        data.get('camera_model', ''),
                        data.get('lens_model', ''),
                        data.get('focus_distance', ''),
                        data.get('latitude', 0.0),
                        data.get('longitude', 0.0),
                        data.get('location', ''),
                        data.get('tags', ''),
                        imported_at_value
                    )
                    params_by_norm[self._norm_path_key(file_path)] = params

                params_list = list(params_by_norm.values())
                if not params_list:
                    return {}

                try:
                    conn.execute("BEGIN")
                except Exception:
                    pass

                bulk_ok = False
                try:
                    cursor.executemany(sql_upsert_by_path, params_list)
                    bulk_ok = True
                except sqlite3.IntegrityError:
                    bulk_ok = False
                except Exception:
                    bulk_ok = False

                if bulk_ok:
                    try:
                        conn.commit()
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                    return uuid_updates

                for params in params_list:
                    try:
                        cursor.execute(sql_upsert_by_path, params)
                    except sqlite3.IntegrityError as e:
                        msg = str(e).upper()
                        is_uuid_conflict = ("UUID" in msg) or ("PRIMARY KEY" in msg)
                        if not is_uuid_conflict:
                            try:
                                LogManager.instance().warning(f"[DB] 单条写入失败: {e}")
                            except Exception:
                                pass
                            continue

                        cur_uuid = params[0]
                        cur_fastid = params[1]
                        cur_path = params[2]

                        try:
                            cursor.execute(f"SELECT fast_id, file_path FROM {table_name} WHERE uuid = ? LIMIT 1", (cur_uuid,))
                            row = cursor.fetchone()
                        except Exception:
                            row = None

                        try:
                            existing_fastid = (row["fast_id"] if row else None)
                            existing_path = (row["file_path"] if row else None)
                        except Exception:
                            existing_fastid = None
                            existing_path = None

                        is_same_file_move = False
                        try:
                            if cur_fastid and existing_fastid and str(cur_fastid) == str(existing_fastid):
                                if existing_path and self._norm_path_key(existing_path) != self._norm_path_key(cur_path):
                                    is_same_file_move = True
                        except Exception:
                            is_same_file_move = False

                        if is_same_file_move:
                            try:
                                cursor.execute(sql_upsert_by_uuid, params)
                                continue
                            except sqlite3.IntegrityError:
                                pass
                            except Exception:
                                pass

                        fixed = False
                        for _ in range(6):
                            try:
                                new_uuid = get_unique_id()
                                new_params = (new_uuid,) + params[1:]
                                cursor.execute(sql_upsert_by_path, new_params)
                                uuid_updates[str(cur_path)] = str(new_uuid)
                                fixed = True
                                break
                            except sqlite3.IntegrityError as e2:
                                msg2 = str(e2).upper()
                                if ("UUID" in msg2) or ("PRIMARY KEY" in msg2):
                                    continue
                                try:
                                    LogManager.instance().warning(f"[DB] UUID 修复重试失败: {e2}")
                                except Exception:
                                    pass
                                break
                            except Exception as e2:
                                try:
                                    LogManager.instance().warning(f"[DB] UUID 修复异常: {e2}")
                                except Exception:
                                    pass
                                break
                        if not fixed:
                            try:
                                LogManager.instance().warning(f"[DB] UUID 冲突未修复: path={cur_path}")
                            except Exception:
                                pass
                        continue
                    except Exception as e:
                        try:
                            LogManager.instance().warning(f"[DB] 单条写入异常: {e}")
                        except Exception:
                            pass
                        continue

                try:
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            except Exception as e:
                try:
                    LogManager.instance().warning(f"数据库批量写入异常: {e}")
                except Exception:
                    pass
            finally:
                conn.close()
        return uuid_updates

    def save_results(self, data, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return
        if not isinstance(data, dict):
            return
        res = self.save_results_batch([data], table_name=table_name)
        return res

    def get_results(self, label=None, min_score=0, limit=None, offset=0, table_name='bird_results'):
        """
        读取数据：支持过滤和排序
        :param label: 过滤色标 (如 'Green')
        :param min_score: 最低分过滤
        :param limit: 限制返回数量
        :param offset: 分页偏移
        :param table_name: 目标表名 ('bird_results' 或 'import_cache')
        """
        if table_name not in ['bird_results', 'import_cache']:
            try:
                LogManager.instance().warning(f"无效表名: {table_name}")
            except Exception:
                pass
            return []

        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = f"SELECT * FROM {table_name} WHERE score >= ?"
        params = [min_score]
        
        if label:
            if label == "None":
                query += " AND (label IS NULL OR label = '')"
            else:
                query += " AND label = ?"
                params.append(label)
            
        query += " ORDER BY score DESC"
        
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # 将结果转换为字典列表，并将 JSON 字符串还原
        results = []
        for row in rows:
            item = dict(row) # sqlite3.Row 可以直接转 dict
            if item.get('bbox'):
                try:
                    item['bbox'] = json.loads(item['bbox']) # 还原为 list
                except:
                    item['bbox'] = None
            results.append(item)
            
        conn.close()
        return results



    def _update_batch_generic(self, file_items, field_name, field_value):
        """
        通用批量更新字段 (支持新建记录)
        :param file_items: List of file paths (str) OR List of dicts
        :param field_name: 'rating', 'is_favorite', 'label', 'tags'
        :param field_value: Value to update
        """
        if not file_items or field_name not in ['rating', 'is_favorite', 'label', 'tags']:
            return

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 1. 预处理（此处仅做必要的路径规范化与 fast_id 计算）
                target_items = []
                for item in file_items:
                    p = item if isinstance(item, str) else item.get('path')
                    if not p:
                        continue
                    p_db = self._normalize_file_path_for_db(p)
                    if not p_db:
                        continue
                    try:
                        from utils.file.file_util import get_fast_id
                        fast_id = get_fast_id(p_db)
                    except Exception:
                        fast_id = None

                    target_items.append({
                        'path': p,
                        'path_db': p_db,
                        'fast_id': fast_id,
                        'item': item,
                    })
                
                if not target_items:
                    return

                # 2. 读取 Exif 的 uuid/fast_id（批量读取，避免逐文件启动进程）
                worker = None
                uuid_tag = None
                fastid_tag = None
                run_exiftool_func = None
                get_exiftool_path_func = None
                try:
                    from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG, run_exiftool, get_exiftool_path
                    worker = ExifHandleWorker.get_instance()
                    uuid_tag = EXIF_TAG.Uuid.value
                    fastid_tag = EXIF_TAG.Fastid.value
                    run_exiftool_func = run_exiftool
                    get_exiftool_path_func = get_exiftool_path
                except Exception:
                    worker = None
                    uuid_tag = None
                    fastid_tag = None

                path_exif_map = {}
                if run_exiftool_func and get_exiftool_path_func and (uuid_tag or fastid_tag):
                    all_paths = [t.get('path_db') for t in target_items if t.get('path_db')]
                    if all_paths:
                        try:
                            chunk_size = 50
                            for i in range(0, len(all_paths), chunk_size):
                                chunk_paths = all_paths[i:i + chunk_size]
                                cmd = [get_exiftool_path_func(), "-j", "-charset", "utf8"]
                                if uuid_tag:
                                    cmd.append("-" + uuid_tag)
                                if fastid_tag:
                                    cmd.append("-" + fastid_tag)
                                cmd += chunk_paths
                                res = run_exiftool_func(cmd)
                                if res.returncode != 0:
                                    continue
                                tags_list = json.loads(res.stdout or "[]")
                                if not isinstance(tags_list, list):
                                    continue
                                for entry in tags_list:
                                    source_file = entry.get("SourceFile")
                                    if not source_file:
                                        continue
                                    exif_uuid = entry.get(uuid_tag) or entry.get("Uuid") if uuid_tag else None
                                    exif_fastid = entry.get(fastid_tag) or entry.get("Fastid") if fastid_tag else None
                                    path_exif_map[os.path.normpath(source_file)] = {
                                        "uuid": exif_uuid,
                                        "fast_id": exif_fastid,
                                    }
                        except Exception as e:
                            try:
                                LogManager.instance().warning(f"[DB][BatchUpdate] 批量读取 Exif uuid/fast_id 失败: {e}")
                            except Exception:
                                pass

                # 3. 按“fast_id 优先、uuid 兜底”的策略定位记录并更新
                update_rows = []
                insert_rows = []
                exif_write_tasks = []

                for t in target_items:
                    p_db = t.get("path_db")
                    if not p_db:
                        continue

                    p_norm = os.path.normpath(p_db)
                    exif_info = path_exif_map.get(p_norm) or {}
                    exif_uuid = exif_info.get("uuid")
                    exif_fastid = exif_info.get("fast_id")
                    computed_fastid = t.get("fast_id")

                    item = t.get("item")
                    item_dict = item if isinstance(item, dict) else {}

                    db_uuid = None
                    item_uuid = None
                    try:
                        item_uuid = item_dict.get("uuid") or item_dict.get("Uuid")
                    except Exception:
                        item_uuid = None
                    if item_uuid:
                        try:
                            cursor.execute("SELECT 1 FROM bird_results WHERE uuid = ? LIMIT 1", (item_uuid,))
                            if cursor.fetchone():
                                db_uuid = item_uuid
                        except Exception:
                            db_uuid = None

                    if computed_fastid:
                        try:
                            cursor.execute("SELECT uuid FROM bird_results WHERE fast_id = ? LIMIT 2", (computed_fastid,))
                            rows = cursor.fetchall() or []
                            if len(rows) == 1:
                                db_uuid = rows[0]["uuid"]
                            elif len(rows) == 0:
                                try:
                                    LogManager.instance().warning(f"[DB][BatchUpdate] fast_id 未命中: fast_id={computed_fastid}, file={p_db}")
                                except Exception:
                                    pass
                            else:
                                try:
                                    LogManager.instance().warning(f"[DB][BatchUpdate] fast_id 命中多条记录: fast_id={computed_fastid}, file={p_db}")
                                except Exception:
                                    pass
                        except Exception as e:
                            try:
                                LogManager.instance().warning(f"[DB][BatchUpdate] fast_id 查询失败: fast_id={computed_fastid}, file={p_db}, err={e}")
                            except Exception:
                                pass
                            db_uuid = None

                    if not db_uuid:
                        try:
                            cursor.execute("SELECT uuid FROM bird_results WHERE file_path = ? LIMIT 1", (p_db,))
                            r = cursor.fetchone()
                            if r:
                                db_uuid = r["uuid"]
                        except Exception:
                            db_uuid = None

                    if not db_uuid and exif_uuid:
                        try:
                            cursor.execute("SELECT 1 FROM bird_results WHERE uuid = ? LIMIT 1", (exif_uuid,))
                            if cursor.fetchone():
                                db_uuid = exif_uuid
                        except Exception:
                            db_uuid = None

                    if not db_uuid:
                        db_uuid = exif_uuid or get_unique_id()

                    if worker and uuid_tag:
                        if not exif_uuid or exif_uuid != db_uuid:
                            exif_write_tasks.append((p_db, {uuid_tag: db_uuid}))

                    if worker and fastid_tag and computed_fastid:
                        if not exif_fastid or str(exif_fastid) != str(computed_fastid):
                            exif_write_tasks.append((p_db, {fastid_tag: computed_fastid}))

                    if computed_fastid:
                        update_rows.append((field_value, computed_fastid, p_db, os.path.basename(p_db), db_uuid))
                    else:
                        update_rows.append((field_value, None, p_db, os.path.basename(p_db), db_uuid))

                    try:
                        cursor.execute("SELECT 1 FROM bird_results WHERE uuid = ? LIMIT 1", (db_uuid,))
                        exists = cursor.fetchone() is not None
                    except Exception:
                        exists = False

                    if not exists:
                        insert_rows.append((
                            db_uuid,
                            computed_fastid,
                            p_db,
                            os.path.basename(p_db),
                            field_value,
                            item_dict.get('order'),
                            item_dict.get('family'),
                            item_dict.get('genus'),
                            item_dict.get('species'),
                        ))

                if insert_rows:
                    sql_insert = f"""
                        INSERT INTO bird_results(
                            uuid, fast_id, file_path, file_name, {field_name}, created_at,
                            order_cls, family_cls, genus_cls, species_cls
                        )
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
                        ON CONFLICT(uuid) DO UPDATE SET
                            fast_id=COALESCE(excluded.fast_id, bird_results.fast_id),
                            file_path=COALESCE(excluded.file_path, bird_results.file_path),
                            file_name=COALESCE(excluded.file_name, bird_results.file_name),
                            {field_name}=excluded.{field_name},
                            order_cls=COALESCE(excluded.order_cls, bird_results.order_cls),
                            family_cls=COALESCE(excluded.family_cls, bird_results.family_cls),
                            genus_cls=COALESCE(excluded.genus_cls, bird_results.genus_cls),
                            species_cls=COALESCE(excluded.species_cls, bird_results.species_cls)
                    """
                    cursor.executemany(sql_insert, insert_rows)

                if update_rows:
                    sql_update = f"""
                        UPDATE bird_results SET
                            {field_name} = ?,
                            fast_id = COALESCE(?, fast_id),
                            file_path = COALESCE(?, file_path),
                            file_name = COALESCE(?, file_name)
                        WHERE uuid = ?
                    """
                    cursor.executemany(sql_update, update_rows)
                    try:
                        LogManager.instance().debug(f"[DB][BatchUpdate] 更新完成 字段={field_name} 更新数={len(update_rows)}")
                    except Exception:
                        pass

                if worker and exif_write_tasks:
                    try:
                        for p, tags in exif_write_tasks:
                            try:
                                worker.write_tags(p, tags)
                            except Exception:
                                pass
                    except Exception:
                        pass
                
                conn.commit()
            except Exception as e:
                try:
                    LogManager.instance().warning(f"Batch update {field_name} failed: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def update_rating_batch(self, file_items, rating):
        """
        批量更新评分 (支持新建记录)
        file_items: List of file paths (str) OR List of dicts
        """
        self._update_batch_generic(file_items, 'rating', rating)

    def update_favorite_batch(self, file_items, is_favorite):
        """
        批量更新收藏状态 (支持新建记录)
        file_items: List of file paths (str) OR List of dicts
        """
        self._update_batch_generic(file_items, 'is_favorite', is_favorite)

    def update_label_batch(self, file_items, label):
        """
        批量更新色标 (支持新建记录)
        file_items: List of file paths (str) OR List of dicts
        """
        self._update_batch_generic(file_items, 'label', label)

    def update_tags_batch(self, file_items, tags):
        """
        批量更新标签 (支持新建记录)
        file_items: List of file paths (str) OR List of dicts
        tags: 标签字符串 (如 'tag1|tag2')
        """
        self._update_batch_generic(file_items, 'tags', tags)

    def update_user_field_batch_for_table(self, file_items, field_name, field_value, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return
        if field_name not in ['rating', 'is_favorite', 'label', 'tags', 'description']:
            return
        if not file_items:
            return
        try:
            LogManager.instance().info(f"[DB] Batch updating {field_name} to {field_value} for {len(file_items)} items in {table_name}")
        except Exception:
            pass
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                paths = []
                for item in (file_items or []):
                    p = item if isinstance(item, str) else item.get('path')
                    if not p:
                        continue
                    p_db = self._normalize_file_path_for_db(p)
                    if not p_db:
                        continue
                    paths.append((str(p), str(p_db)))
                if not paths:
                    return

                for p_raw, p_db in paths:
                    try:
                        cursor.execute(f"UPDATE {table_name} SET {field_name} = ? WHERE file_path = ?", (field_value, p_db))
                        if cursor.rowcount == 0:
                            cursor.execute(f"UPDATE {table_name} SET {field_name} = ? WHERE file_path = ? COLLATE NOCASE", (field_value, p_db))
                    except Exception:
                        pass
                    if cursor.rowcount == 0:
                        try:
                            uuid = get_unique_id()
                            name = os.path.basename(p_db) or os.path.basename(p_raw)
                            cursor.execute(
                                f"INSERT INTO {table_name} (uuid, file_path, file_name, {field_name}, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                                (uuid, p_db, name, field_value),
                            )
                        except Exception:
                            pass

                try:
                    self._dedupe_specific_normalized_paths(cursor, table_name, [self._norm_path_key(p_db) for _p_raw, p_db in paths if p_db])
                except Exception:
                    pass
                conn.commit()
            except Exception as e:
                try:
                    LogManager.instance().warning(f"Batch update {table_name}.{field_name} failed: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def update_tags_batch_for_table(self, file_items, tags, table_name='bird_results'):
        self.update_user_field_batch_for_table(file_items, 'tags', tags, table_name=table_name)

    def update_description(self, file_path, description, table_name='bird_results'):
        self.update_user_field_batch_for_table([file_path], 'description', description, table_name=table_name)

    def update_geolocation(self, file_path, latitude, longitude, location, region_code='', table_name='bird_results'):
        """
        更新地理位置信息
        :param file_path: 图片路径
        :param latitude: 纬度 (float)
        :param longitude: 经度 (float)
        :param location: 地点名称 (str)
        :param region_code: 区域代码 (str)，如 "CN", "CN-44", "US-CA"
        :param table_name: 表名
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 检查是否存在
                record = self.get_result_by_path(file_path, table_name=table_name)
                
                if record:
                    # 更新
                    cursor.execute(f"UPDATE {table_name} SET latitude = ?, longitude = ?, location = ?, region_code = ? WHERE file_path = ?", 
                                   (latitude, longitude, location, region_code, record.get('file_path')))
                else:
                    # 插入新记录 (最简模式)
                    uuid = get_unique_id()
                    file_path_db = self._normalize_file_path_for_db(file_path)
                    if not file_path_db:
                        return
                    name = os.path.basename(file_path_db)
                    cursor.execute(f'''
                        INSERT INTO {table_name} (uuid, file_path, file_name, latitude, longitude, location, region_code, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (uuid, file_path_db, name, latitude, longitude, location, region_code))
                
                self._dedupe_specific_normalized_paths(cursor, table_name, [self._norm_path_key(file_path)])
                conn.commit()
            except Exception as e:
                try:
                    LogManager.instance().warning(f"更新地理位置失败: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def update_taxonomy_batch_for_table(self, file_items, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return
        if not file_items:
            return
        try:
            LogManager.instance().info(f"[DB] Batch updating taxonomy for {len(file_items)} items in {table_name}")
        except Exception:
            pass
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                norm_keys = []
                for it in (file_items or []):
                    if not isinstance(it, dict):
                        continue
                    p_raw = it.get("path") or it.get("file_path")
                    if not p_raw:
                        continue
                    p_db = self._normalize_file_path_for_db(p_raw)
                    if not p_db:
                        continue
                    obj = it.get("object")
                    order_cls = it.get("order_cls")
                    family_cls = it.get("family_cls")
                    genus_cls = it.get("genus_cls")
                    species_cls = it.get("species_cls")
                    try:
                        cursor.execute(
                            f"UPDATE {table_name} SET object = ?, order_cls = ?, family_cls = ?, genus_cls = ?, species_cls = ? WHERE file_path = ?",
                            (obj, order_cls, family_cls, genus_cls, species_cls, p_db),
                        )
                        if cursor.rowcount == 0:
                            cursor.execute(
                                f"UPDATE {table_name} SET object = ?, order_cls = ?, family_cls = ?, genus_cls = ?, species_cls = ? WHERE file_path = ? COLLATE NOCASE",
                                (obj, order_cls, family_cls, genus_cls, species_cls, p_db),
                            )
                    except Exception:
                        pass
                    if cursor.rowcount == 0:
                        try:
                            uuid = get_unique_id()
                            name = os.path.basename(p_db) or os.path.basename(str(p_raw))
                            cursor.execute(
                                f"INSERT INTO {table_name} (uuid, file_path, file_name, object, order_cls, family_cls, genus_cls, species_cls, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                                (uuid, p_db, name, obj, order_cls, family_cls, genus_cls, species_cls),
                            )
                        except Exception:
                            pass
                    try:
                        norm_keys.append(self._norm_path_key(p_db))
                    except Exception:
                        pass
                try:
                    if norm_keys:
                        self._dedupe_specific_normalized_paths(cursor, table_name, norm_keys)
                except Exception:
                    pass
                conn.commit()
            except Exception as e:
                try:
                    LogManager.instance().warning(f"批量更新分类信息失败 {table_name}: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def get_result_by_path(self, file_path, table_name='bird_results'):
        """根据路径获取单条结果"""
        if table_name not in ['bird_results', 'import_cache']:
            return None

        if not file_path:
            return None

        try:
            fp_raw = str(file_path)
        except Exception:
            return None
        if not fp_raw:
            return None

        row = None
        try:
            fp_db = self._normalize_file_path_for_db(fp_raw)
        except Exception:
            fp_db = fp_raw
        candidates = []
        try:
            if fp_db:
                candidates.append(str(fp_db))
        except Exception:
            pass
        try:
            candidates.append(str(fp_raw))
        except Exception:
            pass
        try:
            candidates = [c for c in list(dict.fromkeys([str(x) for x in candidates if x])) if c]
        except Exception:
            candidates = [fp_raw]

        if os.name == "nt":
            try:
                expanded = []
                for c in (candidates or []):
                    if not c:
                        continue
                    try:
                        c0 = self._normalize_file_path_for_db(c) or str(c)
                    except Exception:
                        c0 = str(c)
                    if c0:
                        expanded.append(str(c0))
                        try:
                            expanded.append(str(c0).replace("\\", "/"))
                        except Exception:
                            pass
                    try:
                        c1 = str(c).replace("/", "\\")
                        try:
                            c1 = self._normalize_file_path_for_db(c1) or c1
                        except Exception:
                            c1 = c1
                        expanded.append(str(c1))
                        expanded.append(str(c1).replace("\\", "/"))
                    except Exception:
                        pass
                candidates = list(dict.fromkeys([x for x in expanded if x]))
            except Exception:
                pass

        for attempt in range(4):
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                for cand in candidates:
                    try:
                        cursor.execute(f"SELECT * FROM {table_name} WHERE file_path = ?", (str(cand),))
                        row = cursor.fetchone()
                    except Exception:
                        row = None
                    if row:
                        break
                    if os.name == 'nt':
                        try:
                            cursor.execute(f"SELECT * FROM {table_name} WHERE file_path = ? COLLATE NOCASE", (str(cand),))
                            row = cursor.fetchone()
                        except Exception:
                            row = None
                    if row:
                        break
                break
            except Exception as e:
                msg = str(e).lower()
                try:
                    LogManager.instance().debug(f"get result by path error: {msg}")
                except Exception:
                    pass
                if "locked" in msg and attempt < 3:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                row = None
                break
            finally:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
        
        if row:
            item = dict(row)
            item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
            item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
            return item
        return None

    def clear_import_cache(self):
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM import_cache")
                conn.commit()
            finally:
                conn.close()

    def get_existing_paths(self, file_paths, table_name="import_cache"):
        if table_name not in ['bird_results', 'import_cache']:
            return set()
        try:
            paths = [str(p) for p in (file_paths or []) if p]
        except Exception:
            paths = []
        if not paths:
            return set()
        out = set()
        chunk = 400
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                for i in range(0, len(paths), chunk):
                    sub = paths[i : i + chunk]
                    if not sub:
                        continue
                    q = ",".join(["?"] * len(sub))
                    try:
                        cursor.execute(f"SELECT file_path FROM {table_name} WHERE file_path IN ({q})", tuple(sub))
                        for r in cursor.fetchall() or []:
                            try:
                                out.add(str(r["file_path"]))
                            except Exception:
                                continue
                    except Exception:
                        if os.name == 'nt':
                            try:
                                cursor.execute(f"SELECT file_path FROM {table_name} WHERE file_path COLLATE NOCASE IN ({q})", tuple(sub))
                                for r in cursor.fetchall() or []:
                                    try:
                                        out.add(str(r["file_path"]))
                                    except Exception:
                                        continue
                            except Exception:
                                pass
            finally:
                conn.close()
        return out

    def get_results_by_paths(self, file_paths, table_name="import_cache"):
        if table_name not in ['bird_results', 'import_cache']:
            return {}
        try:
            paths = [str(p) for p in (file_paths or []) if p]
        except Exception:
            paths = []
        if not paths:
            return {}
        if os.name == "nt":
            try:
                expanded = []
                for p in (paths or []):
                    if not p:
                        continue
                    try:
                        p1 = self._normalize_file_path_for_db(p)
                    except Exception:
                        p1 = str(p)
                    if p1:
                        expanded.append(str(p1))
                        try:
                            expanded.append(str(p1).replace("\\", "/"))
                        except Exception:
                            pass
                    try:
                        p2 = str(p).replace("/", "\\")
                        p2 = self._normalize_file_path_for_db(p2) or p2
                        expanded.append(str(p2))
                        expanded.append(str(p2).replace("\\", "/"))
                    except Exception:
                        pass
                paths = list(dict.fromkeys([x for x in expanded if x]))
            except Exception:
                pass
        out = {}
        chunk = 300
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                for i in range(0, len(paths), chunk):
                    sub = paths[i : i + chunk]
                    if not sub:
                        continue
                    q = ",".join(["?"] * len(sub))
                    try:
                        cursor.execute(f"SELECT * FROM {table_name} WHERE file_path IN ({q})", tuple(sub))
                        rows = cursor.fetchall() or []
                    except Exception:
                        rows = []
                        if os.name == 'nt':
                            try:
                                cursor.execute(f"SELECT * FROM {table_name} WHERE file_path COLLATE NOCASE IN ({q})", tuple(sub))
                                rows = cursor.fetchall() or []
                            except Exception:
                                rows = []
                    for row in rows:
                        try:
                            item = dict(row)
                        except Exception:
                            continue
                        item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
                        item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
                        try:
                            out[str(item.get("file_path") or "")] = item
                        except Exception:
                            continue
            finally:
                conn.close()
        return out

    def get_results_by_fast_ids(self, fast_ids, table_name="import_cache"):
        if table_name not in ['bird_results', 'import_cache']:
            return {}
        try:
            ids = [str(x) for x in (fast_ids or []) if x]
        except Exception:
            ids = []
        if not ids:
            return {}
        out = {}
        chunk = 300
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                for i in range(0, len(ids), chunk):
                    sub = ids[i : i + chunk]
                    if not sub:
                        continue
                    q = ",".join(["?"] * len(sub))
                    try:
                        cursor.execute(f"SELECT * FROM {table_name} WHERE fast_id IN ({q}) ORDER BY created_at DESC", tuple(sub))
                        rows = cursor.fetchall() or []
                    except Exception:
                        rows = []
                    for row in rows:
                        try:
                            item = dict(row)
                        except Exception:
                            continue
                        try:
                            fid = str(item.get("fast_id") or "")
                        except Exception:
                            fid = ""
                        if not fid or fid in out:
                            continue
                        item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
                        item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
                        out[fid] = item
            finally:
                conn.close()
        return out

    def get_results_by_uuids(self, uuids, table_name="import_cache"):
        if table_name not in ['bird_results', 'import_cache']:
            return {}
        try:
            ids = [str(x) for x in (uuids or []) if x]
        except Exception:
            ids = []
        if not ids:
            return {}
        out = {}
        chunk = 300
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                for i in range(0, len(ids), chunk):
                    sub = ids[i : i + chunk]
                    if not sub:
                        continue
                    q = ",".join(["?"] * len(sub))
                    try:
                        cursor.execute(f"SELECT * FROM {table_name} WHERE uuid IN ({q})", tuple(sub))
                        rows = cursor.fetchall() or []
                    except Exception:
                        rows = []
                    for row in rows:
                        try:
                            item = dict(row)
                        except Exception:
                            continue
                        try:
                            u = str(item.get("uuid") or "")
                        except Exception:
                            u = ""
                        if not u:
                            continue
                        item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
                        item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
                        out[u] = item
            finally:
                conn.close()
        return out

    def list_import_cache_by_folder(self, folder_path: str, limit: int = 50000):
        try:
            folder = str(folder_path or "")
        except Exception:
            folder = ""
        if not folder:
            return []
        try:
            folder = self._normalize_file_path_for_db(folder) or os.path.normpath(folder)
        except Exception:
            pass
        prefix = str(folder or "")
        try:
            if not prefix.endswith(os.sep):
                prefix = prefix + os.sep
        except Exception:
            pass
        pattern = str(prefix) + "%"
        alt_pattern = ""
        if os.name == "nt":
            try:
                alt_prefix = str(prefix).replace("\\", "/")
                alt_pattern = alt_prefix + "%"
            except Exception:
                alt_pattern = ""
        rows = []
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                try:
                    if os.name == "nt" and alt_pattern:
                        cursor.execute(
                            "SELECT * FROM import_cache WHERE (file_path LIKE ? OR file_path LIKE ?) ORDER BY created_at DESC LIMIT ?",
                            (pattern, alt_pattern, int(limit)),
                        )
                    else:
                        cursor.execute(
                            "SELECT * FROM import_cache WHERE file_path LIKE ? ORDER BY created_at DESC LIMIT ?",
                            (pattern, int(limit)),
                        )
                except Exception:
                    if os.name == 'nt':
                        if alt_pattern:
                            cursor.execute(
                                "SELECT * FROM import_cache WHERE (file_path LIKE ? COLLATE NOCASE OR file_path LIKE ? COLLATE NOCASE) ORDER BY created_at DESC LIMIT ?",
                                (pattern, alt_pattern, int(limit)),
                            )
                        else:
                            cursor.execute(
                                "SELECT * FROM import_cache WHERE file_path LIKE ? COLLATE NOCASE ORDER BY created_at DESC LIMIT ?",
                                (pattern, int(limit)),
                            )
                    else:
                        raise
                for r in cursor.fetchall() or []:
                    try:
                        item = dict(r)
                    except Exception:
                        continue
                    item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
                    item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
                    rows.append(item)
            finally:
                conn.close()
        return rows

    def list_import_cache_by_burst_first(self, first_file_name: str, limit: int = 50000):
        try:
            first_name = str(first_file_name or "")
        except Exception:
            first_name = ""
        if not first_name:
            return []
        pattern = f'%\"burst_first_file\"%{first_name}%'
        rows = []
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "SELECT * FROM import_cache WHERE focus_detect_json LIKE ? ORDER BY created_at DESC LIMIT ?",
                        (pattern, int(limit)),
                    )
                except Exception:
                    if os.name == 'nt':
                        cursor.execute(
                            "SELECT * FROM import_cache WHERE focus_detect_json LIKE ? COLLATE NOCASE ORDER BY created_at DESC LIMIT ?",
                            (pattern, int(limit)),
                        )
                    else:
                        raise
                for r in cursor.fetchall() or []:
                    try:
                        item = dict(r)
                    except Exception:
                        continue
                    item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
                    item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
                    rows.append(item)
            finally:
                conn.close()
        return rows

    def list_import_cache_by_burst_first_in_folder(self, folder_path: str, first_file_name: str, limit: int = 50000):
        try:
            folder = str(folder_path or "")
        except Exception:
            folder = ""
        if not folder:
            return []
        try:
            folder = self._normalize_file_path_for_db(folder) or folder
        except Exception:
            folder = folder
        try:
            folder_like = folder
            if not folder_like.endswith(os.sep):
                folder_like = folder_like + os.sep
            folder_like = folder_like + "%"
        except Exception:
            folder_like = folder + "%"
        alt_folder_like = ""
        if os.name == "nt":
            try:
                alt_folder_like = str(folder_like).replace("\\", "/")
            except Exception:
                alt_folder_like = ""

        try:
            first_name = str(first_file_name or "")
        except Exception:
            first_name = ""
        if not first_name:
            return []
        pattern = f'%\"burst_first_file\"%{first_name}%'

        rows = []
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                try:
                    if os.name == "nt" and alt_folder_like:
                        cursor.execute(
                            "SELECT * FROM import_cache WHERE (file_path LIKE ? OR file_path LIKE ?) AND focus_detect_json LIKE ? ORDER BY created_at DESC LIMIT ?",
                            (folder_like, alt_folder_like, pattern, int(limit)),
                        )
                    else:
                        cursor.execute(
                            "SELECT * FROM import_cache WHERE file_path LIKE ? AND focus_detect_json LIKE ? ORDER BY created_at DESC LIMIT ?",
                            (folder_like, pattern, int(limit)),
                        )
                except Exception:
                    if os.name == 'nt':
                        if alt_folder_like:
                            cursor.execute(
                                "SELECT * FROM import_cache WHERE (file_path LIKE ? COLLATE NOCASE OR file_path LIKE ? COLLATE NOCASE) AND focus_detect_json LIKE ? COLLATE NOCASE ORDER BY created_at DESC LIMIT ?",
                                (folder_like, alt_folder_like, pattern, int(limit)),
                            )
                        else:
                            cursor.execute(
                                "SELECT * FROM import_cache WHERE file_path LIKE ? COLLATE NOCASE AND focus_detect_json LIKE ? COLLATE NOCASE ORDER BY created_at DESC LIMIT ?",
                                (folder_like, pattern, int(limit)),
                            )
                    else:
                        raise
                for r in cursor.fetchall() or []:
                    try:
                        item = dict(r)
                    except Exception:
                        continue
                    item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
                    item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
                    rows.append(item)
            finally:
                conn.close()
        return rows

    def list_import_cache_recent_folders(self, limit_rows: int = 5000, max_folders: int = 50):
        try:
            limit_rows = int(limit_rows or 0)
        except Exception:
            limit_rows = 5000
        limit_rows = max(1, min(limit_rows, 200000))
        try:
            max_folders = int(max_folders or 0)
        except Exception:
            max_folders = 50
        max_folders = max(1, min(max_folders, 500))

        folders = []
        seen = set()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT file_path FROM import_cache ORDER BY created_at DESC LIMIT ?", (int(limit_rows),))
                for r in cursor.fetchall() or []:
                    try:
                        fp = str(r[0] or "")
                    except Exception:
                        fp = ""
                    if not fp:
                        continue
                    try:
                        fp = self._normalize_file_path_for_db(fp) or fp
                    except Exception:
                        pass
                    try:
                        d = os.path.dirname(fp)
                    except Exception:
                        d = ""
                    if not d:
                        continue
                    try:
                        key = os.path.normcase(os.path.normpath(d)) if os.name == "nt" else os.path.normpath(d)
                    except Exception:
                        key = d
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    folders.append(d)
                    if len(folders) >= max_folders:
                        break
            finally:
                conn.close()
        return folders

    def get_result_by_uuid(self, uuid, table_name='bird_results'):
        """根据 uuid 获取单条结果"""
        if table_name not in ['bird_results', 'import_cache']:
            return None
        if not uuid:
            return None

        row = None
        for attempt in range(4):
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM {table_name} WHERE uuid = ? LIMIT 1", (uuid,))
                row = cursor.fetchone()
                break
            except Exception as e:
                msg = str(e).lower()
                try:
                    LogManager.instance().debug(f"get result by uuid error: {msg}")
                except Exception:
                    pass
                if "locked" in msg and attempt < 3:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                row = None
                break
            finally:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

        if row:
            item = dict(row)
            item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
            item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
            return item
        return None

    def get_result_by_fast_id(self, fast_id, table_name='bird_results'):
        """根据 fast_id 获取单条结果（用于路径可能变化场景）"""
        if table_name not in ['bird_results', 'import_cache']:
            return None
        if not fast_id:
            return None

        row = None
        for attempt in range(4):
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM {table_name} WHERE fast_id = ? LIMIT 1", (fast_id,))
                row = cursor.fetchone()
                break
            except Exception as e:
                msg = str(e).lower()
                try:
                    LogManager.instance().debug(f"get result by fast_id error: {msg}")
                except Exception:
                    pass
                if "locked" in msg and attempt < 3:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                row = None
                break
            finally:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

        if row:
            item = dict(row)
            item['bbox'] = self._normalize_bbox_json_str(item.get('bbox'))
            item['focus_point'] = self._normalize_focus_point_json_str(item.get('focus_point'))
            return item
        return None

    def update_subject_info(self, file_path, bbox=None, focus_point=None, position=None, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return
        if not file_path:
            return

        file_path_db = self._normalize_file_path_for_db(file_path)
        if not file_path_db:
            return

        try:
            LogManager.instance().info(f"[DB] Updating subject info for {file_path} in {table_name}. bbox={bbox}, focus={focus_point}, pos={position}")
        except Exception:
            pass

        set_parts = []
        set_params = []

        bbox_json = None
        if bbox is not None:
            try:
                bbox_json = self._normalize_bbox_json_str(bbox)
            except Exception:
                bbox_json = None
            set_parts.append("bbox = ?")
            set_params.append(bbox_json)

        focus_json = None
        if focus_point is not None:
            try:
                focus_json = self._normalize_focus_point_json_str(focus_point)
            except Exception:
                focus_json = None
            set_parts.append("focus_point = ?")
            set_params.append(focus_json)

        if position is not None:
            set_parts.append("position = ?")
            set_params.append(position)

        if not set_parts:
            return

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                record = self.get_result_by_path(file_path_db, table_name=table_name)
                if record and record.get('file_path'):
                    sql = f"UPDATE {table_name} SET {', '.join(set_parts)} WHERE file_path = ?"
                    cursor.execute(sql, tuple(set_params + [record.get('file_path')]))
                else:
                    uuid = get_unique_id()
                    name = os.path.basename(file_path_db)
                    cursor.execute(
                        f"INSERT INTO {table_name} (uuid, file_path, file_name, bbox, focus_point, position, created_at) "
                        f"VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                        (uuid, file_path_db, name, bbox_json, focus_json, position)
                    )

                self._dedupe_specific_normalized_paths(cursor, table_name, [self._norm_path_key(file_path_db)])
                conn.commit()
            except Exception as e:
                try:
                    LogManager.instance().warning(f"更新主体信息失败: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def update_subject_info_by_uuid(self, uuid, file_path=None, bbox=None, focus_point=None, position=None, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return
        if not uuid:
            return

        try:
            LogManager.instance().info(f"[DB] Updating subject info for uuid {uuid} in {table_name}. bbox={bbox}, focus={focus_point}, pos={position}")
        except Exception:
            pass

        set_parts = []
        set_params = []

        bbox_json = None
        if bbox is not None:
            try:
                bbox_json = self._normalize_bbox_json_str(bbox)
            except Exception:
                bbox_json = None
            set_parts.append("bbox = ?")
            set_params.append(bbox_json)

        focus_json = None
        if focus_point is not None:
            try:
                focus_json = self._normalize_focus_point_json_str(focus_point)
            except Exception:
                focus_json = None
            set_parts.append("focus_point = ?")
            set_params.append(focus_json)

        if position is not None:
            set_parts.append("position = ?")
            set_params.append(position)

        if not set_parts:
            return

        file_path_db = None
        if file_path:
            file_path_db = self._normalize_file_path_for_db(file_path)

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(f"SELECT file_path FROM {table_name} WHERE uuid = ? LIMIT 1", (uuid,))
                row = cursor.fetchone()
                if row:
                    sql = f"UPDATE {table_name} SET {', '.join(set_parts)} WHERE uuid = ?"
                    cursor.execute(sql, tuple(set_params + [uuid]))
                else:
                    if not file_path_db:
                        return
                    name = os.path.basename(file_path_db)
                    cursor.execute(
                        f"INSERT INTO {table_name} (uuid, file_path, file_name, bbox, focus_point, position, created_at) "
                        f"VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                        (uuid, file_path_db, name, bbox_json, focus_json, position)
                    )

                conn.commit()
            except Exception as e:
                try:
                    LogManager.instance().warning(f"按 UUID 更新主体信息失败: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def update_file_path_by_uuid(self, uuid, file_path, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return
        try:
            uuid = str(uuid or "")
        except Exception:
            uuid = ""
        if not uuid:
            return
        try:
            file_path_db = self._normalize_file_path_for_db(file_path)
        except Exception:
            file_path_db = str(file_path or "")
        if not file_path_db:
            return
        try:
            file_name = os.path.basename(file_path_db)
        except Exception:
            file_name = ""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    f"UPDATE {table_name} SET file_path = ?, file_name = ? WHERE uuid = ?",
                    (file_path_db, file_name, uuid),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_result(self, file_path, table_name='bird_results'):
        """删除指定路径的记录"""
        if table_name not in ['bird_results', 'import_cache']:
            return

        try:
            LogManager.instance().info(f"[DB] Deleting result for {file_path} from {table_name}")
        except Exception:
            pass

        with self._lock:
            conn = self._get_connection()
            try:
                record = self.get_result_by_path(file_path, table_name=table_name)
                if record and record.get('file_path'):
                    conn.execute(f"DELETE FROM {table_name} WHERE file_path = ?", (record.get('file_path'),))
                else:
                    conn.execute(f"DELETE FROM {table_name} WHERE file_path = ?", (file_path,))
                conn.commit()
            finally:
                conn.close()

    def delete_result_by_uuid(self, uuid: str, table_name: str = "bird_results"):
        if table_name not in ["bird_results", "import_cache"]:
            return
        try:
            uuid = str(uuid or "")
        except Exception:
            uuid = ""
        if not uuid:
            return
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(f"DELETE FROM {table_name} WHERE uuid = ?", (uuid,))
                conn.commit()
            finally:
                conn.close()

    def delete_results_by_uuids(self, uuids: list[str], table_name: str = "bird_results"):
        if table_name not in ["bird_results", "import_cache"]:
            return
        try:
            ids = [str(u) for u in (uuids or []) if u]
        except Exception:
            ids = []
        if not ids:
            return
        uniq = list(dict.fromkeys(ids))
        with self._lock:
            conn = self._get_connection()
            try:
                for i in range(0, len(uniq), 200):
                    batch = uniq[i:i + 200]
                    placeholders = ",".join(["?"] * len(batch))
                    conn.execute(f"DELETE FROM {table_name} WHERE uuid IN ({placeholders})", batch)
                conn.commit()
            finally:
                conn.close()

    def cleanup_missing_files(self, scanned_file_paths, root_path=None, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return 0

        try:
            LogManager.instance().info(f"[DB] Cleaning up missing files from {table_name}")
        except Exception:
            pass

        scanned_keys = set()
        for p in (scanned_file_paths or []):
            k = self._norm_path_key(p)
            if k:
                scanned_keys.add(k)

        root_db = None
        if root_path:
            root_db = self._normalize_file_path_for_db(root_path)
            try:
                root_db = os.path.normpath(root_db)
            except Exception:
                pass

        to_delete_keys = []
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                params = []
                sql = f"SELECT file_path FROM {table_name}"
                if root_db:
                    if os.name == 'nt':
                        sql += " WHERE lower(replace(file_path, '/', '\\\\')) LIKE ?"
                        params.append(self._norm_path_key(os.path.join(root_db, "")) + "%")
                    else:
                        sql += " WHERE lower(file_path) LIKE ?"
                        params.append((os.path.join(root_db, "")).lower() + "%")

                cursor.execute(sql, params)
                rows = cursor.fetchall()
                for r in rows:
                    fp = r['file_path']
                    try:
                        exists = os.path.exists(fp)
                    except Exception:
                        exists = False
                    if exists:
                        continue
                    k = self._norm_path_key(fp)
                    if not k:
                        continue
                    if scanned_keys and (k in scanned_keys):
                        continue
                    to_delete_keys.append(k)

                if not to_delete_keys:
                    return 0

                uniq_keys = list(dict.fromkeys(to_delete_keys))
                deleted = 0
                batch_size = 200
                for i in range(0, len(uniq_keys), batch_size):
                    batch = uniq_keys[i:i + batch_size]
                    placeholders = ",".join(["?"] * len(batch))
                    if os.name == 'nt':
                        cursor.execute(
                            f"DELETE FROM {table_name} WHERE lower(replace(file_path, '/', '\\\\')) IN ({placeholders})",
                            batch
                        )
                    else:
                        cursor.execute(
                            f"DELETE FROM {table_name} WHERE lower(file_path) IN ({placeholders})",
                            [b.lower() for b in batch]
                        )
                    deleted += cursor.rowcount if cursor.rowcount is not None else 0

                conn.commit()
                return deleted
            finally:
                conn.close()

    def update_image_label(self, file_path, label):
        """
        更新图片的色标
        :param file_path: 图片路径
        :param label: 色标 (Green, Blue, Yellow, Red, Purple, White, Orange, Pink, Black, None/Empty)
        """
        if not file_path:
            return

        try:
            LogManager.instance().info(f"[DB] Updating label to {label} for {file_path}")
        except Exception:
            pass
            
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                record = self.get_result_by_path(file_path, table_name='bird_results')
                if record and record.get('file_path'):
                    cursor.execute("UPDATE bird_results SET label = ? WHERE file_path = ?", (label, record.get('file_path')))
                else:
                    cursor.execute("UPDATE bird_results SET label = ? WHERE file_path = ?", (label, file_path))
                    if cursor.rowcount == 0:
                        cursor.execute("UPDATE bird_results SET label = ? WHERE file_path = ? COLLATE NOCASE", (label, file_path))
                self._dedupe_specific_normalized_paths(cursor, 'bird_results', [self._norm_path_key(file_path)])
                conn.commit()
            except Exception as e:
                try:
                    LogManager.instance().warning(f"更新色标失败 {file_path}: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def update_file_path(self, old_path, new_path, new_name, table_name='bird_results'):
        """
        更新文件路径和文件名 (用于重命名)
        :param old_path: 旧文件路径
        :param new_path: 新文件路径
        :param new_name: 新文件名
        :param table_name: 目标表名
        """
        if table_name not in ['bird_results', 'import_cache']:
            return

        try:
            LogManager.instance().info(f"[DB] Updating file path from {old_path} to {new_path} (new_name={new_name}) in {table_name}")
        except Exception:
            pass

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                old_record = self.get_result_by_path(old_path, table_name=table_name)
                real_old_path = old_record.get('file_path') if old_record else old_path
                new_path_db = self._normalize_file_path_for_db(new_path)
                if not new_path_db:
                    return
                try:
                    if os.name == "nt":
                        np0 = os.path.normcase(os.path.normpath(str(new_path_db).replace("/", "\\")))
                        if "\\$recycle.bin\\" in str(np0).lower():
                            try:
                                conn.execute(f"DELETE FROM {table_name} WHERE file_path = ?", (real_old_path,))
                            except Exception:
                                try:
                                    conn.execute(f"DELETE FROM {table_name} WHERE file_path = ? COLLATE NOCASE", (real_old_path,))
                                except Exception:
                                    pass
                            try:
                                conn.commit()
                            except Exception:
                                pass
                            return
                except Exception:
                    pass
                cursor.execute(f"UPDATE {table_name} SET file_path = ?, file_name = ? WHERE file_path = ?", 
                           (new_path_db, new_name, real_old_path))
                
                if cursor.rowcount == 0:
                    # 尝试不区分大小写匹配 (针对 Windows 路径)
                    # 注意：如果数据库中有多个仅大小写不同的路径（理论上 Windows 不会，但数据库可能），这里可能会更新多个，
                    # 但由于 file_path 是 UNIQUE，所以应该没问题。
                    cursor.execute(f"UPDATE {table_name} SET file_path = ?, file_name = ? WHERE file_path = ? COLLATE NOCASE", 
                           (new_path_db, new_name, real_old_path))
                self._dedupe_specific_normalized_paths(cursor, table_name, [self._norm_path_key(new_path_db), self._norm_path_key(real_old_path)])
                conn.commit()
            except sqlite3.IntegrityError:
                try:
                    LogManager.instance().warning(
                        f"更新文件路径触发唯一性冲突，尝试清理残留记录: target={new_path_db}"
                    )
                except Exception:
                    pass
                try:
                    # 目标路径在数据库中已存在（可能是残留记录），先删除它
                    conn.execute(f"DELETE FROM {table_name} WHERE file_path = ?", (new_path_db,))
                    # 再次尝试更新
                    conn.execute(f"UPDATE {table_name} SET file_path = ?, file_name = ? WHERE file_path = ?", 
                           (new_path_db, new_name, real_old_path))
                    self._dedupe_specific_normalized_paths(cursor, table_name, [self._norm_path_key(new_path_db), self._norm_path_key(real_old_path)])
                    conn.commit()
                except Exception as retry_e:
                    try:
                        LogManager.instance().warning(f"重试更新文件路径失败: {retry_e}")
                    except Exception:
                        pass
            except Exception as e:
                try:
                    LogManager.instance().warning(f"更新文件路径失败: {e}")
                except Exception:
                    pass
            finally:
                conn.close()

    def delete_results_under_folder(self, folder_path, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return 0
        folder_db = self._normalize_file_path_for_db(folder_path)
        if not folder_db:
            return 0
        try:
            folder_db = os.path.normpath(folder_db)
        except Exception:
            pass
        prefix = os.path.join(folder_db, "")
        prefix_key = self._norm_path_key(prefix)
        if not prefix_key:
            return 0

        try:
            LogManager.instance().info(f"[DB] Deleting results under folder {folder_path} from {table_name}")
        except Exception:
            pass

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if os.name == 'nt':
                    cursor.execute(
                        f"DELETE FROM {table_name} WHERE lower(replace(file_path, '/', '\\\\')) LIKE ?",
                        (prefix_key + "%",),
                    )
                else:
                    cursor.execute(
                        f"DELETE FROM {table_name} WHERE lower(file_path) LIKE ?",
                        (prefix.lower() + "%",),
                    )
                deleted = cursor.rowcount if cursor.rowcount is not None else 0
                conn.commit()
                return int(deleted)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"删除文件夹下记录失败: {e}")
                except Exception:
                    pass
                return 0
            finally:
                conn.close()

    def update_folder_paths_and_taxonomy(self, old_folder, new_folder, root_path=None, table_name='bird_results'):
        if table_name not in ['bird_results', 'import_cache']:
            return 0
        old_db = self._normalize_file_path_for_db(old_folder)
        new_db = self._normalize_file_path_for_db(new_folder)
        if not old_db or not new_db:
            return 0
        try:
            old_db = os.path.normpath(old_db)
            new_db = os.path.normpath(new_db)
        except Exception:
            pass

        root_db = None
        if root_path:
            root_db = self._normalize_file_path_for_db(root_path)
            try:
                root_db = os.path.normpath(root_db)
            except Exception:
                pass

        old_prefix = os.path.join(old_db, "")
        old_prefix_key = self._norm_path_key(old_prefix)
        if not old_prefix_key:
            return 0

        try:
            LogManager.instance().info(f"[DB] Updating folder paths from {old_folder} to {new_folder} in {table_name}")
        except Exception:
            pass

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if os.name == 'nt':
                    cursor.execute(
                        f"SELECT file_path FROM {table_name} WHERE lower(replace(file_path, '/', '\\\\')) LIKE ?",
                        (old_prefix_key + "%",),
                    )
                else:
                    cursor.execute(
                        f"SELECT file_path FROM {table_name} WHERE lower(file_path) LIKE ?",
                        (old_prefix.lower() + "%",),
                    )
                rows = cursor.fetchall()
                if not rows:
                    return 0

                updated = 0
                for r in rows:
                    old_fp = r["file_path"] if isinstance(r, dict) else r[0]
                    if not old_fp:
                        continue
                    try:
                        old_fp_norm = os.path.normpath(str(old_fp))
                    except Exception:
                        old_fp_norm = str(old_fp)

                    suffix = ""
                    try:
                        if os.name == 'nt':
                            if self._norm_path_key(old_fp_norm).startswith(self._norm_path_key(old_db)):
                                suffix = old_fp_norm[len(old_db):]
                        else:
                            if old_fp_norm.startswith(old_db):
                                suffix = old_fp_norm[len(old_db):]
                    except Exception:
                        suffix = ""
                    new_fp = new_db + suffix
                    try:
                        new_fp = os.path.normpath(new_fp)
                    except Exception:
                        pass
                    new_name = os.path.basename(new_fp)

                    order_cls = None
                    family_cls = None
                    genus_cls = None
                    species_cls = None
                    if root_db:
                        try:
                            rel = os.path.relpath(os.path.normpath(new_fp), os.path.normpath(root_db))
                            parts = [p for p in rel.split(os.sep) if p and p != "."]
                            if len(parts) >= 1:
                                order_cls = parts[0]
                            if len(parts) >= 2:
                                family_cls = parts[1]
                            if len(parts) >= 3:
                                genus_cls = parts[2]
                            if len(parts) >= 4:
                                species_cls = parts[3]
                        except Exception:
                            pass

                    params = [self._normalize_file_path_for_db(new_fp), new_name]
                    sets = "file_path = ?, file_name = ?"
                    if order_cls is not None:
                        sets += ", order_cls = ?"
                        params.append(order_cls)
                    if family_cls is not None:
                        sets += ", family_cls = ?"
                        params.append(family_cls)
                    if genus_cls is not None:
                        sets += ", genus_cls = ?"
                        params.append(genus_cls)
                    if species_cls is not None:
                        sets += ", species_cls = ?"
                        params.append(species_cls)
                    params.append(old_fp)

                    cursor.execute(f"UPDATE {table_name} SET {sets} WHERE file_path = ?", tuple(params))
                    if cursor.rowcount == 0:
                        cursor.execute(f"UPDATE {table_name} SET {sets} WHERE file_path = ? COLLATE NOCASE", tuple(params))
                    updated += cursor.rowcount if cursor.rowcount is not None else 0

                conn.commit()
                return int(updated)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"update_folder_paths_and_taxonomy failed: {e}")
                except Exception:
                    pass
                return 0
            finally:
                conn.close()
