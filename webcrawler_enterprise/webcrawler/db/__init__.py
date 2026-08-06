"""Database package."""

from webcrawler.db.database import Database
from webcrawler.db.duplicates import DuplicateManager

__all__ = ["Database", "DuplicateManager"]
