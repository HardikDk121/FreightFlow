from pydantic import BaseModel, EmailStr, Field

from app.validators import Name, Password, Phone


class RegisterRequest(BaseModel):
    company_name: Name
    name: Name
    email: EmailStr
    password: Password
    phone: Phone | None = None


class LoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=254, description="Email or phone.")
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class AcceptInviteRequest(BaseModel):
    token: str
    name: Name
    password: Password
    phone: Phone | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ForgotPasswordRequest(BaseModel):
    login: str = Field(min_length=3, max_length=254, description="Email or phone.")


class ResetPasswordRequest(BaseModel):
    login: str = Field(min_length=3, max_length=254)
    code: str = Field(pattern=r"^[0-9]{6}$")
    new_password: Password


class RecoverEmailRequest(BaseModel):
    phone: Phone


class Accepted(BaseModel):
    message: str
