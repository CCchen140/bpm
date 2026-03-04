import os
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
                             QMenu, QApplication, QHeaderView, QHBoxLayout, QPushButton)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImageReader
from utils.sql.data_base import BirdLibraryDB
from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG
from ui.utils.geo_manager import GeoInfoManager
from ui.utils.color_manager import ColorManager
from ui.utils.icon_loader import qta

class ExifLoaderThread(QThread):
    """后台线程加载EXIF信息，避免阻塞UI"""
    exif_ready = pyqtSignal(int, str, dict)  # request_id, path, exif_data

    def __init__(self, request_id: int, image_path: str, parent=None):
        super().__init__(parent)
        self.request_id = request_id
        self.image_path = image_path

    def run(self):
        exif_data = {}
        try:
            if not self.image_path or not os.path.exists(self.image_path):
                self.exif_ready.emit(self.request_id, self.image_path or "", exif_data)
                return

            from utils.exif.exif_utils import run_exiftool, get_exiftool_path
            import json
            tool_path = get_exiftool_path()
            cmd = [tool_path, "-j", self.image_path]
            result = run_exiftool(cmd, timeout=5)
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if isinstance(data, list) and data:
                    exif_data = data[0]
        except Exception as e:
            print(f"[ERROR] ExifLoaderThread failed: {e}, path={self.image_path}")

        if not self.isInterruptionRequested():
            self.exif_ready.emit(self.request_id, self.image_path or "", exif_data)


class FocusDistanceLoaderThread(QThread):
    focus_distance_ready = pyqtSignal(int, str, str)  # request_id, path, focus_distance

    def __init__(self, request_id: int, image_path: str, parent=None):
        super().__init__(parent)
        self.request_id = request_id
        self.image_path = image_path

    def run(self):
        focus_disp = "-"

        def _strip_suffix_unit(s: str, unit: str):
            if not s:
                return s
            t = str(s).strip()
            u = str(unit).strip().lower()
            if not u:
                return t
            low = t.lower()
            if low.endswith(u):
                t = t[: len(t) - len(unit)].strip()
            return t

        def _meta_get(meta: dict, tag_name: str):
            if not meta or not tag_name:
                return None
            try:
                if tag_name in meta:
                    return meta.get(tag_name)
            except Exception:
                pass
            try:
                tag_lower = str(tag_name).lower()
            except Exception:
                tag_lower = ""
            try:
                short_key = str(tag_name).split(":")[-1]
                short_lower = short_key.lower()
            except Exception:
                short_lower = ""
            try:
                for k, v in meta.items():
                    try:
                        key_lower = str(k).lower()
                    except Exception:
                        continue
                    if key_lower == tag_lower or key_lower == short_lower or key_lower.endswith(f":{short_lower}"):
                        return v
            except Exception:
                pass
            return None

        try:
            if not self.image_path or not os.path.exists(self.image_path):
                self.focus_distance_ready.emit(self.request_id, self.image_path or "", "-")
                return

            meta = ExifHandleWorker.get_instance().get_metadata(self.image_path)
            if self.isInterruptionRequested():
                return

            v = _meta_get(meta, EXIF_TAG.FocusDistance.value) if isinstance(meta, dict) else None
            if v is not None and str(v).strip():
                focus_disp = str(v).strip()

            if focus_disp and focus_disp != "-":
                focus_disp = _strip_suffix_unit(str(focus_disp).replace(" ", ""), "m") or "-"
            if not focus_disp or not str(focus_disp).strip():
                focus_disp = "-"
        except Exception:
            focus_disp = "-"

        if not self.isInterruptionRequested():
            self.focus_distance_ready.emit(self.request_id, self.image_path or "", focus_disp)

