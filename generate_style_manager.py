"""生成Web样式管理器"""
import os

content = '''"""
Web版样式管理器
"""

class WebStyleManager:
    def __init__(self):
        self.current_theme = 'dark'
    
    def get_all_styles(self):
        return """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #1e1e1e; 
            color: #cccccc; 
            overflow: hidden;
        }
        ::-webkit-scrollbar { width: 12px; height: 12px; }
        ::-webkit-scrollbar-track { background: #1e1e1e; }
        ::-webkit-scrollbar-thumb { background: #424242; border-radius: 6px; }
        ::-webkit-scrollbar-thumb:hover { background: #4e4e4e; }
        
        .container { display: flex; height: 100vh; width: 100vw; }
        .sidebar { 
            width: 250px; 
            background-color: #252526; 
            border-right: 1px solid #3e3e42; 
            display: flex; 
            flex-direction: column; 
        }
        .main-content { flex: 1; display: flex; flex-direction: column; }
        .right-panel { 
            width: 350px; 
            background-color: #252526; 
            border-left: 1px solid #3e3e42; 
            display: flex; 
            flex-direction: column; 
        }
        .toolbar { 
            height: 48px; 
            background-color: #252526; 
            border-bottom: 1px solid #3e3e42; 
            display: flex; 
            align-items: center; 
            padding: 0 12px; 
            gap: 8px; 
        }
        .content-area { flex: 1; overflow: auto; }
        
        .tree-header { 
            height: 40px; 
            background-color: #252526; 
            border-bottom: 1px solid #3e3e42; 
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
        .tree-node:hover { background-color: #2a2d2e; }
        .tree-node.selected { background-color: #094771; }
        .tree-node-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .tree-node-count { color: #858585; font-size: 11px; }
        
        .grid-container { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); 
            gap: 12px; 
            padding: 12px; 
        }
        .grid-item { 
            background-color: #252526; 
            border: 1px solid #3e3e42; 
            border-radius: 6px; 
            overflow: hidden; 
            cursor: pointer; 
            transition: all 0.2s; 
        }
        .grid-item:hover { 
            border-color: #007acc; 
            transform: translateY(-2px); 
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); 
        }
        .grid-item.selected { border-color: #007acc; background-color: #094771; }
        .grid-item-image { width: 100%; height: 180px; object-fit: cover; background-color: #1e1e1e; }
        .grid-item-info { padding: 8px; font-size: 12px; }
        .grid-item-name { 
            font-weight: 500; 
            overflow: hidden; 
            text-overflow: ellipsis; 
            white-space: nowrap; 
            margin-bottom: 4px; 
        }
        .grid-item-meta { color: #858585; font-size: 11px; }
        
        .preview-container { 
            flex: 1; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            background-color: #1e1e1e; 
            border-bottom: 1px solid #3e3e42; 
        }
        .preview-image { max-width: 100%; max-height: 100%; object-fit: contain; }
        .preview-empty { color: #858585; font-size: 14px; }
        
        .info-header { 
            height: 40px; 
            background-color: #252526; 
            border-bottom: 1px solid #3e3e42; 
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
            color: #858585; 
            margin-bottom: 8px; 
            text-transform: uppercase; 
        }
        .info-row { display: flex; padding: 6px 0; font-size: 13px; border-bottom: 1px solid #3e3e42; }
        .info-row:last-child { border-bottom: none; }
        .info-label { width: 100px; color: #858585; flex-shrink: 0; }
        .info-value { flex: 1; color: #cccccc; word-break: break-all; }
        
        .btn-icon { 
            width: 32px; 
            height: 32px; 
            border: none; 
            background-color: transparent; 
            color: #cccccc; 
            cursor: pointer; 
            border-radius: 4px; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
        }
        .btn-icon:hover { background-color: #2a2d2e; color: #ffffff; }
        .icon { width: 16px; height: 16px; fill: currentColor; }
        """

def get_style_manager():
    return WebStyleManager()
'''

# 写入文件
output_path = os.path.join(os.path.dirname(__file__), 'ui', 'web', 'web_style_manager.py')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'已创建: {output_path}')

