"""Request/response models for authentication endpoints."""

import uuid

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    password: SecretStr  # SecretStr: never shown in logs or reprs

    @field_validator("password")
    @classmethod
    def _password_length(cls, value: SecretStr) -> SecretStr:
        if not 8 <= len(value.get_secret_value()) <= 72:
            raise ValueError("Password must be between 8 and 72 characters.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserInfo(BaseModel):
    id: uuid.UUID
    email: str | None


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"
    user: UserInfo


class SignupResponse(BaseModel):
    user: UserInfo
    session: SessionResponse | None
    email_confirmation_required: bool


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
