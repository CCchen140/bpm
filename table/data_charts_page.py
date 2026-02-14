from __future__ import annotations

import os

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.utils.color_manager import ColorManager
from utils.setting.settings_manager import SettingsManager
from utils.log_manager import LogManager

from table.web.charts_backend_manager import ChartsBackendManager
from table.web.charts_web_bridge import ChartsWebBridge
from table.web.data_charts_html_v3 import build_html

try:
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage
except Exception:
    QWebEngineView = None
    QWebChannel = None
    QWebEngineSettings = None
    QWebEnginePage = None


def _project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    except Exception:
        return os.getcwd()


class DataChartsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataChartsPage")
        try:
            self._debug_enabled = bool(SettingsManager.instance().get("debug/charts_web_debug", False))
        except Exception:
            self._debug_enabled = False
        self._build()

    def set_debug_enabled(self, enabled: bool):
        try:
            self._debug_enabled = bool(enabled)
        except Exception:
            self._debug_enabled = False
        try:
            sm = SettingsManager.instance()
            sm.set("debug/charts_web_debug", bool(self._debug_enabled))
            sm.sync()
        except Exception:
            pass
        try:
            web = getattr(self, "web", None)
            if web is None:
                return
            page = web.page()
            if page is None:
                return
            if self._debug_enabled:
                page.runJavaScript(
                    "try{if(window.__bpSetDebug){window.__bpSetDebug(true);}else{window.__bpDebug=true;"
                    "const a=document.getElementById('statusBadge'); if(a){a.style.display='block'; a.textContent='DEBUG: ON';}}}catch(e){}"
                )
            else:
                page.runJavaScript(
                    "try{if(window.__bpSetDebug){window.__bpSetDebug(false);}else{window.__bpDebug=false;"
                    "const a=document.getElementById('statusBadge'); if(a){a.style.display='none';}}}catch(e){}"
                )
        except Exception:
            pass

    def reload_html(self):
        try:
            web = getattr(self, "web", None)
            if web is None:
                return
            html = build_html()
            base_url = getattr(self, "_base_url", None)
            if base_url is None:
                base_url = QUrl.fromLocalFile(_project_root().replace("\\", "/") + "/")
                self._base_url = base_url
            web.setHtml(html, base_url)
        except Exception:
            pass

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if QWebEngineView is None or QWebChannel is None:
            msg = QLabel("当前环境未安装 QtWebEngine，无法加载数据图表页面")
            msg.setWordWrap(True)
            msg.setContentsMargins(20, 20, 20, 20)
            root.addWidget(msg, 1)
            self._apply_fallback_theme(msg)
            try:
                ColorManager.instance().register_listener(lambda: self._apply_fallback_theme(msg))
            except Exception:
                pass
            return

        self._manager = ChartsBackendManager()
        self._bridge = ChartsWebBridge(self._manager, parent=self)

        self.web = QWebEngineView(self)
        if QWebEnginePage is not None:
            try:
                self.web.setPage(_ChartsWebPage(self.web, host=self))
            except Exception:
                pass
        self.channel = QWebChannel(self.web.page())
        self.channel.registerObject("bridge", self._bridge)
        self.web.page().setWebChannel(self.channel)

        try:
            if QWebEngineSettings is not None:
                s = self.web.settings()
                s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
                s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
                s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
                try:
                    ps = self.web.page().profile().settings()
                    ps.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
                    ps.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
                    ps.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
                    ps.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
                except Exception:
                    pass
        except Exception:
            pass

        self._base_url = QUrl.fromLocalFile(_project_root().replace("\\", "/") + "/")
        html = build_html()
        self.web.setHtml(html, self._base_url)
        try:
            self.web.loadFinished.connect(self._on_web_load_finished)
        except Exception:
            pass
        root.addWidget(self.web, 1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(30000)
        self._refresh_timer.timeout.connect(lambda: self._bridge.push_event("data_changed", {}))
        self._refresh_timer.start()

    def _on_web_load_finished(self, ok: bool):
        try:
            if not hasattr(self, "web") or self.web is None:
                return
            page = self.web.page()
            if page is None:
                return
            try:
                if bool(getattr(self, "_debug_enabled", False)):
                    page.runJavaScript(
                        "try{if(window.__bpSetDebug){window.__bpSetDebug(true);}else{window.__bpDebug=true;"
                        "const a=document.getElementById('statusBadge'); if(a){a.style.display='block';}}}catch(e){}"
                    )
                else:
                    page.runJavaScript(
                        "try{if(window.__bpSetDebug){window.__bpSetDebug(false);}else{window.__bpDebug=false;"
                        "const a=document.getElementById('statusBadge'); if(a){a.style.display='none';}}}catch(e){}"
                    )
            except Exception:
                pass
            if not bool(getattr(self, "_debug_enabled", False)):
                return

            def _after_probe(res):
                try:
                    badge = ""
                    script_ok = False
                    if isinstance(res, dict):
                        badge = str(res.get("badge") or "")
                        script_ok = bool(res.get("scriptOk"))
                    if not ok:
                        text = "页面加载失败"
                    else:
                        text = "页面已加载"
                        try:
                            if QWebEngineSettings is not None and not self.web.settings().testAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled):
                                text = text + " (JS=OFF?)"
                            else:
                                text = text + " (JS=ON)"
                        except Exception:
                            text = text + " (JS=ON)"
                    if script_ok:
                        return
                    if badge and badge not in ("准备就绪", "页面已加载 (JS=ON)", "页面已加载 (JS=OFF?)"):
                        return
                    page.runJavaScript(
                        "try{const a=document.getElementById('statusBadge'); if(a) a.textContent=%r;}catch(e){}" % text
                    )
                except Exception:
                    pass

            page.runJavaScript(
                "(function(){try{const b=document.getElementById('statusBadge');"
                "return {badge:(b?b.textContent:''), scriptOk:!!window.__bpScriptOk};}catch(e){return {badge:'', scriptOk:false};}})();",
                _after_probe,
            )
            if ok:
                try:
                    QTimer.singleShot(900, self._probe_runtime_state)
                except Exception:
                    pass
        except Exception:
            pass

    def _probe_runtime_state(self):
        try:
            if not bool(getattr(self, "_debug_enabled", False)):
                return
            if not hasattr(self, "web") or self.web is None:
                return
            page = self.web.page()
            if page is None:
                return

            def _after(res):
                try:
                    if not isinstance(res, dict):
                        return
                    badge = str(res.get("badge") or "")
                    script_ok = bool(res.get("scriptOk"))
                    ensure_bridge = str(res.get("ensureBridge") or "")
                    bridge_call = str(res.get("bridgeCall") or "")
                    if not script_ok:
                        return
                    if badge and badge not in ("准备就绪", "页面已加载 (JS=ON)", "页面已加载 (JS=OFF?)"):
                        return
                    text = f"脚本已执行 但未启动: ensureBridge={ensure_bridge}, bridgeCall={bridge_call}"
                    page.runJavaScript(
                        "try{const a=document.getElementById('statusBadge'); if(a) a.textContent=%r;}catch(e){}" % text
                    )
                except Exception:
                    pass

            page.runJavaScript(
                "(function(){try{const b=document.getElementById('statusBadge');"
                "return {badge:(b?b.textContent:''), scriptOk:!!window.__bpScriptOk,"
                "ensureBridge:(typeof window.ensureBridge), bridgeCall:(typeof window.bridgeCall)};"
                "}catch(e){return {badge:'', scriptOk:false, ensureBridge:'', bridgeCall:''};}})();",
                _after,
            )
        except Exception:
            pass

    def _apply_fallback_theme(self, label: QLabel):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.light", "#FFFFFF")
        text = cm.get("theme.text.dark", "#222222")
        self.setStyleSheet(f"background-color: {bg};")
        label.setStyleSheet(f"font-size: 13px; color: {text};")


