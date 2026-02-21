import json
import os
import threading
import tempfile
try:
    import cv2
except Exception:
    cv2 = None

from PyQt6.QtCore import Qt, QStringListModel, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QCompleter

from ui.utils.icon_loader import qta

from core.classifier.bird_biological_classifier import BirdBiologicalClassifier
from core.detectors.bird_focus_detector import BirdFocusDetector
from core.recognizer.bird_species_recognizer import BirdSpeciesRecognizer
from ui.utils.color_manager import ColorManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.status_manager import StatusManager


class EditSpeciesDialog(QDialog):
    _recognition_done = pyqtSignal(str, str)

    def __init__(self, parent=None, initial_species: str = "", initial_order: str = "", initial_family: str = "", initial_genus: str = "", image_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("修改物种")
        self.setModal(True)
        self._result = None
        self._image_path = image_path
        self._recognition_done.connect(self._on_recognition_done)

        cm = ColorManager.instance()
        bg = cm.get("popup.background.primary")
        border = cm.get("popup.border.primary")
        text = cm.get("theme.text.dark")
        primary = cm.get("theme.primary")
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QLabel {{ color: {text}; }}
            QLineEdit {{
                padding: 6px 10px;
                border: 1px solid {border};
                border-radius: 6px;
                background-color: {cm.get("theme.background.primary")};
                color: {text};
            }}
            QCheckBox {{ color: {text}; }}
            QPushButton {{
                padding: 6px 14px;
                border-radius: 6px;
                border: 1px solid {border};
                background-color: {cm.get("theme.background.primary")};
                color: {text};
            }}
            QPushButton:hover {{
                border-color: {primary};
            }}
            QPushButton#primary {{
                background-color: {primary};
                color: {cm.get("theme.text.light")};
                border-color: {primary};
            }}
            QPushButton#primary:disabled {{
                background-color: {border};
                color: #A0A0A0;
                border-color: {border};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("修改物种与分类")
        tfont = QFont()
        tfont.setPointSize(12)
        tfont.setBold(True)
        title.setFont(tfont)
        title_row.addWidget(title, 1)
        layout.addLayout(title_row)

        self.species_input = QLineEdit()
        self.species_input.setPlaceholderText("物种（中文名）")
        self.species_input.setText(str(initial_species or ""))
        layout.addWidget(QLabel("物种"))
        
        species_row = QHBoxLayout()
        species_row.setSpacing(8)
        species_row.addWidget(self.species_input)
        
        if self._image_path and os.path.exists(self._image_path):
             self.identify_btn = QPushButton("识别")
             self.identify_btn.setIcon(qta.icon("mdi6.eye-outline", color=cm.get("theme.text.dark")))
             self.identify_btn.setToolTip("使用AI识别物种")
             self.identify_btn.setFixedWidth(80)
             self.identify_btn.clicked.connect(self._on_identify_clicked)
             species_row.addWidget(self.identify_btn)
             
        layout.addLayout(species_row)
        try:
            if (not str(initial_species or "").strip()) and self._image_path and os.path.exists(self._image_path):
                folder_name = os.path.basename(os.path.dirname(self._image_path))
                if folder_name:
                    try:
                        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                        path = os.path.join(project_root, "data", "bird_classification.json")
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, dict) and str(folder_name) in data:
                            self.species_input.setText(str(folder_name))
                    except Exception:
                        pass
        except Exception:
            pass

        row1 = QHBoxLayout()
        self.order_input = QLineEdit()
        self.order_input.setPlaceholderText("目（例如：雀形目）")
        self.order_input.setText(str(initial_order or ""))
        self.family_input = QLineEdit()
        self.family_input.setPlaceholderText("科（例如：鸦科）")
        self.family_input.setText(str(initial_family or ""))
        row1.addWidget(self.order_input, 1)
        row1.addWidget(self.family_input, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.genus_input = QLineEdit()
        self.genus_input.setPlaceholderText("属（例如：鸦属）")
        self.genus_input.setText(str(initial_genus or ""))
        row2.addWidget(self.genus_input, 1)
        layout.addLayout(row2)

        self.move_files_cb = QCheckBox("同时移动文件到新物种文件夹")
        self.move_files_cb.setChecked(True)
        layout.addWidget(self.move_files_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        self.ok_btn = QPushButton("确定")
        self.ok_btn.setObjectName("primary")
        cancel_btn.setIcon(qta.icon("mdi6.close", color=cm.get("theme.text.dark")))
        self.ok_btn.setIcon(qta.icon("mdi6.check", color=cm.get("theme.text.light")))
        cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

        self._init_species_completer()
        self.species_input.textChanged.connect(self._on_species_changed)
        self.species_input.textChanged.connect(self._update_ok_enabled)
        self.order_input.textChanged.connect(self._update_ok_enabled)
        self.family_input.textChanged.connect(self._update_ok_enabled)
        self.genus_input.textChanged.connect(self._update_ok_enabled)
        self._update_ok_enabled()

    def _init_species_completer(self):
        names = []
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            path = os.path.join(project_root, "data", "bird_classification.json")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                names = [str(k) for k in data.keys() if k]
        except Exception:
            names = []
        model = QStringListModel(names)
        completer = QCompleter(model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.species_input.setCompleter(completer)

    def _on_species_changed(self, text: str):
        s = str(text or "").strip()
        if not s:
            try:
                self._update_ok_enabled()
            except Exception:
                pass
            return
        try:
            t = BirdBiologicalClassifier().classify(s)
        except Exception:
            t = None
        if not t:
            return
        try:
            if not self.order_input.text().strip():
                self.order_input.setText(str(t.order_cn or ""))
            if not self.family_input.text().strip():
                self.family_input.setText(str(t.family_cn or ""))
            if not self.genus_input.text().strip():
                self.genus_input.setText(str(t.genus_cn or ""))
        except Exception:
            pass
        try:
            self._update_ok_enabled()
        except Exception:
            pass

    def _is_taxonomy_complete(self) -> bool:
        try:
            species = str(self.species_input.text() or "").strip()
            order = str(self.order_input.text() or "").strip()
            family = str(self.family_input.text() or "").strip()
            genus = str(self.genus_input.text() or "").strip()
        except Exception:
            return False
        return bool(species and order and family and genus)

    def _update_ok_enabled(self, *args, **kwargs):
        try:
            self.ok_btn.setEnabled(self._is_taxonomy_complete())
        except Exception:
            pass

    def _on_ok(self):
        # 在确定前，如果物种名存在但目科属不完整，尝试自动填充
        species = str(self.species_input.text() or "").strip()
        order = str(self.order_input.text() or "").strip()
        family = str(self.family_input.text() or "").strip()
        genus = str(self.genus_input.text() or "").strip()

        if species and (not order or not family or not genus):
            try:
                t = BirdBiologicalClassifier().classify(species)
                if t is not None:
                    if not order and t.order_cn:
                        order = t.order_cn
                        self.order_input.setText(order)
                    if not family and t.family_cn:
                        family = t.family_cn
                        self.family_input.setText(family)
                    if not genus and t.genus_cn:
                        genus = t.genus_cn
                        self.genus_input.setText(genus)
            except Exception:
                pass

        if not self._is_taxonomy_complete():
            NotificationManager.instance().show_warning("提示", "请先填写完整的生物学分类（物种/目/科/属）")
            return

        # 重新获取值（可能被自动填充更新了）
        species = str(self.species_input.text() or "").strip()
        order = str(self.order_input.text() or "").strip()
        family = str(self.family_input.text() or "").strip()
        genus = str(self.genus_input.text() or "").strip()
        move_files = bool(self.move_files_cb.isChecked())
        self._result = {
            "species_cls": species,
            "order_cls": order,
            "family_cls": family,
            "genus_cls": genus,
            "move_files": move_files,
        }
        self.accept()

    def _on_identify_clicked(self):
        if not self._image_path: return
        self.identify_btn.setEnabled(False)
        self.species_input.setEnabled(False)
        self._task_id = StatusManager.instance().start_task("正在识别物种...")
        threading.Thread(target=self._run_recognition, daemon=True).start()

    def _run_recognition(self):
        try:
             # Detect & Crop
             detector = BirdFocusDetector()
             res = detector.detect_file(self._image_path)
             
             final_path = self._image_path
             tmp_path = None
             
             best_bird = res.get("best_bird")
             if best_bird:
                 bbox = best_bird.get("bbox")
                 if bbox:
                      # Crop
                      if cv2 is None:
                          raise RuntimeError("缺少依赖：opencv-python")
                      img = cv2.imread(self._image_path)
                      if img is not None:
                          h, w = img.shape[:2]
                          x1, y1, x2, y2 = [int(v) for v in bbox]
                          x1 = max(0, min(x1, w-1))
                          y1 = max(0, min(y1, h-1))
                          x2 = max(0, min(x2, w))
                          y2 = max(0, min(y2, h))
                          if x2 > x1 and y2 > y1:
                              crop = img[y1:y2, x1:x2]
                              fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
                              os.close(fd)
                              cv2.imwrite(tmp_path, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                              final_path = tmp_path
             
             # Recognize
             rec = BirdSpeciesRecognizer()
             result_text = rec.recognize(final_path).text
             
             # Clean up
             if tmp_path and os.path.exists(tmp_path):
                 os.remove(tmp_path)
                 
             self._recognition_done.emit(result_text, "")
             
        except Exception as e:
             self._recognition_done.emit("", str(e))

    def _on_recognition_done(self, text, err):
        StatusManager.instance().finish_task(self._task_id)
        self.identify_btn.setEnabled(True)
        self.species_input.setEnabled(True)
        
        if err:
            NotificationManager.instance().show_warning("识别失败", err)
            return
            
        if text and text != "无法识别":
             s = text.replace("。", "").replace(".", "").strip()
             self.species_input.setText(s)
             NotificationManager.instance().show_toast(f"识别结果: {s}")
        else:
             NotificationManager.instance().show_warning("提示", "未能识别出物种")

    def get_result(self):
        return self._result