class InfoPanel(QWidget):
    vertical_toggle_requested = pyqtSignal()

    def __init__(self, parent=None, show_extended_info=True):
        super().__init__(parent)
        self.show_extended_info = show_extended_info
        self.db = BirdLibraryDB()
        self._focus_distance_request_id = 0
        self._current_image_path = None
        self._focus_distance_threads = set()
        self._exif_loader_threads = set()  # 管理EXIF加载线程
        self._vert_collapsed = False
        self.init_ui()
        ColorManager.instance().register_listener(self._apply_theme_styles)
        
    def init_ui(self):
        self.setMinimumHeight(34)
        self.setMaximumHeight(16777215)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header_widget = QWidget()
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(6)

        self.vert_toggle_btn = QPushButton()
        self.vert_toggle_btn.setFixedSize(24, 24)
        self.vert_toggle_btn.setToolTip("收起信息")
        self.vert_toggle_btn.clicked.connect(lambda: self.vertical_toggle_requested.emit())
        header_layout.addWidget(self.vert_toggle_btn)
        header_layout.addStretch(1)

        layout.addWidget(self.header_widget)
        
        # 使用 QTreeWidget 实现可展开折叠的信息面板
        self.info_tree = QTreeWidget()
        self.info_tree.setHeaderHidden(True)
        self.info_tree.setColumnCount(2)
        self.info_tree.setIndentation(16)  # 子项缩进
        self.info_tree.setRootIsDecorated(False)  # 顶级项不显示默认装饰
        self.info_tree.setAnimated(True)
        self.info_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.info_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_tree.customContextMenuRequested.connect(self.on_info_tree_context_menu)
        self.info_tree.itemExpanded.connect(self._on_info_item_expanded)
        self.info_tree.itemCollapsed.connect(self._on_info_item_collapsed)
        
        header = self.info_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.info_tree.setWordWrap(False)
        self.info_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.info_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 初始化信息分组
        self._init_info_tree()
        layout.addWidget(self.info_tree)
        self._apply_theme_styles()

    def set_vertical_collapsed(self, collapsed: bool):
        self._vert_collapsed = bool(collapsed)
        try:
            self.info_tree.setVisible(not bool(collapsed))
        except Exception:
            pass
        try:
            self._apply_theme_styles()
        except Exception:
            pass

    def _adjust_key_column_width(self):
        try:
            self.info_tree.resizeColumnToContents(0)
        except Exception:
            return
        try:
            w = int(self.info_tree.columnWidth(0))
        except Exception:
            return
        w = max(90, min(260, w + 8))
        try:
            self.info_tree.setColumnWidth(0, int(w))
        except Exception:
            pass

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.primary")
        border = cm.get("popup.border.primary")
        text_color = cm.get("theme.text.dark")
        icon_color = cm.get("theme.text.dark")
        primary = cm.get("theme.primary")
        hover_bg = cm.get("theme.background.light")
        selected_bg = cm.get("theme.primary")
        selected_text = cm.get("theme.text.light")
        scrollbar_bg = panel_bg
        scrollbar_handle = cm.get("popup.border.primary")
        scrollbar_handle_hover = cm.get("theme.primary")
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {panel_bg};
                border-top: 1px solid {border};
            }}
        """)
        try:
            self.header_widget.setStyleSheet("background: transparent; border: none;")
        except Exception:
            pass
        try:
            self.vert_toggle_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    padding: 2px;
                }}
                QPushButton:hover {{
                    background-color: {primary};
                    border-radius: 3px;
                }}
            """)
        except Exception:
            pass
        try:
            if bool(getattr(self, "_vert_collapsed", False)):
                self.vert_toggle_btn.setIcon(qta.icon("mdi6.chevron-up", color=icon_color, options=[{"scale_factor": 1.1}]))
                self.vert_toggle_btn.setToolTip("展开信息")
            else:
                self.vert_toggle_btn.setIcon(qta.icon("mdi6.chevron-down", color=icon_color, options=[{"scale_factor": 1.1}]))
                self.vert_toggle_btn.setToolTip("收起信息")
        except Exception:
            pass
        self.info_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {panel_bg};
                border: none;
                font-size: 12px;
                color: {text_color};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 4px 4px;
                border: none;
            }}
            QTreeWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QTreeWidget::item:selected {{
                background-color: {selected_bg};
                color: {selected_text};
            }}
            QTreeWidget::branch {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {scrollbar_handle};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {scrollbar_handle_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                background-color: {scrollbar_bg};
                height: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {scrollbar_handle};
                min-width: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {scrollbar_handle_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """)

    def _init_info_tree(self):
        """初始化信息树结构"""
        self.info_tree.clear()
        
        # 创建分组的辅助函数
        def create_group(title, expanded=True):
            item = QTreeWidgetItem(self.info_tree)
            # 展开时显示 -，折叠时显示 +
            prefix = "- " if expanded else "+ "
            item.setText(0, prefix + title)
            item.setExpanded(expanded)
            # 设置分组标题样式（加粗）
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            return item
            
        # 基本信息分组
        self.info_basic = create_group("基本信息", True)
        self.info_basic_items = {
            'filename': QTreeWidgetItem(self.info_basic, ["    文件名", "-"]),
            'path': QTreeWidgetItem(self.info_basic, ["    路径", "-"]),
            'size': QTreeWidgetItem(self.info_basic, ["    大小", "-"]),
            'type': QTreeWidgetItem(self.info_basic, ["    类型", "-"]),
        }
        
        # 图片信息分组
        self.info_image = create_group("图片信息", True)
        self.info_image_items = {
            'dimensions': QTreeWidgetItem(self.info_image, ["    尺寸", "-"]),
            'resolution': QTreeWidgetItem(self.info_image, ["    分辨率", "-"]),
            'color_mode': QTreeWidgetItem(self.info_image, ["    颜色模式", "-"]),
        }
        
        # 时间信息分组
        self.info_time = create_group("时间信息", True)
        self.info_time_items = {
            'shot_time': QTreeWidgetItem(self.info_time, ["    拍摄时间", "-"]),
            'import_time': QTreeWidgetItem(self.info_time, ["    导入时间", "-"]),
            'create_time': QTreeWidgetItem(self.info_time, ["    创建时间", "-"]),
            'modify_time': QTreeWidgetItem(self.info_time, ["    修改时间", "-"]),
            'access_time': QTreeWidgetItem(self.info_time, ["    访问时间", "-"]),
        }
        
        # EXIF 信息分组
        self.info_exif = create_group("EXIF 信息", True)  # 默认折叠
        self.info_exif_items = {
            'camera': QTreeWidgetItem(self.info_exif, ["    相机", "-"]),
            'lens': QTreeWidgetItem(self.info_exif, ["    镜头", "-"]),
            'aperture': QTreeWidgetItem(self.info_exif, ["    光圈", "-"]),
            'shutter': QTreeWidgetItem(self.info_exif, ["    快门", "-"]),
            'iso': QTreeWidgetItem(self.info_exif, ["    ISO", "-"]),
            'focal_length': QTreeWidgetItem(self.info_exif, ["    焦距", "-"]),
            'focus_distance': QTreeWidgetItem(self.info_exif, ["    对焦距离", "-"]),
            'gps_lat': QTreeWidgetItem(self.info_exif, ["    纬度", "-"]),
            'gps_lng': QTreeWidgetItem(self.info_exif, ["    经度", "-"]),
            'location': QTreeWidgetItem(self.info_exif, ["    拍摄地址", "-"]),
        }

        if self.show_extended_info:
            self.info_focus = create_group("对焦分类", True)
            self.info_focus_items = {
                'status': QTreeWidgetItem(self.info_focus, ["    分类", "-"]),
                'reason': QTreeWidgetItem(self.info_focus, ["    分类原因", "-"]),
                'score': QTreeWidgetItem(self.info_focus, ["    得分", "-"]),
                'norm_score': QTreeWidgetItem(self.info_focus, ["    标准分", "-"]),
                'area_ratio': QTreeWidgetItem(self.info_focus, ["    鸟占比", "-"]),
            }
            try:
                self.info_focus.setHidden(True)
            except Exception:
                pass
    
            self.info_taxonomy = create_group("分类信息", True)
            self.info_taxonomy_items = {
                'order': QTreeWidgetItem(self.info_taxonomy, ["    目", "-"]),
                'family': QTreeWidgetItem(self.info_taxonomy, ["    科", "-"]),
                'genus': QTreeWidgetItem(self.info_taxonomy, ["    属", "-"]),
                'species': QTreeWidgetItem(self.info_taxonomy, ["    种", "-"]),
            }
    
            # 备注信息分组
            self.info_remark = create_group("备注信息", True)
            self.info_remark_items = {
                'description': QTreeWidgetItem(self.info_remark, ["    内容", "-"]),
                'tags': QTreeWidgetItem(self.info_remark, ["    标签", "-"]),
            }
        else:
            self.info_focus = None
            self.info_taxonomy = None
            self.info_remark = None
            self.info_focus_items = {}
            self.info_taxonomy_items = {}
            self.info_remark_items = {}
        
        # 调整列宽以适应内容
        self._adjust_key_column_width()

    def set_extended_info_visible(self, visible):
        """设置是否显示扩展信息（对焦、分类、备注等）"""
        if self.show_extended_info == visible:
            return
            
        self.show_extended_info = visible
        # 重新初始化树结构
        self._init_info_tree()
        
        # 如果有当前图片，刷新信息
        if self._current_image_path:
            self.update_info(self._current_image_path)

    def _on_info_item_expanded(self, item):
        """信息树项展开时更新图标"""
        if item.childCount() > 0:
            text = item.text(0)
            if text.startswith("+ "):
                item.setText(0, "- " + text[2:])

    def _on_info_item_collapsed(self, item):
        """信息树项折叠时更新图标"""
        if item.childCount() > 0:
            text = item.text(0)
            if text.startswith("- "):
                item.setText(0, "+ " + text[2:])

    def _get_gps_coord(self, tags, key):
        # key is 'Latitude' or 'Longitude'
        try:
            tag_name = f'GPS GPS{key}'
            ref_name = f'GPS GPS{key}Ref'
            if tag_name not in tags:
                return None
            
            values = tags[tag_name].values
            if not values or len(values) < 3:
                return None
                
            d = float(values[0])
            m = float(values[1])
            s = float(values[2])
            val = d + m / 60.0 + s / 3600.0
            
            if ref_name in tags:
                ref = str(tags[ref_name].values).upper()
                if ref == 'S' or ref == 'W':
                    val = -val
            return val
        except:
            return None

    def _on_exif_loaded(self, request_id, image_path, exif_data):
        """EXIF加载完成后的回调（在主线程执行）"""
        # 检查是否是当前请求
        if request_id != self._focus_distance_request_id:
            return
        
        def _get_exif(keys, default="-"):
            for k in keys:
                if k in exif_data and exif_data[k] is not None:
                    v = str(exif_data[k]).strip()
                    if v and v != "-":
                        return v
            return default
        
        def _strip_suffix_unit(s: str, unit: str):
            if not s:
                return s
            t = str(s).strip()
            u = str(unit).strip().lower()
            if not u:
                return t
            low = t.lower()
            if low.endswith(u):
                t = t[: len(t) - len(unit)].strip()
            return t
        
        # 更新尺寸和分辨率
        try:
            dimensions_disp = "-"
            img_size = _get_exif(["ImageSize"])
            if img_size and "x" in img_size.lower():
                dimensions_disp = img_size
            else:
                img_width = _get_exif(["ImageWidth", "ExifImageWidth"])
                img_height = _get_exif(["ImageHeight", "ExifImageLength"])
                if img_width != "-" and img_height != "-":
                    dimensions_disp = f"{img_width} × {img_height}"
            if dimensions_disp != "-":
                self.info_image_items['dimensions'].setText(1, dimensions_disp)
        except Exception:
            pass
        
        # 更新分辨率
        try:
            x_res = _get_exif(["XResolution"])
            if x_res != "-":
                self.info_image_items['resolution'].setText(1, f"{x_res} DPI")
        except Exception:
            pass
        
        # 更新EXIF信息
        try:
            camera_disp = _get_exif(["Model"])
            lens_disp = _get_exif(["LensModel", "Lens"])
            iso_disp = _get_exif(["ISO", "ISOSpeedRatings", "PhotographicSensitivity"])
            
            fnumber = _get_exif(["FNumber", "Aperture"])
            aperture_disp = "-"
            if fnumber != "-":
                try:
                    f_val = float(fnumber)
                    aperture_disp = f"f/{f_val}" if f_val > 0 else "-"
                except Exception:
                    aperture_disp = fnumber if fnumber.startswith("f/") else f"f/{fnumber}"
            
            shutter_disp = _get_exif(["ExposureTime", "ShutterSpeed"])
            if shutter_disp != "-":
                shutter_disp = shutter_disp.replace(" sec", "").replace("sec", "").strip() or "-"
            
            focal_disp = _get_exif(["FocalLength"])
            if focal_disp != "-":
                focal_disp = _strip_suffix_unit(str(focal_disp).replace(" ", ""), "mm") or "-"
            
            # 对焦距离
            focus_disp = _get_exif([
                "FocusDistance", "SubjectDistance",
                "FocusDistance2",
                "FocusDistanceUpper", "FocusDistanceLower",
            ])
            if focus_disp != "-":
                focus_disp = _strip_suffix_unit(str(focus_disp).replace(" ", ""), "m") or "-"
            
            self.info_exif_items['camera'].setText(1, camera_disp)
            self.info_exif_items['lens'].setText(1, lens_disp)
            self.info_exif_items['aperture'].setText(1, aperture_disp)
            self.info_exif_items['shutter'].setText(1, shutter_disp)
            self.info_exif_items['iso'].setText(1, iso_disp)
            self.info_exif_items['focal_length'].setText(1, focal_disp)
            self.info_exif_items['focus_distance'].setText(1, focus_disp)
        except Exception as e:
            print(f"[ERROR] info_panel update EXIF UI failed: {e}")
        
        # 更新GPS
        try:
            lat_raw = _get_exif(["GPSLatitude"])
            lng_raw = _get_exif(["GPSLongitude"])
            if lat_raw != "-":
                try:
                    lat_val = float(lat_raw)
                    self.info_exif_items['gps_lat'].setText(1, GeoInfoManager.instance().format_coordinate(lat_val))
                except Exception:
                    self.info_exif_items['gps_lat'].setText(1, "-")
            if lng_raw != "-":
                try:
                    lng_val = float(lng_raw)
                    self.info_exif_items['gps_lng'].setText(1, GeoInfoManager.instance().format_coordinate(lng_val))
                except Exception:
                    self.info_exif_items['gps_lng'].setText(1, "-")
        except Exception as e:
            print(f"[ERROR] info_panel update GPS UI failed: {e}")
        
        # 更新拍摄时间
        try:
            exif_time_raw = _get_exif(["DateTimeOriginal", "CreateDate", "DateTime"])
            if exif_time_raw != "-":
                s = str(exif_time_raw).strip()
                try:
                    dt_obj = datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
                    dt_disp = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    dt_disp = s.replace(":", "-", 2) if len(s) >= 10 and s[4] == ":" and s[7] == ":" else s
                if dt_disp and dt_disp.strip():
                    self.info_time_items['shot_time'].setText(1, dt_disp.strip())
        except Exception as e:
            print(f"[ERROR] info_panel update time UI failed: {e}")
    
    def update_info(self, image_path, context=None):
        """更新信息树内容（优化版：EXIF读取在后台线程）"""
        import time
        
        if not image_path:
            self._clear_info()
            return
        
        # 路径处理
        try:
            p = str(image_path).replace("\r", "").strip()
            if "路径:" in p:
                p = p.split("路径:")[-1].strip()
            if "原图片的路径" in p:
                p = p.split("原图片的路径")[-1].strip()
            low = p.lower()
            if low.startswith("file:///"):
                p = p[8:]
                if len(p) >= 3 and p[0] == "/" and p[2] == ":":
                    p = p[1:]
            elif low.startswith("file://"):
                p = p[7:]
            p = p.strip().strip('"').strip("'").strip()
            p = os.path.normpath(p)
        except Exception:
            p = image_path
        image_path = p or image_path
        
        self._current_image_path = image_path
        self._focus_distance_request_id += 1
        request_id = self._focus_distance_request_id
        
        # 取消之前的EXIF加载线程
        try:
            for t in list(self._exif_loader_threads):
                if t and t.isRunning():
                    t.requestInterruption()
        except Exception:
            pass

        focus_distance_value = "-"
        description_value = "-"
        shot_time_value = "-"
        import_time_value = "-"
        location_value = "-"
        tags_value = "-"
        score_value = "-"
        norm_score_value = "-"
        area_ratio_value = "-"
        order_value = "-"
        family_value = "-"
        genus_value = "-"
        species_value = "-"
        record_area_ratio_raw = None
        t0 = time.time()
        try:
            record = self.db.get_result_by_path(image_path, table_name="bird_results")
            if not record:
                record = self.db.get_result_by_path(image_path, table_name="import_cache")
            if record:
                v = record.get("focus_distance")
                if v is not None and str(v).strip():
                    focus_distance_value = str(v).strip()
                
                d = record.get("description")
                if d is not None and str(d).strip():
                    description_value = str(d).strip()

                st = record.get("shot_time")
                if st is not None and str(st).strip():
                    shot_time_value = str(st).strip()

                it = record.get("imported_at")
                if it is not None and str(it).strip():
                    import_time_value = str(it).strip()
                elif record.get("created_at") is not None and str(record.get("created_at")).strip():
                    import_time_value = str(record.get("created_at")).strip()
                    
                loc = record.get("location")
                if loc is not None and str(loc).strip():
                    location_value = str(loc).strip()

                t = record.get("tags")
                if t is not None and str(t).strip():
                    tags_value = str(t).strip()
                try:
                    o = record.get("order_cls")
                    if o is not None and str(o).strip():
                        order_value = str(o).strip()
                except Exception:
                    pass
                try:
                    f = record.get("family_cls")
                    if f is not None and str(f).strip():
                        family_value = str(f).strip()
                except Exception:
                    pass
                try:
                    g = record.get("genus_cls")
                    if g is not None and str(g).strip():
                        genus_value = str(g).strip()
                except Exception:
                    pass
                try:
                    s = record.get("species_cls")
                    if s is not None and str(s).strip():
                        species_value = str(s).strip()
                except Exception:
                    pass
                try:
                    v = record.get("score")
                    if v is not None and str(v).strip():
                        score_value = f"{float(v):.4f}"
                except Exception:
                    score_value = "-"
                try:
                    v = record.get("norm_score")
                    if v is not None and str(v).strip():
                        norm_score_value = f"{float(v):.4f}"
                except Exception:
                    norm_score_value = "-"
                try:
                    v = record.get("area_ratio")
                    if v is not None and str(v).strip():
                        r = float(v)
                        record_area_ratio_raw = float(r)
                        if 0 <= r <= 1.5:
                            pct = max(0.0, min(1.0, r)) * 100.0
                            if 0.0 < pct < 0.01:
                                area_ratio_value = "<0.01%"
                            else:
                                area_ratio_value = f"{pct:.2f}%"
                        else:
                            area_ratio_value = f"{r:.2f}%"
                except Exception:
                    area_ratio_value = "-"
        except Exception:
            pass

        focus_status = ""
        focus_reason = ""
        ctx_score = None
        ctx_norm_score = None
        ctx_area_ratio = None
        try:
            if isinstance(context, dict):
                focus_status = str(context.get("focus_status") or "")
                focus_reason = str(context.get("focus_reason") or "")
                ctx_score = context.get("score")
                ctx_norm_score = context.get("norm_score")
                ctx_area_ratio = context.get("area_ratio")
        except Exception:
            focus_status = ""
            focus_reason = ""
            ctx_score = None
            ctx_norm_score = None
            ctx_area_ratio = None
        if score_value == "-" and ctx_score not in (None, ""):
            try:
                score_value = f"{float(ctx_score):.4f}"
            except Exception:
                pass
        if norm_score_value == "-" and ctx_norm_score not in (None, ""):
            try:
                norm_score_value = f"{float(ctx_norm_score):.4f}"
            except Exception:
                pass
        if area_ratio_value == "-" and ctx_area_ratio not in (None, ""):
            try:
                r = float(ctx_area_ratio)
                if 0 <= r <= 1.5:
                    pct = max(0.0, min(1.0, r)) * 100.0
                    if 0.0 < pct < 0.01:
                        area_ratio_value = "<0.01%"
                    else:
                        area_ratio_value = f"{pct:.2f}%"
                else:
                    area_ratio_value = f"{r:.2f}%"
            except Exception:
                pass
        elif ctx_area_ratio not in (None, ""):
            try:
                r_ctx = float(ctx_area_ratio)
            except Exception:
                r_ctx = None
            try:
                r_rec = float(record_area_ratio_raw) if record_area_ratio_raw is not None else None
            except Exception:
                r_rec = None
            if r_ctx is not None and r_ctx > 0 and (r_rec is None or r_rec <= 0):
                try:
                    if 0 <= r_ctx <= 1.5:
                        pct = max(0.0, min(1.0, r_ctx)) * 100.0
                        if 0.0 < pct < 0.01:
                            area_ratio_value = "<0.01%"
                        else:
                            area_ratio_value = f"{pct:.2f}%"
                    else:
                        area_ratio_value = f"{r_ctx:.2f}%"
                except Exception:
                    pass
        # 仅在扩展信息模式下更新对焦信息
        if getattr(self, 'show_extended_info', False):
            try:
                if self.info_focus_items:
                    if 'score' in self.info_focus_items:
                        self.info_focus_items['score'].setText(1, score_value)
                    if 'norm_score' in self.info_focus_items:
                        self.info_focus_items['norm_score'].setText(1, norm_score_value)
                    if 'area_ratio' in self.info_focus_items:
                        self.info_focus_items['area_ratio'].setText(1, area_ratio_value)
            except Exception as e:
                print(f"[ERROR] info_panel set focus scores failed: {e}")
            try:
                if self.info_focus_items and self.info_focus:
                    show_focus = bool(focus_status or focus_reason or (score_value != "-") or (norm_score_value != "-") or (area_ratio_value != "-"))
                    if show_focus:
                        if 'status' in self.info_focus_items:
                            self.info_focus_items['status'].setText(1, focus_status or "-")
                        if 'reason' in self.info_focus_items:
                            self.info_focus_items['reason'].setText(1, focus_reason or "-")
                            try:
                                self.info_focus_items['reason'].setToolTip(1, focus_reason or "")
                            except Exception:
                                pass
                        self.info_focus.setHidden(False)
                    else:
                        if 'status' in self.info_focus_items:
                            self.info_focus_items['status'].setText(1, "-")
                        if 'reason' in self.info_focus_items:
                            self.info_focus_items['reason'].setText(1, "-")
                        self.info_focus.setHidden(True)
            except Exception as e:
                print(f"[ERROR] info_panel set focus status failed: {e}")
            
        # 仅在扩展信息模式下更新这些字段
        if getattr(self, 'show_extended_info', False):
            try:
                if 'description' in self.info_remark_items:
                    self.info_remark_items['description'].setText(1, description_value)
            except Exception as e:
                print(f"[ERROR] info_panel set description failed: {e}")
            try:
                if 'tags' in self.info_remark_items:
                    self.info_remark_items['tags'].setToolTip(1, tags_value)
            except Exception as e:
                print(f"[ERROR] info_panel set tags tooltip failed: {e}")
            try:
                if self.info_taxonomy_items:
                    if 'order' in self.info_taxonomy_items:
                        self.info_taxonomy_items['order'].setText(1, order_value)
                    if 'family' in self.info_taxonomy_items:
                        self.info_taxonomy_items['family'].setText(1, family_value)
                    if 'genus' in self.info_taxonomy_items:
                        self.info_taxonomy_items['genus'].setText(1, genus_value)
                    if 'species' in self.info_taxonomy_items:
                        self.info_taxonomy_items['species'].setText(1, species_value)
            except Exception as e:
                print(f"[ERROR] info_panel set taxonomy failed: {e}")
            
        # 基本信息
        try:
            filename = os.path.basename(image_path) if image_path else "-"
        except Exception:
            filename = "-"
        try:
            self.info_basic_items['filename'].setText(1, filename)
        except Exception as e:
            print(f"[ERROR] info_panel set filename failed: {e}")
        try:
            self.info_basic_items['path'].setText(1, image_path or "-")
        except Exception as e:
            print(f"[ERROR] info_panel set path failed: {e}")
        
        # 文件大小
        try:
            if image_path and os.path.exists(image_path):
                file_size = os.path.getsize(image_path)
                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.2f} MB"
                self.info_basic_items['size'].setText(1, size_str)
            else:
                self.info_basic_items['size'].setText(1, "-")
        except Exception as e:
            print(f"[ERROR] info_panel get file size failed: {e}, path={image_path}")
            self.info_basic_items['size'].setText(1, "-")
        
        # 文件类型
        try:
            ext = os.path.splitext(filename)[1].upper()
            self.info_basic_items['type'].setText(1, ext[1:] if ext else "-")
        except Exception as e:
            print(f"[ERROR] info_panel get file ext failed: {e}")
            self.info_basic_items['type'].setText(1, "-")
        
        # 图片信息 - 先显示默认值，后台线程加载EXIF后更新
        self.info_image_items['dimensions'].setText(1, "-")
        self.info_image_items['resolution'].setText(1, "72 DPI")
        try:
            self.info_image_items['color_mode'].setText(1, "RGB")
        except Exception:
            pass
        
        # 时间信息
        try:
            if image_path and os.path.exists(image_path):
                create_time = datetime.fromtimestamp(os.path.getctime(image_path))
                modify_time = datetime.fromtimestamp(os.path.getmtime(image_path))
                access_time = datetime.fromtimestamp(os.path.getatime(image_path))
                
                if shot_time_value == "-" or not str(shot_time_value).strip():
                    shot_time_value = create_time.strftime('%Y-%m-%d %H:%M:%S')
                self.info_time_items['shot_time'].setText(1, str(shot_time_value))
                self.info_time_items['import_time'].setText(1, str(import_time_value or "-"))
                self.info_time_items['create_time'].setText(1, create_time.strftime('%Y-%m-%d %H:%M:%S'))
                self.info_time_items['modify_time'].setText(1, modify_time.strftime('%Y-%m-%d %H:%M:%S'))
                self.info_time_items['access_time'].setText(1, access_time.strftime('%Y-%m-%d %H:%M:%S'))
            else:
                self.info_time_items['shot_time'].setText(1, str(shot_time_value) if shot_time_value != "-" else "-")
                self.info_time_items['import_time'].setText(1, str(import_time_value or "-"))
                self.info_time_items['create_time'].setText(1, "-")
                self.info_time_items['modify_time'].setText(1, "-")
                self.info_time_items['access_time'].setText(1, "-")
        except Exception as e:
            print(f"[ERROR] info_panel get file time failed: {e}, path={image_path}")
            self.info_time_items['shot_time'].setText(1, str(shot_time_value) if shot_time_value != "-" else "-")
            self.info_time_items['import_time'].setText(1, str(import_time_value or "-"))
            self.info_time_items['create_time'].setText(1, "-")
            self.info_time_items['modify_time'].setText(1, "-")
            self.info_time_items['access_time'].setText(1, "-")
        
        # EXIF 信息 - 先显示默认值
        for key in self.info_exif_items:
            self.info_exif_items[key].setText(1, "-")
        
        # 设置位置和标签
        try:
            self.info_exif_items['location'].setText(1, location_value)
        except Exception:
            pass
        
        if getattr(self, 'show_extended_info', False):
            try:
                if 'tags' in self.info_remark_items:
                    self.info_remark_items['tags'].setText(1, tags_value)
            except Exception:
                pass
        
        # 启动后台线程加载EXIF信息
        try:
            thread = ExifLoaderThread(request_id, image_path, parent=self)
            self._exif_loader_threads.add(thread)
            thread.finished.connect(lambda t=thread: self._exif_loader_threads.discard(t))
            thread.finished.connect(thread.deleteLater)
            thread.exif_ready.connect(self._on_exif_loaded)
            thread.start()
        except Exception as e:
            print(f"[ERROR] info_panel start ExifLoaderThread failed: {e}")
        self._adjust_key_column_width()
        try:
            self.info_tree.doItemsLayout()
            self.info_tree.viewport().update()
        except Exception:
            pass

    def update_folder_info(self, folder_name, stats):
        """更新文件夹统计信息"""
        self._clear_info()
        self.info_basic_items['filename'].setText(1, folder_name)
        self.info_basic_items['path'].setText(1, "统计信息")
        
        if stats:
            self.info_basic_items['size'].setText(0, "图片总数")
            self.info_basic_items['size'].setText(1, str(stats.get('image_count', 0)))
            self.info_basic_items['type'].setText(0, "物种总数")
            self.info_basic_items['type'].setText(1, str(stats.get('species_count', 0)))
        else:
            self.info_basic_items['size'].setText(1, "-")
            self.info_basic_items['type'].setText(1, "-")
        self._adjust_key_column_width()

    def _clear_info(self):
        """清空信息"""
        try:
            self._current_image_path = None
            self._focus_distance_request_id += 1
            for t in list(getattr(self, "_focus_distance_threads", [])):
                if t and t.isRunning():
                    t.requestInterruption()
        except Exception:
            pass
        # 恢复默认标题
        self.info_basic_items['size'].setText(0, "文件大小")
        self.info_basic_items['type'].setText(0, "文件类型")
        
        for group in [self.info_basic_items, self.info_image_items, self.info_time_items, self.info_exif_items]:
            for key in group:
                group[key].setText(1, "-")
        try:
            if hasattr(self, "info_focus_items"):
                for key in self.info_focus_items:
                    self.info_focus_items[key].setText(1, "-")
            if hasattr(self, "info_focus"):
                self.info_focus.setHidden(True)
        except Exception:
            pass
        self._adjust_key_column_width()

    def _on_focus_distance_ready(self, request_id: int, image_path: str, focus_distance: str):
        try:
            if request_id != self._focus_distance_request_id:
                return
            if not image_path or image_path != self._current_image_path:
                return
            if not focus_distance or str(focus_distance).strip() in ("", "-"):
                return
            self.info_exif_items['focus_distance'].setText(1, str(focus_distance).strip())
        except Exception:
            pass

    def on_info_tree_context_menu(self, position):
        """信息树右键菜单"""
        item = self.info_tree.itemAt(position)
        if not item:
            return
            
        menu = QMenu(self)
        cm = ColorManager.instance()
        menu_bg = cm.get("theme.background.light")
        menu_border = cm.get("popup.border.primary")
        menu_text = cm.get("theme.text.dark")
        menu_hover = cm.get("theme.background.dark")
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {menu_bg};
                border: 1px solid {menu_border};
                padding: 2px;
            }}
            QMenu::item {{
                padding: 4px 20px 4px 30px;
                border: none;
                color: {menu_text};
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
                color: {menu_text};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {menu_border};
                margin: 2px 4px;
            }}
        """)
        
        # 复制当前行
        copy_row_action = menu.addAction("复制此行")
        copy_row_action.triggered.connect(lambda: self._copy_info_row(item))
        
        # 复制分组
        if item.childCount() > 0:
            # 是分组标题
            copy_group_action = menu.addAction("复制此分组")
            copy_group_action.triggered.connect(lambda: self._copy_info_group(item))
        elif item.parent():
            # 是子项，添加复制父分组选项
            copy_group_action = menu.addAction("复制此分组")
            copy_group_action.triggered.connect(lambda: self._copy_info_group(item.parent()))
            
        menu.addSeparator()
        
        # 复制所有
        copy_all_action = menu.addAction("复制所有信息")
        copy_all_action.triggered.connect(self._copy_all_info)
        
        menu.exec(self.info_tree.viewport().mapToGlobal(position))

    def _copy_info_row(self, item):
        """复制单行信息"""
        if item.childCount() > 0:
            # 是分组标题，去掉三角符号
            text = item.text(0).lstrip("+-  ")
        else:
            # 是数据行，去掉前导空格
            key = item.text(0).strip()
            text = f"{key}: {item.text(1)}"
        
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

    def _copy_info_group(self, group_item):
        """复制分组信息"""
        # 去掉三角符号
        title = group_item.text(0).lstrip("+-  ")
        lines = [title]
        for i in range(group_item.childCount()):
            child = group_item.child(i)
            key = child.text(0).strip()
            lines.append(f"  {key}: {child.text(1)}")
            
        clipboard = QApplication.clipboard()
        clipboard.setText('\n'.join(lines))

    def _copy_all_info(self):
        """复制所有信息"""
        lines = []
        for i in range(self.info_tree.topLevelItemCount()):
            group = self.info_tree.topLevelItem(i)
            # 去掉三角符号
            title = group.text(0).lstrip("+-  ")
            lines.append(title)
            for j in range(group.childCount()):
                child = group.child(j)
                key = child.text(0).strip()
                lines.append(f"  {key}: {child.text(1)}")
            lines.append("")  # 分组之间空行
            
        clipboard = QApplication.clipboard()
        clipboard.setText('\n'.join(lines))
