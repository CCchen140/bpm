import os
import re
import utils.file.file as file_util

class LibraryScanner:
    """图片库扫描器"""
    
    @staticmethod
    def scan(root_path, strict_mode=True, max_depth=None, exclude_dirs=None, exclude_regex: str = "", progress_callback=None, cancel_check=None):
        """
        扫描指定目录下的符合条件的文件
        :param root_path: 根目录
        :param strict_mode: 是否启用严格模式（目-科-属）
        :param max_depth: 最大扫描深度(相对根目录的目录层级)，None 表示不限制
        :return: 文件路径列表
        """
        valid_files = []
        valid_extensions = set(ext.lower() for ext in file_util.raw_exts + file_util.img_exts)
        
        # 规范化路径分隔符
        root_path = os.path.normpath(root_path)
        try:
            root_norm = os.path.normcase(os.path.normpath(str(root_path)))
        except Exception:
            root_norm = ""

        excl = []
        for p in (exclude_dirs or []):
            if not p:
                continue
            try:
                np = os.path.normcase(os.path.normpath(str(p)))
            except Exception:
                np = str(p)
            if np:
                excl.append(np)

        rx = None
        rx_str = str(exclude_regex or "").strip()
        if rx_str:
            try:
                rx = re.compile(rx_str)
            except Exception:
                rx = None

        def _path_matches_regex(p: str) -> bool:
            if not rx:
                return False
            try:
                s = str(p).replace("\\", "/")
            except Exception:
                return False
            try:
                return bool(rx.search(s))
            except Exception:
                return False

        def _is_excluded_dir(p_norm: str) -> bool:
            if not p_norm:
                return False

            # 默认排除系统回收站
            if "$recycle.bin" in p_norm.lower() or "system volume information" in p_norm.lower():
                return True

            for e in excl:
                if not e:
                    continue
                if p_norm == e:
                    return True
                try:
                    if p_norm.startswith(e + os.sep):
                        return True
                except Exception:
                    continue
            if _path_matches_regex(p_norm):
                return True
            return False

        visited_dirs = 0
        last_emit_ts = 0.0
        
        # [Fix] 使用 scandir 替代 os.walk 以获得更好的性能和控制
        # 自己实现递归遍历，避免 os.walk 在遇到特殊文件或超大目录时的不可控
        stack = [(root_path, 0)] # (path, depth)
        seen_dirs = set()
        try:
            if root_norm:
                seen_dirs.add(root_norm)
        except Exception:
            pass
        
        # [Log] Start scanning
        try:
            from utils.log_manager import LogManager
            LogManager.instance().debug(f"[LibraryScanner] Scanning root: {root_path}")
        except:
            pass
        
        while stack:
            # 检查取消
            if callable(cancel_check):
                try:
                    if bool(cancel_check()):
                        break
                except Exception:
                    pass

            current_dir, current_depth = stack.pop()
            
            try:
                # 规范化路径
                current_dir_norm = os.path.normcase(os.path.normpath(current_dir))
            except Exception:
                current_dir_norm = current_dir

            # 检查是否排除
            if _is_excluded_dir(current_dir_norm):
                continue
                
            # 更新进度
            visited_dirs += 1
            if callable(progress_callback):
                try:
                    now = float(__import__("time").time())
                    if now and (now - last_emit_ts) >= 0.1: # 保持 0.1s 快速响应
                        last_emit_ts = now
                        progress_callback(visited_dirs, len(valid_files), current_dir)
                except Exception:
                    pass

            # 检查深度
            if isinstance(max_depth, int) and max_depth >= 0 and current_depth >= max_depth:
                # 达到最大深度，不再添加子目录，但仍需处理当前目录的文件（如果需要的话，或者直接跳过）
                # 通常达到最大深度意味着不再扫描子目录，当前目录的文件是否扫描取决于定义
                # 这里假设 max_depth 是扫描文件的最大深度
                pass
            
            try:
                t0 = float(__import__("time").time())
            except Exception:
                t0 = 0.0

            subdirs = []
            files = []
            entry_count = 0

            try:
                with os.scandir(current_dir) as it:
                    for entry in it:
                        entry_count += 1
                        if entry_count % 500 == 0 and callable(progress_callback):
                            try:
                                now = float(__import__("time").time())
                                if now and (now - last_emit_ts) >= 0.1:
                                    last_emit_ts = now
                                    progress_callback(visited_dirs, len(valid_files), f"{current_dir} [entries {entry_count}]")
                            except Exception:
                                pass

                        try:
                            if entry.is_dir(follow_symlinks=False):
                                try:
                                    if entry.is_symlink():
                                        continue
                                except Exception:
                                    pass
                                subdirs.append(entry)
                                continue
                        except Exception:
                            pass

                        try:
                            name = entry.name
                            ext = os.path.splitext(name)[1].lower()
                            if ext not in valid_extensions:
                                continue
                        except Exception:
                            continue

                        try:
                            if entry.is_file(follow_symlinks=False):
                                files.append(entry)
                        except Exception:
                            continue
            except (OSError, PermissionError):
                continue
            except Exception:
                continue

            try:
                t1 = float(__import__("time").time())
            except Exception:
                t1 = 0.0
            try:
                if t0 and t1 and (t1 - t0) >= 2.0:
                    from utils.log_manager import LogManager
                    LogManager.instance().debug(f"[LibraryScanner] Slow dir list: {current_dir} entries={entry_count} files={len(files)} dirs={len(subdirs)} elapsed={t1-t0:.2f}s")
            except Exception:
                pass
            
            # 处理子目录（入栈）
            # 只有未达到最大深度时才加入子目录
            if not (isinstance(max_depth, int) and max_depth >= 0 and current_depth >= max_depth):
                # 倒序入栈，保证正序处理（虽然对扫描顺序没强制要求，但符合直觉）
                if len(subdirs) <= 2000:
                    try:
                        subdirs.sort(key=lambda e: e.name, reverse=True)
                    except Exception:
                        pass
                for d in subdirs:
                    try:
                        full_path = d.path
                        # 提前检查子目录排除，避免不必要的入栈
                        full_path_norm = os.path.normcase(os.path.normpath(full_path))
                        if not _is_excluded_dir(full_path_norm):
                            if full_path_norm in seen_dirs:
                                continue
                            seen_dirs.add(full_path_norm)
                            stack.append((full_path, current_depth + 1))
                    except Exception:
                        continue
            # [Fix] 如果 max_depth 是 None (不限)，则必须处理子目录
            # 上面的 if 条件: if not (isinstance(max_depth, int) ...)
            # 如果 max_depth 为 None，isinstance(None, int) 为 False，整个条件为 True，进入处理
            # 看起来逻辑是没问题的。
            # 但用户反馈首次进入不限模式卡住，且四层模式正常。
            # 四层模式下 max_depth=4，会进入上面的分支。
            # 不限模式下 max_depth=None，也会进入。
            
            # 唯一的区别是：不限模式下会扫描到很深层的目录。
            # 而首次进入时，如果 root_path 是磁盘根目录，可能会遇到一些奇怪的系统目录，即使我们有默认排除列表。
            # 比如 D:\$RECYCLE.BIN 虽然排除了，但 D:\System Volume Information 这种可能因为权限直接抛出 PermissionError 而在 scandir 时被捕获并 continue 了。
            
            # 让我们增加一个日志，记录被跳过的异常目录，以及当前正在扫描的深度
            if current_depth > 20 and current_depth % 10 == 0:
                # 深度过深时打印日志
                try:
                    from utils.log_manager import LogManager
                    LogManager.instance().debug(f"Deep scan: depth={current_depth}, dir={current_dir}")
                except:
                    pass

            # 处理文件
            file_batch_count = 0
            # 获取当前目录下的文件总数，用于显示进度
            total_files_in_dir = len(files)
            
            for f in files:
                file_batch_count += 1
                if file_batch_count % 200 == 0:
                     if callable(cancel_check):
                        try:
                            if bool(cancel_check()):
                                return valid_files
                        except Exception:
                            pass
                     if callable(progress_callback):
                        try:
                            now = float(__import__("time").time())
                            if now and (now - last_emit_ts) >= 0.1:
                                last_emit_ts = now
                                # 在 current_dir 后附加文件进度信息，hack 传递给 callback
                                progress_info = f"{current_dir} [{file_batch_count}/{total_files_in_dir}]"
                                progress_callback(visited_dirs, len(valid_files), progress_info)
                        except Exception:
                            pass

                try:
                    name = f.name
                    ext = os.path.splitext(name)[1].lower()
                    if ext in valid_extensions:
                        fp = f.path
                        fp_norm = os.path.normcase(os.path.normpath(fp))
                        if not _path_matches_regex(fp_norm):
                            valid_files.append(fp)
                except Exception:
                    continue

        return valid_files
