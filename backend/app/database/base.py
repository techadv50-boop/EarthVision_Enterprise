"""SQLAlchemy declarative base and model imports."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models.user import (  # noqa: E402, F401
    User,
    Role,
    Permission,
    user_roles,
    role_permissions,
    user_journals,
)
from app.models.project import Project  # noqa: E402, F401
from app.models.bookmark import Bookmark  # noqa: E402, F401
from app.models.aoi import AreaOfInterest  # noqa: E402, F401
from app.models.scene import CachedScene  # noqa: E402, F401
from app.models.subscription import Subscription, APIKey  # noqa: E402, F401
from app.models.copernicus import CopernicusToken  # noqa: E402, F401
from app.models.analysis import AnalysisJob  # noqa: E402, F401
from app.models.citation import (  # noqa: E402, F401
    Journal,
    Issue,
    Article,
    ArticleChunk,
    CrawlJob,
    Manuscript,
    ManuscriptParagraph,
    CitationSuggestion,
    AuthorArticle,
    AuthorArticleChange,
    AuthorDbJournal,
    AuthorIssueSet,
    AuthorStoreFile,
)
from app.models.galley import GalleyJournal, GalleyProof, GalleySetting  # noqa: E402, F401
