import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, EmailStr

from app.db.models import Rolle


class UserRead(schemas.BaseUser[uuid.UUID]):
    buero_id: uuid.UUID


class UserCreate(schemas.BaseUserCreate):
    buero_id: uuid.UUID


class AdminUserCreate(BaseModel):
    """Neuer Benutzer im Büro des anlegenden Admins."""

    email: EmailStr
    password: str


class EinladungCreate(BaseModel):
    email: EmailStr
    rolle: Rolle = Rolle.MITARBEITER


class EinladungRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    rolle: Rolle
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


class TokenEinloesen(BaseModel):
    token: str
    password: str


class ResetAnfrage(BaseModel):
    email: EmailStr
