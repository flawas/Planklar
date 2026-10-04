import uuid
from datetime import datetime
from decimal import Decimal

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, EmailStr, Field

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


class UserUpdate(BaseModel):
    """Teilweise Änderung eines Benutzers durch den Büro-Admin."""

    rolle: Rolle | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class BueroCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    admin_email: EmailStr


class BueroUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aktiv: bool | None = None


class BueroRead(BaseModel):
    """Nur Metadaten."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    aktiv: bool
    benutzer: int
    dossiers: int


class ModellNutzungRead(BaseModel):
    modell: str
    aufrufe: int
    input_tokens: int
    output_tokens: int
    kosten_usd: Decimal
    ohne_preis: int


class BueroNutzungRead(BaseModel):
    """Verbrauch eines Büros im Monat; nur Zähler, keine Inhalte."""

    buero_id: uuid.UUID
    buero: str
    aufrufe: int
    input_tokens: int
    output_tokens: int
    kosten_usd: Decimal
    modelle: list[ModellNutzungRead]
