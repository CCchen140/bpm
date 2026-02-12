from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QRect
from PyQt6.QtGui import QPainter, QColor, QFont

class StarRatingWidget(QWidget):
    ratingChanged = pyqtSignal(int)

    def __init__(self, parent=None, max_rating=5):
        super().__init__(parent)
        self.max_rating = max_rating
        self.current_rating = 0
        self.hover_rating = 0
        self.is_read_only = False
        
        self.setMouseTracking(True)
        # Size: 24px per star
        self.setFixedSize(QSize(max_rating * 24 + 10, 30)) # Slightly larger for padding

    def setRating(self, rating):
        if rating != self.current_rating:
            self.current_rating = rating
            self.update()

    def setReadOnly(self, read_only):
        self.is_read_only = read_only

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        display_rating = self.hover_rating if self.hover_rating > 0 and not self.is_read_only else self.current_rating
        
        star_width = 24
        icon_size = 20
        
        for i in range(self.max_rating):
            rect = QRect(i * star_width, 0, star_width, 30)
            
            # Center the icon in the rect
            icon_rect = QRect(
                rect.x() + (rect.width() - icon_size) // 2,
                rect.y() + (rect.height() - icon_size) // 2,
                icon_size,
                icon_size
            )
            
            if i < display_rating:
                color = "#FFD700" # Gold
            else:
                color = "#CCCCCC" # Grey
                
            icon = qta.icon('fa5s.star', color=color)
            icon.paint(painter, icon_rect)

    def mouseMoveEvent(self, event):
        if self.is_read_only:
            return
        
        x = event.pos().x()
        star_width = 24
        rating = int(x / star_width) + 1
        rating = max(0, min(rating, self.max_rating))
        
        if self.hover_rating != rating:
            self.hover_rating = rating
            self.update()

    def leaveEvent(self, event):
        if self.hover_rating != 0:
            self.hover_rating = 0
            self.update()

    def mousePressEvent(self, event):
        if self.is_read_only:
            return
            
        x = event.pos().x()
        star_width = 24
        rating = int(x / star_width) + 1
        rating = max(0, min(rating, self.max_rating))
        
        # Toggle off if clicking the single star again
        if self.current_rating == 1 and rating == 1:
            rating = 0
        
        self.current_rating = rating
        self.ratingChanged.emit(rating)
        self.update()
