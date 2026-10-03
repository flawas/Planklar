import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Buero(Base):
    """Mandant: Alle Daten gehören genau einem Büro."""

    __tablename__ = "buero"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="buero")


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    buero: Mapped[Buero] = relationship(back_populates="users")
