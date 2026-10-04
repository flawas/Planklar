import uuid

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr

from app.db.models import Rolle


class UserRead(schemas.BaseUser[uuid.UUID]):
    buero_id: uuid.UUID
    rolle: Rolle


class UserCreate(schemas.BaseUserCreate):
    buero_id: uuid.UUID


class AdminUserCreate(BaseModel):
    """Neuer Benutzer im Büro des anlegenden Admins."""

    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """Teilweise Änderung eines Benutzers durch den Büro-Admin."""

    rolle: Rolle | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str
