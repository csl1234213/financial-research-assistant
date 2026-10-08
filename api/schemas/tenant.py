from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    created_at: datetime
