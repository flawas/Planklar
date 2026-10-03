import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DokumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dossier_id: uuid.UUID
    dateiname: str
    sha256: str
    seitenzahl: int
    created_at: datetime
