import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

from table.web.charts_backend_manager import ChartsBackendManager, _store_path
from table.web.charts_web_bridge import ChartsWebBridge
from table.web.data_charts_html_v3 import build_html


def main():
    m = ChartsBackendManager()
    b = ChartsWebBridge(m)
    print("store_path", _store_path())
    boot = m.bootstrap()
    print("chart_types", len(boot.get("chart_types") or []))
    print("charts", len(boot.get("charts") or []))
    print("token_len", len(b.token))
    html = build_html()
    print("html_ok", ("__REGISTER_CODE__" not in html) and ("__THEME_OPTS__" not in html) and ("__THEME_UI__" not in html))
    c = m.add_chart({"name": "test", "type": "bar", "dataset": "library", "options": {"x_field": "created_at", "y_agg": "count"}})
    m.update_layout(c["chart_id"], {"x": 10, "y": 20, "w": 400, "h": 300, "z": 99})
    print("layout_saved", bool(m.bootstrap().get("charts")))
    m.remove_chart(c["chart_id"])


if __name__ == "__main__":
    main()
