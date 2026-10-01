from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
import os
from pathlib import Path

from app.services.google_oauth import (
    get_authorization_url,
    SCOPES,
)


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

    global oauth_state
    global oauth_code_verifier

    (
        authorization_url,
        state,
        code_verifier,
    ) = get_authorization_url()

    oauth_state = state
    oauth_code_verifier = code_verifier

    return RedirectResponse(
        url=authorization_url
    )


# ============================================================
# GOOGLE CALLBACK
# ============================================================

@router.get("/callback")
def google_callback(
    request: Request,
):

    global oauth_state
    global oauth_code_verifier

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
    # VERIFY STATE
    # --------------------------------------------------------

    if state != oauth_state:
        raise HTTPException(
            status_code=400,
            detail="Invalid Google OAuth state."
        )

    # --------------------------------------------------------
    # VERIFY CODE VERIFIER
    # --------------------------------------------------------

    if not oauth_code_verifier:
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
            state=state,
            code_verifier=oauth_code_verifier,
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
        # CLEAR TEMPORARY OAUTH DATA
        # ----------------------------------------------------

        oauth_state = None
        oauth_code_verifier = None

        # ----------------------------------------------------
        # REDIRECT TO LOGIN PAGE
        # ----------------------------------------------------

        return RedirectResponse(
    url="http://localhost:5173/login.html"
)

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Google authorization failed: "
                f"{str(error)}"
            ),
        )