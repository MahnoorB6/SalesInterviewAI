
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field

from app.database.database import get_db
from app.models.user import User
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
)
from app.config import settings


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=72)


@router.post("/register")
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    normalized_email = str(payload.email).strip().lower()
    if normalized_email not in settings.recruiter_email_allowlist:
        raise HTTPException(status_code=403, detail="Email is not authorized to register a recruiter account")
    existing_user = db.query(User).first()

    if existing_user:
        raise HTTPException(
            status_code=403,
            detail="Registration is disabled. Only one authorized user is allowed.",
        )

    new_user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "Authorized user created successfully",
        "user_id": new_user.id,
        "email": new_user.email,
    }


@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == form_data.username.strip().lower())
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    if not verify_password(
        form_data.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    access_token = create_access_token(
        data={
            "sub": user.email,
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }

