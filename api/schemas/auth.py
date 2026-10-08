from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from api.schemas.tenant import TenantResponse


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    id: int
    email: str
    token: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    tenant: Optional[TenantResponse] = None
