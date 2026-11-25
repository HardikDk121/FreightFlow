from pydantic import BaseModel, EmailStr, Field

from app.validators import BusinessName, NewPassword, PersonName, Phone


class RegisterRequest(BaseModel):
    company_name: BusinessName
    name: PersonName
    email: EmailStr
    password: NewPassword
    phone: Phone | None = None
    # The code emailed by POST /auth/register/code, when email verification is on.
    email_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeSent(BaseModel):
    required: bool
    expires_in: int | None = None
    resend_after: int | None = None


class LoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=254, description="Email or phone.")
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class AcceptInviteRequest(BaseModel):
    token: str
    name: PersonName
    password: NewPassword
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
    new_password: NewPassword


class RecoverEmailRequest(BaseModel):
    phone: Phone


class Accepted(BaseModel):
    message: str