class _ChartsWebPage(QWebEnginePage):
    def __init__(self, parent=None, host: DataChartsPage | None = None):
        super().__init__(parent)
        self._host = host

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            host = getattr(self, "_host", None)
            debug_on = bool(getattr(host, "_debug_enabled", False))
            web = getattr(host, "web", None) if host else None
            msg = str(message or "")
            src = str(sourceID or "")
            if src:
                try:
                    src = src.split("/")[-1]
                except Exception:
                    pass
            try:
                lvl = str(getattr(level, "name", "") or str(level or "")).lower()
            except Exception:
                lvl = ""
            try:
                prefix = "JS控制台"
                if src or lineNumber:
                    prefix = f"{prefix} @{src}:{int(lineNumber)}"
                text = f"{prefix} {msg}"
                try:
                    if "error" in lvl or "uncaught" in msg.lower():
                        LogManager.instance().error(text)
                    else:
                        LogManager.instance().warning(text)
                except Exception:
                    pass
            except Exception:
                pass

            if debug_on and web is not None:
                page = web.page()
                if page is not None:
                    text = f"控制台: {msg}"
                    if src or lineNumber:
                        text = f"{text} @{src}:{int(lineNumber)}"
                    page.runJavaScript(
                        "try{const a=document.getElementById('statusBadge'); if(a) a.textContent=%r;}catch(e){}" % text
                    )
        except Exception:
            pass
        try:
            return super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)
        except Exception:
            return
