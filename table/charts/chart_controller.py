from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from PyQt6.QtWidgets import QWidget


class ChartController(ABC):
    @property
    @abstractmethod
    def widget(self) -> QWidget: ...

    @abstractmethod
    def set_data(self, data: Any) -> None: ...

    @abstractmethod
    def set_theme(self, theme: Optional[str]) -> None: ...

    @abstractmethod
    def set_display_options(self, options: Dict[str, Any]) -> None: ...

    @abstractmethod
    def refresh(self) -> None: ...

