from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import os
import secrets
from pathlib import Path

from app.services.google_oauth import get_authorization_url, SCOPES
from app.database.database import SessionLocal
from app.models.user import User
from app.auth import create_access_token, hash_password

router = APIRouter(prefix="/api/google", tags=["Google Calendar"])

# Local OAuth session storage. Keeps the PKCE verifier on the backend.
oauth_sessions = {}


@router.get("/status")
def google_status():
    backend_directory = Path(__file__).resolve().parents[2]
    token_path = backend_directory / "token.json"
    return {"connected": token_path.exists()}


@router.get("/login")
def google_login():
    authorization_url, state, code_verifier = get_authorization_url()
    oauth_sessions[state] = code_verifier

    response = RedirectResponse(url=authorization_url)
    response.set_cookie(
        key="google_oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        secure=False,
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

    code_verifier = oauth_sessions.pop(state, None)

    if not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth session expired. Please click Connect Google again.",
        )

    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI")],
                }
            },
            scopes=SCOPES,
            state=state,
            code_verifier=code_verifier,
        )

        flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
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
            os.getenv("GOOGLE_CLIENT_ID"),
        )

        google_email = google_identity.get("email")
        if not google_email:
            raise HTTPException(
                status_code=400,
                detail="Google account email could not be verified.",
            )

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == google_email).first()

            if not user:
                user = User(
                    email=google_email,
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

        response = RedirectResponse(
            url=f"http://localhost:5173/?google_token={access_token}"
        )
        response.delete_cookie("google_oauth_state", path="/")
        return response

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Google authorization failed: {error}",
        )
