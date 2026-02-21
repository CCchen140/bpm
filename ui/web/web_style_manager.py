"""
Web版样式管理器
"""

from ui.utils.color_manager import ColorManager

class WebStyleManager:
    def __init__(self):
        self.current_theme = 'dark'
    
    def get_all_styles(self):
        cm = ColorManager.instance()
        body_bg = cm.get("theme.background.primary", "#1e1e1e")
        panel_bg = cm.get("theme.sidebar", "#252526")
        border = cm.get("popup.border.primary", "#3e3e42")
        text = cm.get("popup.text.primary", "#cccccc")
        muted = cm.get("popup.text.secondary", "#858585")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#2a2d2e")
        primary = cm.get("theme.primary", "#007acc")
        input_bg = cm.get("settings.shortcut_input.background", "#3c3c3c")
        tooltip_bg = cm.get("theme.popup", "#2d2d30")
        tooltip_text = cm.get("popup.text.primary", "#cccccc")
        css = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: __BODY_BG__; 
            color: __TEXT__; 
            overflow: hidden;
        }
        ::-webkit-scrollbar { width: 12px; height: 12px; }
        ::-webkit-scrollbar-track { background: __BODY_BG__; }
        ::-webkit-scrollbar-thumb { background: __BORDER__; border-radius: 6px; }
        ::-webkit-scrollbar-thumb:hover { background: __PRIMARY__; }
        
        .container { display: flex; height: 100vh; width: 100vw; }
        .sidebar { 
            width: 250px; 
            background-color: __PANEL_BG__; 
            border-right: 1px solid __BORDER__; 
            display: flex; 
            flex-direction: column; 
        }
        .main-content { flex: 1; display: flex; flex-direction: column; }
        .right-panel { 
            width: 350px; 
            background-color: __PANEL_BG__; 
            border-left: 1px solid __BORDER__; 
            display: flex; 
            flex-direction: column; 
        }
        .toolbar { 
            height: 48px; 
            background-color: __PANEL_BG__; 
            border-bottom: 1px solid __BORDER__; 
            display: flex; 
            align-items: center; 
            padding: 0 12px; 
            gap: 8px; 
        }
        .content-area { flex: 1; overflow: auto; }
        
        .tree-header { 
            height: 40px; 
            background-color: __PANEL_BG__; 
            border-bottom: 1px solid __BORDER__; 
            display: flex; 
            align-items: center; 
            padding: 0 12px; 
            font-weight: 600; 
            font-size: 13px; 
        }
        .tree-container { flex: 1; overflow: auto; padding: 8px; }
        .tree-node { 
            padding: 6px 8px; 
            cursor: pointer; 
            border-radius: 4px; 
            font-size: 13px; 
            display: flex; 
            align-items: center; 
            gap: 6px; 
        }
        .tree-node:hover { background-color: __HOVER_BG__; }
        .tree-node.selected { background-color: __PRIMARY__; }
        .tree-node-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .tree-node-count { color: __MUTED__; font-size: 11px; }
        
        .grid-container { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); 
            gap: 12px; 
            padding: 12px; 
        }
        .grid-item { 
            background-color: __PANEL_BG__; 
            border: 1px solid __BORDER__; 
            border-radius: 6px; 
            overflow: hidden; 
            cursor: pointer; 
            transition: all 0.2s; 
        }
        .grid-item:hover { 
            border-color: __PRIMARY__; 
            transform: translateY(-2px); 
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); 
        }
        .grid-item.selected { border-color: __PRIMARY__; background-color: __PRIMARY__; }
        .grid-item-image { width: 100%; height: 180px; object-fit: cover; background-color: __BODY_BG__; }
        .grid-item-info { padding: 8px; font-size: 12px; }
        .grid-item-name { 
            font-weight: 500; 
            overflow: hidden; 
            text-overflow: ellipsis; 
            white-space: nowrap; 
            margin-bottom: 4px; 
        }
        .grid-item-meta { color: __MUTED__; font-size: 11px; }
        
        .preview-container { 
            flex: 1; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            background-color: __BODY_BG__; 
            border-bottom: 1px solid __BORDER__; 
        }
        .preview-image { max-width: 100%; max-height: 100%; object-fit: contain; }
        .preview-empty { color: __MUTED__; font-size: 14px; }
        
        .info-header { 
            height: 40px; 
            background-color: __PANEL_BG__; 
            border-bottom: 1px solid __BORDER__; 
            display: flex; 
            align-items: center; 
            padding: 0 12px; 
            font-weight: 600; 
            font-size: 13px; 
        }
        .info-content { flex: 1; overflow: auto; padding: 12px; }
        .info-section { margin-bottom: 16px; }
        .info-section-title { 
            font-weight: 600; 
            font-size: 12px; 
            color: __MUTED__; 
            margin-bottom: 8px; 
            text-transform: uppercase; 
        }
        .info-row { display: flex; padding: 6px 0; font-size: 13px; border-bottom: 1px solid __BORDER__; }
        .info-row:last-child { border-bottom: none; }
        .info-label { width: 100px; color: __MUTED__; flex-shrink: 0; }
        .info-value { flex: 1; color: __TEXT__; word-break: break-all; }
        
        .btn-icon { 
            width: 32px; 
            height: 32px; 
            border: none; 
            background-color: transparent; 
            color: __TEXT__; 
            cursor: pointer; 
            border-radius: 4px; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            transition: all 0.2s;
        }
        .btn-icon:hover { background-color: __HOVER_BG__; color: __TEXT__; }
        .btn-icon.active { background-color: __PRIMARY__; color: __TEXT__; }
        .icon { width: 16px; height: 16px; fill: currentColor; }
        
        .toolbar-separator { 
            width: 1px; 
            height: 24px; 
            background-color: __BORDER__; 
            margin: 0 4px; 
        }
        
        .toolbar-select {
            height: 28px;
            padding: 0 8px;
            background-color: __INPUT_BG__;
            color: __TEXT__;
            border: 1px solid __BORDER__;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            outline: none;
        }
        .toolbar-select:hover { background-color: __HOVER_BG__; }
        .toolbar-select:focus { border-color: __PRIMARY__; }
        
        /* 列表视图样式 */
        .list-item {
            display: flex;
            align-items: center;
            background-color: __PANEL_BG__;
            border: 1px solid __BORDER__;
            padding: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .list-item:hover {
            background-color: __HOVER_BG__;
            border-color: __PRIMARY__;
        }
        .list-item.selected {
            background-color: __PRIMARY__;
            border-color: __PRIMARY__;
        }
        .list-item-image {
            width: 60px;
            height: 60px;
            object-fit: cover;
            border-radius: 4px;
            margin-right: 12px;
            background-color: __BODY_BG__;
        }
        .list-item-info {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .list-item-name {
            font-weight: 500;
            font-size: 13px;
        }
        .list-item-meta { color: __MUTED__; font-size: 12px; }
        
        /* 自定义Tooltip样式 */
        [data-tooltip] {
            position: relative;
        }
        [data-tooltip]:hover::before {
            content: attr(data-tooltip);
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            margin-bottom: 8px;
            padding: 6px 10px;
            background-color: __TOOLTIP_BG__;
            color: __TOOLTIP_TEXT__;
            font-size: 12px;
            white-space: nowrap;
            border-radius: 4px;
            border: 1px solid __BORDER__;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            z-index: 1000;
            pointer-events: none;
            opacity: 0;
            animation: tooltipFadeIn 0.2s ease-in-out forwards;
        }
        [data-tooltip]:hover::after {
            content: '';
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            margin-bottom: 2px;
            border: 6px solid transparent;
            border-top-color: __TOOLTIP_BG__;
            z-index: 1000;
            pointer-events: none;
            opacity: 0;
            animation: tooltipFadeIn 0.2s ease-in-out forwards;
        }
        @keyframes tooltipFadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        """
        return (
            str(css)
            .replace("__BODY_BG__", str(body_bg or ""))
            .replace("__PANEL_BG__", str(panel_bg or ""))
            .replace("__BORDER__", str(border or ""))
            .replace("__TEXT__", str(text or ""))
            .replace("__MUTED__", str(muted or ""))
            .replace("__HOVER_BG__", str(hover_bg or ""))
            .replace("__PRIMARY__", str(primary or ""))
            .replace("__INPUT_BG__", str(input_bg or ""))
            .replace("__TOOLTIP_BG__", str(tooltip_bg or ""))
            .replace("__TOOLTIP_TEXT__", str(tooltip_text or ""))
        )

def get_style_manager():
    return WebStyleManager()
