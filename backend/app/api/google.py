from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import os
import secrets
import time
from pathlib import Path

from app.services.google_oauth import get_authorization_url, SCOPES
from app.database.database import SessionLocal
from app.models.user import User
from app.auth import create_access_token, hash_password
from app.config import settings
from pydantic import BaseModel

router = APIRouter(prefix="/api/google", tags=["Google Calendar"])
_oauth_codes: dict[str, tuple[str, float]] = {}


class OAuthCodeExchange(BaseModel):
    code: str



@router.get("/status")
def google_status():
    backend_directory = Path(__file__).resolve().parents[2]
    token_path = backend_directory / "token.json"
    return {"connected": token_path.exists()}


@router.get("/login")
def google_login():
    authorization_url, state, code_verifier = get_authorization_url()
    response = RedirectResponse(url=authorization_url)
    response.set_cookie(
        key="google_oauth_verifier",
        value=code_verifier,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=600,
        path="/",
    )
    response.set_cookie(
        key="google_oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=600,
        path="/",
    )
    return response


@router.get("/callback")
def google_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Google authorization code is missing.")

    if not state:
        raise HTTPException(status_code=400, detail="Google OAuth state is missing.")

    code_verifier = request.cookies.get("google_oauth_verifier")
    stored_state = request.cookies.get("google_oauth_state")

    if not stored_state or not secrets.compare_digest(state, stored_state):
        raise HTTPException(status_code=400, detail="Google OAuth state validation failed. Please restart sign-in.")

    if not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth session expired. Please click Connect Google again.",
        )

    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
                }
            },
            scopes=SCOPES,
            state=state,
            code_verifier=code_verifier,
        )

        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
        flow.fetch_token(authorization_response=str(request.url))
        credentials = flow.credentials

        if not credentials.id_token:
            raise HTTPException(
                status_code=400,
                detail="Google did not return an identity token.",
            )

        google_identity = id_token.verify_oauth2_token(
            credentials.id_token,
            GoogleRequest(),
            settings.GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=5,
        )

        google_email = google_identity.get("email")
        if not google_email:
            raise HTTPException(
                status_code=400,
                detail="Google account email could not be verified.",
            )

        db = SessionLocal()
        try:
            normalized_email = google_email.strip().lower()
            if settings.recruiter_email_allowlist and normalized_email not in settings.recruiter_email_allowlist:
                raise HTTPException(status_code=403, detail="This Google account is not authorized for the recruiter workspace.")
            user = db.query(User).filter(User.email == normalized_email).first()

            if not user:
                if normalized_email not in settings.recruiter_email_allowlist:
                    raise HTTPException(status_code=403, detail="Recruiter account is not provisioned. Configure the recruiter email allowlist.")
                user = User(
                    email=normalized_email,
                    hashed_password=hash_password(secrets.token_urlsafe(32)),
                )
                db.add(user)
                db.commit()
                db.refresh(user)

            access_token = create_access_token({"sub": user.email})
        finally:
            db.close()

        backend_directory = Path(__file__).resolve().parents[2]
        token_path = backend_directory / "token.json"

        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(credentials.to_json())

        exchange_code = secrets.token_urlsafe(32)
        _oauth_codes[exchange_code] = (access_token, time.time() + 60)
        response = RedirectResponse(url=f"{settings.FRONTEND_URL}/#oauth_code={exchange_code}")
        response.delete_cookie("google_oauth_state", path="/")
        response.delete_cookie("google_oauth_verifier", path="/")
        return response

    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Google OAuth callback failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail="Google authorization failed. Please restart sign-in.",
        )


@router.post("/exchange")
def exchange_google_code(payload: OAuthCodeExchange):
    item = _oauth_codes.pop(payload.code, None)
    now = time.time()
    for expired in [key for key, (_, expiry) in _oauth_codes.items() if expiry < now]:
        _oauth_codes.pop(expired, None)
    if not item or item[1] < now:
        raise HTTPException(status_code=401, detail="Google sign-in code expired or already used")
    return {"access_token": item[0], "token_type": "bearer"}
