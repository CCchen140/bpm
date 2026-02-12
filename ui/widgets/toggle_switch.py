from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtProperty, QEasingCurve, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QLinearGradient, QGradient, QBrush
from ui.utils.color_manager import ColorManager

class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None, width=50, height=26, 
                 track_color_on="#4CAF50", track_color_off="#B0BEC5",
                 thumb_color="#FFFFFF"):
        super().__init__(parent)
        
        # UI Configuration
        self._width = width
        self._height = height
        self._track_color_on = QColor(track_color_on)
        self._track_color_off = QColor(track_color_off)
        self._thumb_color = QColor(thumb_color)
        
        # State
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._width, self._height)
        
        # Animation properties
        self._thumb_pos = 0.0  # 0.0 (left/off) to 1.0 (right/on)
        self._anim = QPropertyAnimation(self, b"thumb_pos", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        self.stateChanged.connect(self._start_animation)
        
        # Apply tooltip styles
        self._apply_tooltip_styles()
        
        # Register theme listener
        ColorManager.instance().register_listener(self._apply_tooltip_styles)
    
    def set_track_color_on(self, color):
        self._track_color_on = QColor(color)
        self.update()
    
    def set_track_color_off(self, color):
        self._track_color_off = QColor(color)
        self.update()
    
    def _apply_tooltip_styles(self):
        cm = ColorManager.instance()
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        self.setStyleSheet(f"""
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
            }}
        """)

    @pyqtProperty(float)
    def thumb_pos(self):
        return self._thumb_pos

    @thumb_pos.setter
    def thumb_pos(self, pos):
        self._thumb_pos = pos
        self.update()

    def _start_animation(self, state):
        self._anim.stop()
        end_value = 1.0 if state == Qt.CheckState.Checked.value else 0.0
        self._anim.setEndValue(end_value)
        self._anim.start()

    def hitButton(self, pos):
        return self.contentsRect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Geometry calculations
        margin = 3
        rect = self.rect()
        track_rect = QRectF(rect.x(), rect.y(), rect.width(), rect.height())
        
        # Determine colors based on position (interpolating for smooth transition)
        # Or just use the target state color if we want a simpler logic, 
        # but blending looks better.
        
        # Draw Track
        painter.setPen(Qt.PenStyle.NoPen)
        
        # Gradient for Track (Textured look)
        if self.isChecked():
            # Greenish gradient
            grad = QLinearGradient(track_rect.topLeft(), track_rect.bottomLeft())
            grad.setColorAt(0, self._track_color_on.lighter(110))
            grad.setColorAt(1, self._track_color_on.darker(110))
        else:
            # Greyish gradient
            grad = QLinearGradient(track_rect.topLeft(), track_rect.bottomLeft())
            grad.setColorAt(0, self._track_color_off.lighter(110))
            grad.setColorAt(1, self._track_color_off.darker(110))
            
        painter.setBrush(grad)
        painter.drawRoundedRect(track_rect, self._height / 2, self._height / 2)
        
        # Inner Shadow simulation removed to blend better with background
        # painter.setBrush(Qt.BrushStyle.NoBrush)
        # pen = QPen(QColor(0, 0, 0, 30))
        # pen.setWidth(1)
        # painter.setPen(pen)
        # painter.drawRoundedRect(track_rect.adjusted(1, 1, -1, -1), self._height / 2 - 1, self._height / 2 - 1)

        # Draw Thumb
        thumb_size = self._height - (margin * 2)
        
        # Calculate thumb x position
        # Start X: margin
        # End X: width - margin - thumb_size
        start_x = margin
        range_x = self._width - (margin * 2) - thumb_size
        current_x = start_x + (range_x * self._thumb_pos)
        
        thumb_rect = QRectF(current_x, margin, thumb_size, thumb_size)
        
        # Thumb Shadow (Simple offset)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(thumb_rect.adjusted(1, 2, 1, 2))
        
        # Thumb Gradient (Metallic/Plastic look)
        thumb_grad = QLinearGradient(thumb_rect.topLeft(), thumb_rect.bottomLeft())
        thumb_grad.setColorAt(0, QColor("#FFFFFF"))
        thumb_grad.setColorAt(1, QColor("#E0E0E0"))
        
        painter.setBrush(thumb_grad)
        painter.drawEllipse(thumb_rect)
        
        # Thumb Border
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        painter.drawEllipse(thumb_rect)
