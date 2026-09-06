import os

from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


# ============================================================
# GOOGLE CALENDAR PERMISSIONS
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/calendar"
]


# ============================================================
# CREATE GOOGLE OAUTH FLOW
# ============================================================

def create_google_flow():

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")

    if not client_id:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID is missing from .env"
        )

    if not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_SECRET is missing from .env"
        )

    if not redirect_uri:
        raise RuntimeError(
            "GOOGLE_REDIRECT_URI is missing from .env"
        )

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri":
                    "https://accounts.google.com/o/oauth2/auth",
                "token_uri":
                    "https://oauth2.googleapis.com/token",
                "redirect_uris": [
                    redirect_uri
                ],
            }
        },
        scopes=SCOPES,
    )

    flow.redirect_uri = redirect_uri

    return flow


# ============================================================
# GET GOOGLE AUTHORIZATION URL
# ============================================================

def get_authorization_url():

    flow = create_google_flow()

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    return (
        authorization_url,
        state,
        flow.code_verifier,
    )