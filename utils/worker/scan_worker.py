from PyQt6.QtCore import QThread, pyqtSignal
import exiftool
import os
import sys
import time
import subprocess
import json
import tempfile
from utils.setting.settings_manager import SettingsManager
from utils.file.library_scanner import LibraryScanner
from utils.file.fingerprint import get_unique_id
from utils.file.file_util import get_fast_id
from utils.exif.exif_utils import get_exiftool_path, EXIF_TAG, ExifHandleWorker, run_exiftool
from utils.sql.data_base import BirdLibraryDB
from utils.taxonomy.path_taxonomy_matcher import match_taxonomy_from_path
from utils.log_manager import LogManager

class ScanWorker(QThread):
    progress_updated = pyqtSignal(int, int, str)
    scan_finished = pyqtSignal()
    pending_exif_updates = [] # 存储待写入 Exif 的任务 [(path, tags), ...]

    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path
        self.is_cancelled = False
        self.pending_exif_updates = [] # 初始化为空列表
        self.auto_submit_exif = False # 标志位：是否自动提交 Exif 任务
        self.scanned_files = []

    def _vendor_group_from_camera_model(self, camera_model):
        try:
            token = str(camera_model or "").strip().split()[0].strip()
        except Exception:
            token = ""
        if not token:
            return ""
        token_upper = token.upper()
        vendor_map = {
            "NIKON": "Nikon",
            "CANON": "Canon",
            "SONY": "Sony",
            "FUJIFILM": "FujiFilm",
            "OLYMPUS": "Olympus",
            "PANASONIC": "Panasonic",
            "PENTAX": "Pentax",
            "LEICA": "Leica",
            "SIGMA": "Sigma",
            "DJI": "DJI",
            "HASSELBLAD": "Hasselblad",
        }
        for k, v in vendor_map.items():
            if token_upper.startswith(k):
                return v
        return token.title()
    
    def _normalize_path_key(self, path):
        if not path:
            return path
        try:
            return os.path.normcase(os.path.normpath(str(path).replace("/", os.sep)))
        except Exception:
            return str(path)

    def get_pending_exif_updates(self):
        """获取所有待写入的 Exif 任务"""
        return self.pending_exif_updates

    def enable_auto_submit_exif(self):
        """开启自动提交 Exif 任务模式"""
        self.auto_submit_exif = True

    def run(self):
        self.pending_exif_updates = [] # 重置
        self.scanned_files = []
        try:
            try:
                can_print = not bool(getattr(sys, "frozen", False))
            except Exception:
                can_print = False
            # 1. 扫描文件
            self.progress_updated.emit(0, 0, "正在扫描文件系统...")
            t_scan0 = time.time()
            try:
                # [Optimization] 避免频繁读取配置导致卡顿
                settings = SettingsManager()
                # 显式转换类型并提供默认值
                try:
                    strict_mode = bool(settings.get("setting/bird_strict", True))
                except Exception:
                    strict_mode = True
                
                try:
                    scan_depth_val = settings.get("library/scan_depth", 0)
                    scan_depth = int(scan_depth_val) if scan_depth_val is not None else 0
                except Exception:
                    scan_depth = 0
                if scan_depth < 0:
                    try:
                        LogManager.instance().info(f"[ScanWorker] Skip scanning by config: root={self.root_path}")
                    except Exception:
                        pass
                    try:
                        self.progress_updated.emit(0, 0, "已选择不扫描模式")
                    except Exception:
                        pass
                    self.scanned_files = []
                    self.scan_finished.emit()
                    return
                max_depth = scan_depth if scan_depth > 0 else None
                
                try:
                    exclude_dirs_val = settings.get("library/scan_exclude_dirs", [])
                    exclude_dirs = list(exclude_dirs_val) if exclude_dirs_val else []
                except Exception:
                    exclude_dirs = []
            except Exception:
                strict_mode = True
                max_depth = None
                exclude_dirs = []
            
            # [Fix] 首次启动/恢复初始设置后，如果用户选择了根目录扫描且配置为空，
            # 强制添加一些默认的系统目录排除，防止扫描整个系统盘导致卡死
            if not exclude_dirs:
                default_excludes = [
                    "Program Files", "Program Files (x86)", "Windows", 
                    "AppData", "Application Data", "ProgramData",
                    "$RECYCLE.BIN", "System Volume Information", "Recovery",
                    "Documents and Settings", "Intel", "PerfLogs", "Boot"
                ]
                # 转换为当前系统的绝对路径（如果 root_path 是根目录）
                # 如果 root_path 不是根目录，这些相对匹配可能无效，但也不影响
                
                # 如果 root_path 包含盘符，尝试构造绝对路径
                try:
                    drive = os.path.splitdrive(self.root_path)[0]
                    if drive:
                        for de in default_excludes:
                            full_ex = os.path.join(drive + os.sep, de)
                            if full_ex not in exclude_dirs:
                                exclude_dirs.append(full_ex)
                except Exception:
                    pass
                
                # 同时把原始名称也加进去，防止 _is_excluded_dir 的 startswith 逻辑漏网
                for de in default_excludes:
                     if de not in exclude_dirs:
                         exclude_dirs.append(de)

            try:
                exclude_regex = str(settings.get("library/scan_exclude_regex", "") or "")
            except Exception:
                exclude_regex = ""

            # [Log] 记录扫描参数，辅助排查首次启动卡死问题
            try:
                LogManager.instance().info(f"[ScanWorker] Start scanning: root={self.root_path}, strict={strict_mode}, max_depth={max_depth}")
                LogManager.instance().info(f"[ScanWorker] Exclude dirs ({len(exclude_dirs)}): {exclude_dirs[:5]}...")
                LogManager.instance().info(f"[ScanWorker] Exclude regex: {exclude_regex}")
            except:
                pass

            def _on_scan_progress(dir_count: int, found_count: int, current_dir: str):
                try:
                    rel = os.path.relpath(str(current_dir or ""), str(self.root_path or ""))
                except Exception:
                    rel = str(current_dir or "")
                if rel == ".":
                    rel = ""
                # 如果 rel 超过一定长度，截断显示
                if len(rel) > 40:
                     rel = "..." + rel[-37:]
                     
                # 尝试获取 files_processed_in_current_dir (如果是 LibraryScanner 传递了额外参数)
                # 目前 LibraryScanner 只传 3 个参数，但为了扩展性，我们保持兼容
                # 实际上 LibraryScanner 修改后也不会传第 4 个参数，除非我们修改 scan 方法签名
                # 但我们可以在 current_dir 字符串里做文章，或者让 LibraryScanner 传更丰富的信息
                
                msg = f"正在扫描..."
                if rel:
                    msg = msg + f" | {rel}"
                try:
                    self.progress_updated.emit(0, 0, msg)
                except Exception:
                    pass

            files = LibraryScanner.scan(
                self.root_path,
                strict_mode=strict_mode,
                max_depth=max_depth,
                exclude_dirs=exclude_dirs,
                exclude_regex=exclude_regex,
                progress_callback=_on_scan_progress,
                cancel_check=lambda: bool(self.is_cancelled),
            )
            self.scanned_files = files or []
            total = len(files)
            try:
                LogManager.instance().warning(f"[PROFILE][ScanWorker] scan_fs done files={total} elapsed={time.time() - t_scan0:.2f}s")
            except Exception:
                pass
            if can_print:
                try:
                    print(f"[PROFILE][ScanWorker] scan_fs done files={total} elapsed={time.time() - t_scan0:.2f}s")
                except Exception:
                    pass
            
            # [Log] 记录扫描结果
            try:
                LogManager.instance().info(f"[ScanWorker] LibraryScanner found {total} files.")
                if total > 0:
                    LogManager.instance().info(f"[ScanWorker] First 5 files: {files[:5]}")
            except:
                pass
            
            if total == 0:
                self.progress_updated.emit(0, 0, "未找到符合条件的图片")
                self.scan_finished.emit()
                return

            # 2. 批量读取 Exif 并写入数据库
            db = BirdLibraryDB()
            is_first_run = False
            try:
                is_first_run = settings.get("general/first_run", False)
                if isinstance(is_first_run, str):
                    is_first_run = is_first_run.lower() == 'true'
                if not is_first_run:
                    db.cleanup_missing_files(files, root_path=self.root_path, table_name='bird_results')
                    db.cleanup_missing_files(files, root_path=self.root_path, table_name='import_cache')
            except Exception:
                pass
            
            has_existing_records = False
            try:
                conn = db._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1 FROM bird_results LIMIT 1")
                    has_existing_records = cur.fetchone() is not None
                finally:
                    conn.close()
            except Exception:
                has_existing_records = False
            try:
                LogManager.instance().warning(f"[PROFILE][ScanWorker] db_has_existing_records={int(bool(has_existing_records))}")
            except Exception:
                pass
            if can_print:
                try:
                    print(f"[PROFILE][ScanWorker] db_has_existing_records={int(bool(has_existing_records))}")
                except Exception:
                    pass

            seen_uuid = set()
            exe = get_exiftool_path()
            if not exe or not os.path.exists(exe):
                self.progress_updated.emit(0, 0, f"未找到 ExifTool: {exe}")
                self.scan_finished.emit()
                return
            
            # 创建临时 config 文件
            from utils.exif.exif_utils import create_temp_config_file
            config_file = create_temp_config_file()
            common_args = ["-config", config_file] if config_file else []

            # 提前启动缩略图预加载（取前100张）
            if files and (not is_first_run):
                try:
                    from cache.cache_manager import ImageCacheManager
                    preload_paths = files[:100]
                    ImageCacheManager.instance().preload(preload_paths)
                except Exception as e:
                    try:
                        LogManager.instance().warning(f"启动缩略图预加载失败: {e}")
                    except Exception:
                        pass
            
            batch_size = 100
            processed = 0

            disable_write = False
            try:
                val = SettingsManager().get("exif/disable_write", False)
                if isinstance(val, str):
                    disable_write = val.lower() == 'true'
                else:
                    disable_write = bool(val)
            except Exception:
                pass

            exif_worker = None
            try:
                exif_worker = ExifHandleWorker.get_instance()
            except Exception:
                exif_worker = None
            
            # [Fix] 确保循环步进正确，防止死循环
            # total 是总文件数
            i = 0
            while i < total:
                if self.is_cancelled: break
                
                # 计算本次批次的切片范围
                end_idx = min(i + batch_size, total)
                batch = files[i : end_idx]
                
                # 如果 batch 为空（虽然理论上不会，因为 i < total），则跳出
                if not batch:
                    break

                try:
                    ext_count = {}
                    for p in batch:
                        try:
                            ext = os.path.splitext(str(p))[-1].lower()
                        except Exception:
                            ext = ""
                        ext_count[ext] = ext_count.get(ext, 0) + 1
                    top_ext = sorted(ext_count.items(), key=lambda kv: kv[1], reverse=True)[:5]
                    LogManager.instance().info(f"[ScanWorker] Batch start idx={i} size={len(batch)} exts={top_ext}")
                except Exception:
                    pass
                
                # 准备批量写入的数据列表
                batch_db_data = []
                # batch_exif_update_tasks = [] # 局部变量不再需要，直接存入 self.pending_exif_updates

                try:
                    t_batch0 = time.time()
                    # 读取必要的标签
                    # 包括时间、ImageWidth, ImageHeight 等
                    tags_to_read = [
                        "DateTimeOriginal", "CreateDate", "FileModifyDate",
                        "ImageWidth", "ImageHeight"
                    ] + [tag.value for tag in EXIF_TAG if tag.value != EXIF_TAG.Description.value]
                    # 确保读取 Fastid
                    if EXIF_TAG.Fastid.value not in tags_to_read:
                            tags_to_read.append(EXIF_TAG.Fastid.value)
                    
                    t_exif_start = time.time()

                    metadata_list = []
                    def _safe_parse_exif_json(raw_text: str):
                        try:
                            s = "" if raw_text is None else str(raw_text)
                        except Exception:
                            s = ""
                        s = s.strip()
                        if not s:
                            raise ValueError("empty exiftool output")

                        try:
                            start = s.find("[")
                            end = s.rfind("]")
                            if start != -1 and end != -1 and end > start:
                                s = s[start : end + 1]
                        except Exception:
                            pass
                        return json.loads(s)

                    try:
                        if exif_worker is not None:
                            try:
                                LogManager.instance().info(f"[ScanWorker] ExifTool(stay_open) batch start idx={i} size={len(batch)}")
                            except Exception:
                                pass

                            args = ["-charset", "filename=utf8", "-json", "-c", "%.6f"]
                            for tag in tags_to_read:
                                args.append("-" + str(tag))
                            for p in batch:
                                args.append(str(p))

                            timeout = max(30, int(len(batch) * 2))
                            raw = exif_worker._stayopen_exec(args, timeout=timeout)
                            try:
                                metadata_list = _safe_parse_exif_json(raw)
                            except Exception as e_json:
                                try:
                                    snippet = ""
                                    try:
                                        snippet = (str(raw or "").replace("\r", "\\r").replace("\n", "\\n"))[:600]
                                    except Exception:
                                        snippet = ""
                                    LogManager.instance().warning(f"[ScanWorker] stay_open JSON parse failed: {e_json}; raw_head={snippet}")
                                except Exception:
                                    pass
                                raise
                        else:
                            raise RuntimeError("ExifHandleWorker not available")
                    except Exception as e:
                        try:
                            LogManager.instance().warning(f"[ScanWorker] ExifTool(stay_open) failed, fallback to subprocess: {e}")
                        except Exception:
                            pass

                        arg_file = None
                        try:
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                                for path in batch:
                                    f.write(f"{path}\n")
                                arg_file = f.name

                            cmd = [exe] + common_args + ["-charset", "filename=utf8", "-json", "-c", "%.6f"]
                            for tag in tags_to_read:
                                cmd.append("-" + tag)
                            cmd.extend(["-@", arg_file])

                            try:
                                LogManager.instance().info(f"[ScanWorker] ExifTool(subprocess) batch start idx={i} size={len(batch)}")
                            except Exception:
                                pass

                            res = run_exiftool(cmd)
                            if res.returncode != 0:
                                try:
                                    err = str(res.stderr or "")
                                    if len(err) > 1000:
                                        err = err[:1000] + "..."
                                    LogManager.instance().warning(f"ExifTool 批量读取失败(batch {i}): {err}")
                                except Exception:
                                    pass
                                metadata_list = []
                            else:
                                try:
                                    metadata_list = _safe_parse_exif_json(res.stdout)
                                except Exception as e2:
                                    try:
                                        LogManager.instance().warning(f"ExifTool JSON 解析失败(batch {i}): {e2}")
                                    except Exception:
                                        pass
                                    metadata_list = []
                        finally:
                            if arg_file and os.path.exists(arg_file):
                                try:
                                    os.remove(arg_file)
                                except Exception:
                                    pass

                    try:
                        for meta in (metadata_list or []):
                            for tag in EXIF_TAG:
                                if tag.value == EXIF_TAG.Description.value:
                                    continue
                                short_name = tag.value.split(":")[-1]
                                if short_name in meta and tag.value not in meta:
                                    meta[tag.value] = meta[short_name]
                    except Exception:
                        pass

                    t_exif_end = time.time()

                    # 计算平均每个文件的 Exif 读取时间
                    avg_exif_time = (t_exif_end - t_exif_start) / len(batch) if batch else 0
                    try:
                        LogManager.instance().info(
                            f"[ScanWorker] Exif batch done idx={i} size={len(batch)} meta={len(metadata_list or [])} elapsed={t_exif_end - t_exif_start:.2f}s avg={avg_exif_time:.3f}s"
                        )
                    except Exception:
                        pass
                    try:
                        if is_first_run or (t_exif_end - t_exif_start) >= 2.0:
                            LogManager.instance().warning(
                                f"[PROFILE][ScanWorker] exif_read idx={i} size={len(batch)} meta={len(metadata_list or [])} elapsed={t_exif_end - t_exif_start:.2f}s"
                            )
                    except Exception:
                        pass
                    if can_print:
                        try:
                            print(
                                f"[PROFILE][ScanWorker] exif_read idx={i} size={len(batch)} meta={len(metadata_list or [])} elapsed={t_exif_end - t_exif_start:.2f}s"
                            )
                        except Exception:
                            pass

                    meta_map = {}
                    name_map = {}
                    try:
                        for meta in (metadata_list or []):
                            p = meta.get("SourceFile")
                            k = db._norm_path_key(p)
                            if k:
                                meta_map[k] = meta
                            
                            # 同时也记录文件名映射
                            if p:
                                try:
                                    fname = os.path.basename(p)
                                    # 只有当该文件名在当前 batch 中唯一时才作为备选
                                    # (简单起见，这里总是覆盖，因为通常 batch 内重名概率低，且即使重名也只是备选)
                                    # 更严谨的做法是统计重名，如果有重名则放弃文件名匹配
                                    if fname not in name_map:
                                        name_map[fname] = meta
                                    else:
                                        name_map[fname] = "CONFLICT" 
                                except Exception:
                                    pass
                    except Exception:
                        meta_map = {}

                    existing_user_map = {}
                    if has_existing_records:
                        try:
                            t_um0 = time.time()
                            existing_user_map = db.get_user_fields_map(batch, table_name='bird_results')
                            t_um1 = time.time()
                            if is_first_run or (t_um1 - t_um0) >= 0.5:
                                try:
                                    LogManager.instance().warning(
                                        f"[PROFILE][ScanWorker] db_get_user_fields idx={i} size={len(batch)} elapsed={t_um1 - t_um0:.2f}s"
                                    )
                                except Exception:
                                    pass
                            if can_print:
                                try:
                                    print(f"[PROFILE][ScanWorker] db_get_user_fields idx={i} size={len(batch)} elapsed={t_um1 - t_um0:.2f}s")
                                except Exception:
                                    pass
                        except Exception:
                            existing_user_map = {}
                    
                    from datetime import datetime
                    last_ui_emit_ts = 0.0
                    t_build0 = time.time()
                    
                    for idx, fpath in enumerate(batch):
                        t_process_start = time.time()
                        
                        meta = meta_map.get(db._norm_path_key(fpath))
                        
                        # 如果全路径匹配失败，尝试文件名匹配
                        if not meta:
                            try:
                                fname = os.path.basename(fpath)
                                candidate = name_map.get(fname)
                                if candidate and candidate != "CONFLICT":
                                    meta = candidate
                            except Exception:
                                pass
                        
                        if not meta:
                             meta = {"SourceFile": fpath}
                             # ExifTool 读取失败，尝试补充文件系统时间
                             try:
                                 stat = os.stat(fpath)
                                 # 格式化为 Exif 风格的时间字符串 "YYYY:MM:DD HH:MM:SS"
                                 ctime = datetime.fromtimestamp(stat.st_ctime).strftime('%Y:%m:%d %H:%M:%S')
                                 mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y:%m:%d %H:%M:%S')
                                 meta["CreateDate"] = ctime
                                 meta["FileModifyDate"] = mtime
                                 meta["DateTimeOriginal"] = mtime # 兜底
                             except Exception:
                                 pass

                        existing_user = None
                        try:
                            existing_user = existing_user_map.get(db._norm_path_key(fpath))
                        except Exception:
                            existing_user = None

                        def _get_meta_value(tag: EXIF_TAG):
                            try:
                                if tag.value in meta:
                                    return meta.get(tag.value)
                            except Exception:
                                pass
                            try:
                                short = tag.value.split(":")[-1]
                                if short in meta:
                                    return meta.get(short)
                            except Exception:
                                pass
                            return None

                        # 获取或生成 UUID
                        uuid = _get_meta_value(EXIF_TAG.Uuid)
                        uuid_need_write = False
                        if not uuid:
                            uuid = get_unique_id()
                            uuid_need_write = True
                        try:
                            if uuid and uuid in seen_uuid:
                                uuid = get_unique_id()
                                uuid_need_write = True
                        except Exception:
                            pass
                        try:
                            if uuid:
                                seen_uuid.add(uuid)
                        except Exception:
                            pass

                        # [Fix] 如果元数据中已有 UUID，但数据库中已存在相同的 UUID 且对应不同的文件路径（或者 fast_id 不同），
                        # 这通常意味着用户复制了文件（如 DSC_0098 - 副本.NEF），导致两个文件拥有完全相同的 UUID。
                        # 这种情况下，数据库会因为 UUID 主键冲突而拒绝写入第二个文件，导致界面上只显示一张。
                        # 修复方案：检测 UUID 冲突，如果冲突则为当前文件生成新的 UUID，并标记需要写入 Exif。
                        
                        if uuid and not uuid_need_write:
                            # 检查 UUID 是否已存在于 DB 中（但这需要查 DB，性能开销大）
                            # 更高效的方法是利用 fast_id 或文件路径来辅助判断。
                            # 或者，我们可以在下面的 try-except 写入 DB 失败时（IntegrityError）进行重试。
                            # 但为了更好的用户体验（因为要改写 Exif），最好在这里预判。
                            
                            # 这里简单起见，如果文件名包含 "副本"、"Copy" 或匹配正则 " \(\d+\)"，
                            # 且 UUID 已存在（这一步其实很难预判，除非把所有 UUID 加载到内存），
                            # 我们可以强制检查 fast_id。
                            
                            # 实际上，最稳妥的方式是：
                            # 只要是扫描到的文件，我们假设它是独立的。
                            # 如果数据库写入时报 UUID 冲突，我们在 catch 块里重新生成 UUID 并重试。
                            pass

                        # 计算 fast_id（快速且相对稳定的文件标识）
                        fast_id = get_fast_id(fpath)
                        
                        # 准备需要写入的标签
                        tags_to_write = {}
                        if uuid_need_write:
                            tags_to_write[EXIF_TAG.Uuid.value] = uuid
                        
                        if fast_id:
                            current_fastid = _get_meta_value(EXIF_TAG.Fastid)
                            if current_fastid != fast_id:
                                tags_to_write[EXIF_TAG.Fastid.value] = fast_id

                        # 优先取 DateTimeOriginal，其次 CreateDate，最后 FileModifyDate
                        time_str = meta.get("DateTimeOriginal") or \
                                    meta.get("CreateDate") or \
                                    meta.get("FileModifyDate")
                        
                        width = meta.get("ImageWidth") or 0
                        height = meta.get("ImageHeight") or 0
                        pixel_count = int(width) * int(height) if width and height else 0

                        # 解析 bbox
                        bbox_raw = meta.get(EXIF_TAG.ObjectCoordinates.value)
                        bbox = None
                        if bbox_raw:
                            if isinstance(bbox_raw, list):
                                try:
                                    if len(bbox_raw) >= 4:
                                        bbox = [int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])]
                                except Exception:
                                    bbox = None
                            elif isinstance(bbox_raw, str):
                                try:
                                    bbox_json = json.loads(bbox_raw)
                                    if isinstance(bbox_json, dict):
                                        x = int(bbox_json.get("x", 0))
                                        y = int(bbox_json.get("y", 0))
                                        w = int(bbox_json.get("w", 0))
                                        h = int(bbox_json.get("h", 0))
                                        bbox = [x, y, x + w, y + h]
                                    elif isinstance(bbox_json, list) and len(bbox_json) >= 4:
                                        bbox = [int(bbox_json[0]), int(bbox_json[1]), int(bbox_json[2]), int(bbox_json[3])]
                                except:
                                    try:
                                        bbox = [int(x) for x in bbox_raw.replace(',', ' ').split()]
                                    except:
                                        pass
                        try:
                            if bbox is not None and len(bbox) >= 4:
                                bbox = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
                        except Exception:
                            bbox = None

                        parsed_focus_point = None

                        order_cls = None
                        family_cls = None
                        genus_cls = None
                        species_cls = None

                        taxonomy_from_path = None
                        try:
                            taxonomy_from_path = match_taxonomy_from_path(fpath, self.root_path)
                        except Exception:
                            taxonomy_from_path = None

                        if isinstance(taxonomy_from_path, dict):
                            order_cls = taxonomy_from_path.get("order_cls")
                            family_cls = taxonomy_from_path.get("family_cls")
                            genus_cls = taxonomy_from_path.get("genus_cls")
                            species_cls = taxonomy_from_path.get("species_cls")

                        has_full_taxonomy = bool(order_cls and family_cls and genus_cls and species_cls)
                        if has_full_taxonomy:
                            try:
                                exif_order = _get_meta_value(EXIF_TAG.OrderCls)
                                exif_family = _get_meta_value(EXIF_TAG.FamilyCls)
                                exif_genus = _get_meta_value(EXIF_TAG.GenusCls)
                                exif_species = _get_meta_value(EXIF_TAG.SpeciesCls)
                                if not exif_order:
                                    tags_to_write[EXIF_TAG.OrderCls.value] = str(order_cls)
                                if not exif_family:
                                    tags_to_write[EXIF_TAG.FamilyCls.value] = str(family_cls)
                                if not exif_genus:
                                    tags_to_write[EXIF_TAG.GenusCls.value] = str(genus_cls)
                                if not exif_species:
                                    tags_to_write[EXIF_TAG.SpeciesCls.value] = str(species_cls)
                            except Exception:
                                pass
                        else:
                            exif_order = _get_meta_value(EXIF_TAG.OrderCls)
                            exif_family = _get_meta_value(EXIF_TAG.FamilyCls)
                            exif_genus = _get_meta_value(EXIF_TAG.GenusCls)
                            exif_species = _get_meta_value(EXIF_TAG.SpeciesCls)
                            if exif_order and exif_family and exif_genus and exif_species:
                                order_cls = str(exif_order)
                                family_cls = str(exif_family)
                                genus_cls = str(exif_genus)
                                species_cls = str(exif_species)

                        if tags_to_write:
                            self.pending_exif_updates.append((fpath, tags_to_write))
                        # 构造数据
                        data = {
                            "uuid": uuid,
                            "fast_id": fast_id,
                            "path": fpath,
                            "file": os.path.basename(fpath),
                            "label": meta.get(EXIF_TAG.Label.value, ""),
                            "score": float(meta.get(EXIF_TAG.Score.value, 0) or 0),
                            "norm_score": 0,
                            "bbox": bbox,
                            "position": meta.get(EXIF_TAG.Position.value, ""),
                            "pixel_count": pixel_count,
                            "area_ratio": float(meta.get(EXIF_TAG.AreaRatio.value, 0.0) or 0.0),
                            "focus_point": parsed_focus_point,
                            "object": meta.get(EXIF_TAG.Object.value),
                            "order_cls": order_cls,
                            "family_cls": family_cls,
                            "genus_cls": genus_cls,
                            "species_cls": species_cls,
                            "eye_coordinates": meta.get(EXIF_TAG.EyeCoordinates.value),
                            "description": meta.get(EXIF_TAG.BmpDescription.value),
                            "is_favorite": 1 if str(meta.get(EXIF_TAG.Favorite.value, "")).lower() == "true" else 0,
                            "rating": int(meta.get(EXIF_TAG.Rating.value, 0) or 0),
                            "shot_time": time_str,
                            "fnumber": float(meta.get(EXIF_TAG.FNumber.value, 0.0) or 0.0),
                            "shutter": meta.get(EXIF_TAG.ShutterSpeed.value),
                            "iso": int(meta.get(EXIF_TAG.ISO.value, 0) or 0),
                            "focal_length": meta.get(EXIF_TAG.FocalLength.value),
                            "camera_model": meta.get(EXIF_TAG.CameraModel.value),
                            "lens_model": meta.get(EXIF_TAG.LensModel.value),
                            "focus_distance": str(meta.get(EXIF_TAG.FocusDistance.value) or ""),
                            "latitude": float(meta.get(EXIF_TAG.GPSLatitude.value, 0.0) or 0.0),
                            "longitude": float(meta.get(EXIF_TAG.GPSLongitude.value, 0.0) or 0.0),
                            "location": meta.get(EXIF_TAG.Location.value, ""),
                            "tags": meta.get(EXIF_TAG.Tags.value, ""),
                            # "created_at": ... 数据库会自动处理
                        }

                        if existing_user:
                            try:
                                if not data.get('label') and existing_user.get('label'):
                                    data['label'] = existing_user.get('label')
                            except Exception:
                                pass
                            try:
                                if not data.get('description') and existing_user.get('description'):
                                    data['description'] = existing_user.get('description')
                            except Exception:
                                pass
                            
                            try:
                                tags_present = EXIF_TAG.Tags.value in meta or EXIF_TAG.Tags.value.split(":")[-1] in meta
                            except:
                                tags_present = False
                            if not tags_present and existing_user.get('tags'):
                                data['tags'] = existing_user.get('tags')

                            try:
                                loc_present = EXIF_TAG.Location.value in meta or EXIF_TAG.Location.value.split(":")[-1] in meta
                            except:
                                loc_present = False
                            if not loc_present and existing_user.get('location'):
                                data['location'] = existing_user.get('location')

                            try:
                                gps_present = EXIF_TAG.GPSLatitude.value in meta or EXIF_TAG.GPSLatitude.value.split(":")[-1] in meta
                            except:
                                gps_present = False
                            if not gps_present:
                                if existing_user.get('latitude'):
                                    data['latitude'] = existing_user.get('latitude')
                                if existing_user.get('longitude'):
                                    data['longitude'] = existing_user.get('longitude')

                            try:
                                fav_present = EXIF_TAG.Favorite.value in meta or EXIF_TAG.Favorite.value.split(":")[-1] in meta
                            except Exception:
                                fav_present = False
                            if not fav_present:
                                try:
                                    data['is_favorite'] = int(existing_user.get('is_favorite') or 0)
                                except Exception:
                                    pass

                            try:
                                rating_present = EXIF_TAG.Rating.value in meta or EXIF_TAG.Rating.value.split(":")[-1] in meta
                            except Exception:
                                rating_present = False
                            if not rating_present:
                                try:
                                    data['rating'] = int(existing_user.get('rating') or 0)
                                except Exception:
                                    pass
                        
                        # 收集数据库写入数据
                        batch_db_data.append(data)

                        try:
                            now = time.time()
                            if now - last_ui_emit_ts >= 0.2:
                                last_ui_emit_ts = now
                                cur = processed + idx + 1
                                if cur > total:
                                    cur = total
                                self.progress_updated.emit(cur, total, f"正在导入数据库: {cur}/{total}")
                        except Exception:
                            pass
                        
                        t_process_end = time.time()
                        total_time = avg_exif_time + (t_process_end - t_process_start)
                        
                        current_idx = processed + idx + 1
                        try:
                            dt = t_process_end - t_process_start
                            if dt >= 1.0:
                                LogManager.instance().info(f"[ScanWorker] Slow file process {dt:.2f}s: {fpath}")
                        except Exception:
                            pass
                        
                    # 批量执行数据库写入
                    if batch_db_data:
                        # [Log] 准备写入数据库
                        try:
                            LogManager.instance().info(f"[ScanWorker] Saving batch of {len(batch_db_data)} to DB...")
                        except:
                            pass

                        # [Fix] 使用 save_results_batch_safe 替代 save_results_batch
                        # 该方法内部会处理 IntegrityError (UUID 冲突)，
                        # 遇到冲突时会自动为冲突的记录重新生成 UUID 并重试写入。
                        # 这能解决用户手动复制文件（DSC_0098 - 副本.NEF）导致 UUID 重复而无法入库的问题。
                        
                        # 找出哪些记录是新生成的 UUID（需要回写 Exif），哪些是读取到的 UUID
                        # 在重试逻辑中，如果重新生成了 UUID，也需要同步更新 pending_exif_updates
                        
                        # 这里我们采用一种简化的策略：
                        # 1. 尝试批量写入
                        # 2. 如果失败，则逐条写入
                        # 3. 逐条写入时如果遇到 UUID 冲突，则重新生成 UUID 并添加到 Exif 写入队列
                        
                        try:
                            t_db0 = time.time()
                            uuid_updates = db.save_results_batch(batch_db_data, table_name='bird_results')
                            try:
                                t_db1 = time.time()
                                if is_first_run or (t_db1 - t_db0) >= 1.0:
                                    LogManager.instance().warning(
                                        f"[PROFILE][ScanWorker] db_save_batch idx={i} rows={len(batch_db_data)} elapsed={t_db1 - t_db0:.2f}s uuid_updates={len(uuid_updates or {})}"
                                    )
                            except Exception:
                                pass
                            if can_print:
                                try:
                                    print(
                                        f"[PROFILE][ScanWorker] db_save_batch idx={i} rows={len(batch_db_data)} elapsed={time.time() - t_db0:.2f}s uuid_updates={len(uuid_updates or {})}"
                                    )
                                except Exception:
                                    pass
                            if (not disable_write) and isinstance(uuid_updates, dict) and uuid_updates:
                                for p_u, new_uuid in uuid_updates.items():
                                    try:
                                        found_task = False
                                        nk_u = self._normalize_path_key(p_u)
                                        for idx_t, (p_t, tags_t) in enumerate(self.pending_exif_updates):
                                            if self._normalize_path_key(p_t) == nk_u:
                                                tags_t[EXIF_TAG.Uuid.value] = str(new_uuid)
                                                found_task = True
                                                break
                                        if not found_task:
                                            self.pending_exif_updates.append((p_u, {EXIF_TAG.Uuid.value: str(new_uuid)}))
                                    except Exception:
                                        continue
                            # [Log] 写入成功
                            try:
                                LogManager.instance().info(f"[ScanWorker] Batch saved successfully in {time.time() - t_db0:.2f}s.")
                            except:
                                pass
                        except Exception as e:
                            # [Log] 批量写入失败
                            try:
                                LogManager.instance().warning(f"[ScanWorker] Batch save failed: {e}")
                            except:
                                pass
                            
                            # 批量写入失败，降级为逐条写入并处理冲突
                            for item in batch_db_data:
                                try:
                                    db.save_results(item, table_name='bird_results')
                                except Exception as e:
                                    # 检查是否是 UUID 冲突 (IntegrityError: UNIQUE constraint failed: bird_results.uuid)
                                    # SQLite 的错误信息可能包含 "UNIQUE constraint failed"
                                    if "UNIQUE" in str(e).upper() and "UUID" in str(e).upper():
                                        try:
                                            # 重新生成 UUID
                                            new_uuid = get_unique_id()
                                            item['uuid'] = new_uuid
                                            # 再次尝试写入
                                            db.save_results(item, table_name='bird_results')
                                            
                                            # 添加到 Exif 回写队列
                                            # 需要找到原始路径对应的 tags_to_write
                                            fpath = item['path']
                                            
                                            # 查找 pending_exif_updates 中是否已有该文件的任务
                                            # 如果有，更新 UUID；如果没有，添加新任务
                                            found_task = False
                                            for idx_t, (p_t, tags_t) in enumerate(self.pending_exif_updates):
                                                if p_t == fpath:
                                                    tags_t[EXIF_TAG.Uuid.value] = new_uuid
                                                    found_task = True
                                                    break
                                            if not found_task:
                                                self.pending_exif_updates.append((fpath, {EXIF_TAG.Uuid.value: new_uuid}))
                                                
                                            LogManager.instance().info(f"UUID 冲突已自动修复: {fpath} -> {new_uuid}")
                                        except Exception as e2:
                                            LogManager.instance().warning(f"单条写入重试失败: {item.get('path')} - {e2}")
                                    else:
                                        # 其他错误（如路径冲突），记录日志但继续
                                        LogManager.instance().warning(f"单条写入失败: {item.get('path')} - {e}")

                    # 如果开启了自动提交模式，则直接提交给 ExifHandleWorker
                    if self.auto_submit_exif:
                        if disable_write:
                            self.pending_exif_updates = []
                        else:
                            # 找出当前 batch 中新产生的 Exif 任务
                            # 这里简单处理：把所有 pending 的一次性提交并清空
                            current_pending = list(self.pending_exif_updates)
                            if current_pending:
                                ExifHandleWorker.get_instance().enqueue_update_tags(current_pending)
                                self.pending_exif_updates = []

                except Exception as e:
                    try:
                        LogManager.instance().warning(f"批量处理失败: {e}")
                    except Exception:
                        pass
                try:
                    t_batch1 = time.time()
                    if is_first_run or (t_batch1 - t_batch0) >= 3.0:
                        LogManager.instance().warning(
                            f"[PROFILE][ScanWorker] batch_total idx={i} size={len(batch)} elapsed={t_batch1 - t_batch0:.2f}s"
                        )
                except Exception:
                    pass
                if can_print:
                    try:
                        print(f"[PROFILE][ScanWorker] batch_total idx={i} size={len(batch)} elapsed={time.time() - t_batch0:.2f}s")
                    except Exception:
                        pass
                # [Fix] 显式更新循环变量 i
                i += len(batch)
                processed += len(batch)
                if processed > total:
                    processed = total
                self.progress_updated.emit(processed, total, f"正在导入数据库: {processed}/{total}")
                    
        except Exception as e:
            try:
                LogManager.instance().warning(f"ScanWorker 异常: {e}")
            except Exception:
                pass
            
        finally:
            if 'config_file' in locals() and config_file and os.path.exists(config_file):
                try:
                    os.remove(config_file)
                except:
                    pass
            
            # 强制提交剩余的 Exif 写入任务：
            # - 重建数据库/首次扫描时，要求确保 uuid 与 fast_id 一定落到原文件 Exif 中
            # - 即使未开启 auto_submit_exif，也要在任务结束前把待写入列表刷掉，避免“数据库有、Exif 没有”的不一致
            try:
                # 再次检查是否禁用了 EXIF 写入
                disable_write = False
                try:
                    val = SettingsManager().get("exif/disable_write", False)
                    if isinstance(val, str):
                        disable_write = val.lower() == 'true'
                    else:
                        disable_write = bool(val)
                except Exception:
                    pass

                if disable_write:
                    self.pending_exif_updates = []
                else:
                    pending = list(self.pending_exif_updates or [])
                    if pending:
                        ExifHandleWorker.get_instance().enqueue_update_tags(pending)
                    self.pending_exif_updates = []
            except Exception:
                pass
        
        self.scan_finished.emit()

    def stop(self):
        self.is_cancelled = True
