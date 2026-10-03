import uuid

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr


class UserRead(schemas.BaseUser[uuid.UUID]):
    buero_id: uuid.UUID


class UserCreate(schemas.BaseUserCreate):
    buero_id: uuid.UUID


class AdminUserCreate(BaseModel):
    """Neuer Benutzer im Büro des anlegenden Admins."""

    email: EmailStr
    password: str
