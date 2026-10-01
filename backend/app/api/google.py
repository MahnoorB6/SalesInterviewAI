from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import os
import secrets
from pathlib import Path

from app.services.google_oauth import (
    get_authorization_url,
    SCOPES,
)
from app.database.database import SessionLocal
from app.models.user import User
from app.auth import create_access_token, hash_password


router = APIRouter(
    prefix="/api/google",
    tags=["Google Calendar"],
)


# ============================================================
# TEMPORARY OAUTH SESSION STORAGE
# ============================================================

oauth_state = None
oauth_code_verifier = None


@router.get("/status")
def google_status():
    backend_directory = Path(__file__).resolve().parents[2]
    token_path = backend_directory / "token.json"
    return {"connected": token_path.exists()}


# ============================================================
# GOOGLE LOGIN
# ============================================================

@router.get("/login")
def google_login():

    (
        authorization_url,
        state,
        code_verifier,
    ) = get_authorization_url()

    response = RedirectResponse(url=authorization_url)
    response.set_cookie(key="google_oauth_state", value=state, httponly=True, samesite="lax", secure=False, max_age=600)
    response.set_cookie(key="google_oauth_code_verifier", value=code_verifier, httponly=True, samesite="lax", secure=False, max_age=600)
    return response


# ============================================================
# GOOGLE CALLBACK
# ============================================================

@router.get("/callback")
def google_callback(
    request: Request,
):

    # --------------------------------------------------------
    # GET GOOGLE PARAMETERS
    # --------------------------------------------------------

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Google authorization code is missing."
        )

    if not state:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth state is missing."
        )

    # --------------------------------------------------------
    # VERIFY STATE FROM OAUTH COOKIE
    # --------------------------------------------------------

    stored_state = request.cookies.get("google_oauth_state")
    code_verifier = request.cookies.get("google_oauth_code_verifier")

    if not stored_state or state != stored_state:
        raise HTTPException(
            status_code=400,
            detail="Invalid Google OAuth state."
        )

    if not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth code verifier is missing."
        )

    try:

        # ----------------------------------------------------
        # CREATE GOOGLE FLOW
        # ----------------------------------------------------

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": os.getenv(
                        "GOOGLE_CLIENT_ID"
                    ),

                    "client_secret": os.getenv(
                        "GOOGLE_CLIENT_SECRET"
                    ),

                    "auth_uri":
                        "https://accounts.google.com/o/oauth2/auth",

                    "token_uri":
                        "https://oauth2.googleapis.com/token",

                    "redirect_uris": [
                        os.getenv(
                            "GOOGLE_REDIRECT_URI"
                        )
                    ],
                }
            },
            scopes=SCOPES,
            state=stored_state,
            code_verifier=code_verifier,
        )

        # ----------------------------------------------------
        # SET REDIRECT URI
        # ----------------------------------------------------

        flow.redirect_uri = os.getenv(
            "GOOGLE_REDIRECT_URI"
        )

        # ----------------------------------------------------
        # EXCHANGE AUTHORIZATION CODE FOR TOKEN
        # ----------------------------------------------------

        flow.fetch_token(
            authorization_response=str(
                request.url
            )
        )

        credentials = flow.credentials

        if not credentials.id_token:
            raise HTTPException(
                status_code=400,
                detail="Google did not return an identity token."
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
                detail="Google account email could not be verified."
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

        # ----------------------------------------------------
        # FIND BACKEND DIRECTORY
        # ----------------------------------------------------

        backend_directory = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)
                )
            )
        )

        # ----------------------------------------------------
        # TOKEN FILE
        # ----------------------------------------------------

        token_path = os.path.join(
            backend_directory,
            "token.json"
        )

        # ----------------------------------------------------
        # SAVE GOOGLE TOKEN
        # ----------------------------------------------------

        with open(
            token_path,
            "w",
            encoding="utf-8",
        ) as token_file:

            token_file.write(
                credentials.to_json()
            )

        # ----------------------------------------------------
        # REDIRECT TO LOGIN PAGE
        # ----------------------------------------------------

        response = RedirectResponse(url=f"http://localhost:5173/?google_token={access_token}")
        response.delete_cookie("google_oauth_state")
        response.delete_cookie("google_oauth_code_verifier")
        return response

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Google authorization failed: "
                f"{str(error)}"
            ),
        )