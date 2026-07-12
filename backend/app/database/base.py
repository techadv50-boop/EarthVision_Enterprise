"""SQLAlchemy declarative base and model imports."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models.user import User, Role, Permission, user_roles, role_permissions  # noqa: E402, F401
from app.models.project import Project  # noqa: E402, F401
from app.models.bookmark import Bookmark  # noqa: E402, F401
from app.models.aoi import AreaOfInterest  # noqa: E402, F401
from app.models.scene import CachedScene  # noqa: E402, F401
from app.models.subscription import Subscription, APIKey  # noqa: E402, F401
from app.models.copernicus import CopernicusToken  # noqa: E402, F401
from app.models.analysis import AnalysisJob  # noqa: E402, F401
