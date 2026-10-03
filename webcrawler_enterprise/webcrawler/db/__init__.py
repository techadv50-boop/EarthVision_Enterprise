"""Database package."""

from webcrawler.db.database import Database
from webcrawler.db.duplicates import DuplicateManager
from webcrawler.db.frontier import FrontierStore

__all__ = ["Database", "DuplicateManager", "FrontierStore"]