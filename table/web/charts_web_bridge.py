from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from utils.log_manager import LogManager

from table.web.charts_backend_manager import ChartsBackendManager


def _json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def _b64(s: bytes) -> str:
    return base64.b64encode(s).decode("ascii")


class ChartsWebBridge(QObject):
    push = pyqtSignal(str, str)

    def __init__(self, manager: ChartsBackendManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = manager
        self._token = secrets.token_urlsafe(24)

    @property
    def token(self) -> str:
        return self._token

    def _log_warning(self, msg: str) -> None:
        try:
            LogManager.instance().warning(msg)
        except Exception:
            pass

    def _sign(self, action: str, payload: str) -> str:
        key = (self._token or "").encode("utf-8")
        msg = (str(action or "") + "\n" + str(payload or "")).encode("utf-8")
        mac = hmac.new(key, msg, hashlib.sha256).digest()
        return _b64(mac)

    def _verify(self, action: str, payload: str, token: str, sig: str) -> bool:
        if str(token or "") != str(self._token or ""):
            return False
        expected = self._sign(action, payload)
        try:
            return hmac.compare_digest(str(expected), str(sig or ""))
        except Exception:
            return False

    @pyqtSlot(result=str)
    def getToken(self) -> str:
        return str(self._token or "")

    @pyqtSlot(str, str, str, str, result=str)
    def request(self, action: str, payload: str, token: str, sig: str) -> str:
        act = str(action or "")
        raw = str(payload or "")
        if not self._verify(act, raw, token, sig):
            return _json_dumps({"ok": False, "error": "unauthorized"})

        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}

        try:
            if act == "bootstrap":
                return _json_dumps({"ok": True, "data": self._manager.bootstrap()})
            if act == "add_chart":
                return _json_dumps({"ok": True, "data": self._manager.add_chart(dict(data or {}))})
            if act == "update_chart":
                cid = str(data.get("chart_id") or "")
                cfg = {k: data.get(k) for k in ["name", "type", "dataset", "options"] if k in data}
                return _json_dumps({"ok": True, "data": self._manager.update_chart(cid, cfg)})
            if act == "remove_chart":
                self._manager.remove_chart(str(data.get("chart_id") or ""))
                return _json_dumps({"ok": True})
            if act == "set_theme":
                self._manager.set_theme(str(data.get("theme") or "follow"))
                return _json_dumps({"ok": True})
            if act == "set_display_options":
                self._manager.set_display_options(dict(data.get("options") or {}))
                return _json_dumps({"ok": True})
            if act == "set_gpu":
                self._manager.set_gpu_rendering_enabled(bool(data.get("enabled", False)))
                return _json_dumps({"ok": True})
            if act == "set_preferences":
                self._manager.set_preferences(
                    str(data.get("theme") or "follow"),
                    dict(data.get("options") or {}),
                    bool(data.get("gpu_enabled", False)),
                )
                return _json_dumps({"ok": True})
            if act == "update_layout":
                self._manager.update_layout(str(data.get("chart_id") or ""), dict(data.get("layout") or {}))
                return _json_dumps({"ok": True})
            if act == "update_user_field":
                dataset = str(data.get("dataset") or "library")
                field_name = str(data.get("field_name") or "")
                field_value = data.get("field_value")
                file_paths = data.get("file_paths") or []
                if not isinstance(file_paths, list):
                    file_paths = []
                self._manager.update_dataset_user_field(dataset, field_name, field_value, [str(p) for p in file_paths if p])
                self.push_event("data_changed", {})
                return _json_dumps({"ok": True})
            if act == "get_chart_payload":
                return _json_dumps({"ok": True, "data": self._manager.build_chart_payload(dict(data or {}))})
        except Exception as e:
            self._log_warning(f"ChartsWebBridge request失败: {e}")
            return _json_dumps({"ok": False, "error": "internal_error"})

        return _json_dumps({"ok": False, "error": "unknown_action"})

    @pyqtSlot(str, str, result=str)
    def requestSimple(self, action: str, payload: str) -> str:
        act = str(action or "")
        raw = str(payload or "")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        try:
            if act == "bootstrap":
                return _json_dumps({"ok": True, "data": self._manager.bootstrap()})
            if act == "add_chart":
                return _json_dumps({"ok": True, "data": self._manager.add_chart(dict(data or {}))})
            if act == "update_chart":
                cid = str(data.get("chart_id") or "")
                cfg = {k: data.get(k) for k in ["name", "type", "dataset", "options"] if k in data}
                return _json_dumps({"ok": True, "data": self._manager.update_chart(cid, cfg)})
            if act == "remove_chart":
                self._manager.remove_chart(str(data.get("chart_id") or ""))
                return _json_dumps({"ok": True})
            if act == "set_theme":
                self._manager.set_theme(str(data.get("theme") or "follow"))
                return _json_dumps({"ok": True})
            if act == "set_display_options":
                self._manager.set_display_options(dict(data.get("options") or {}))
                return _json_dumps({"ok": True})
            if act == "set_gpu":
                self._manager.set_gpu_rendering_enabled(bool(data.get("enabled", False)))
                return _json_dumps({"ok": True})
            if act == "set_preferences":
                self._manager.set_preferences(
                    str(data.get("theme") or "follow"),
                    dict(data.get("options") or {}),
                    bool(data.get("gpu_enabled", False)),
                )
                return _json_dumps({"ok": True})
            if act == "update_layout":
                self._manager.update_layout(str(data.get("chart_id") or ""), dict(data.get("layout") or {}))
                return _json_dumps({"ok": True})
            if act == "update_user_field":
                dataset = str(data.get("dataset") or "library")
                field_name = str(data.get("field_name") or "")
                field_value = data.get("field_value")
                file_paths = data.get("file_paths") or []
                if not isinstance(file_paths, list):
                    file_paths = []
                self._manager.update_dataset_user_field(dataset, field_name, field_value, [str(p) for p in file_paths if p])
                self.push_event("data_changed", {})
                return _json_dumps({"ok": True})
            if act == "get_chart_payload":
                return _json_dumps({"ok": True, "data": self._manager.build_chart_payload(dict(data or {}))})
        except Exception as e:
            self._log_warning(f"ChartsWebBridge requestSimple失败: {e}")
            return _json_dumps({"ok": False, "error": "internal_error"})
        return _json_dumps({"ok": False, "error": "unknown_action"})

    def push_event(self, event: str, payload_obj: Any) -> None:
        try:
            self.push.emit(str(event or ""), _json_dumps(payload_obj))
        except Exception:
            pass
