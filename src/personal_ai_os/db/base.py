"""SQLAlchemy declarative metadata for product domain models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base metadata shared by the modular monolith."""


# Import model modules after Base exists so Alembic sees their metadata.
from personal_ai_os.conversations import models as conversation_models  # noqa: E402, F401
from personal_ai_os.identity import models as identity_models  # noqa: E402, F401
from personal_ai_os.tools import models as tool_models  # noqa: E402, F401
