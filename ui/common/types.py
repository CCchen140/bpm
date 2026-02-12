from typing import TypedDict, List, Optional, Any
from enum import Enum

class ViewMode(Enum):
    THUMBNAIL_ONLY = 0
    THUMBNAIL_FILE = 1
    THUMBNAIL_DETAIL = 2

class SortMode(Enum):
    FILENAME = 0
    DATE = 1
    RATING = 2
    SPECIES = 3
    SIZE = 4

class ImageFile(TypedDict):
    path: str
    filename: str
    date: Optional[str]
    rating: int
    species: Optional[str]
    file_size: int
    width: int
    height: int
    # Add other fields as needed

class GroupData(TypedDict):
    header_text: str
    images: List[ImageFile]
