# 通用样式定义

# 工具栏按钮样式
TOOLBAR_BTN_STYLE = """
    QPushButton {
        background: transparent;
        border: none;
        font-size: 16px;
        padding: 4px;
    }
    QPushButton:hover {
        background-color: #e0e0e0;
    }
    QPushButton:pressed {
        background-color: #d0d0d0;
    }
"""

# 统一下拉框样式
COMBO_STYLE = """
    QComboBox {
        padding: 4px 8px;
        border: 1px solid #d0d0d0;
        background-color: #ffffff;
        font-size: 12px;
        min-width: 70px;
    }
    QComboBox:hover {
        border: 1px solid #2196f3;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
        background: transparent;
    }
    QComboBox::down-arrow {
        image: url(data/icon/line/箭头下_arrow-down.svg);
        width: 12px;
        height: 12px;
        margin-right: 5px;
    }
    QComboBox QAbstractItemView {
        border: 1px solid #d0d0d0;
        background-color: #ffffff;
        selection-background-color: #e3f2fd;
    }
"""

# 滚动区域样式
SCROLL_AREA_STYLE = """
    QScrollArea {
        border: none;
        background-color: #f5f5f5;
    }
    QScrollBar:vertical {
        background-color: #f0f0f0;
        width: 10px;
    }
    QScrollBar::handle:vertical {
        background-color: #c0c0c0;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #a0a0a0;
    }
    QScrollBar:horizontal {
        background-color: #f0f0f0;
        height: 10px;
    }
    QScrollBar::handle:horizontal {
        background-color: #c0c0c0;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover {
        background-color: #a0a0a0;
    }
"""

SPLITTER_STYLE = """
    QSplitter::handle {
        background-color: #d0d0d0;
        width: 1px;
    }
    QSplitter::handle:hover {
        background-color: #2196f3;
    }
"""
