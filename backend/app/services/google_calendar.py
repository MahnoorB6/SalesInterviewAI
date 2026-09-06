import os
import uuid
from datetime import timedelta

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


# ============================================================
# CONFIGURATION
# ============================================================

TIMEZONE = "Asia/Karachi"

CALENDAR_ID = "primary"

TOKEN_FILE = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        )
    ),
    "token.json"
)


# ============================================================
# LOAD GOOGLE CREDENTIALS
# ============================================================

def get_google_credentials():

    if not os.path.exists(TOKEN_FILE):

        raise RuntimeError(
            "Google Calendar is not connected. "
            "Please connect Google Calendar first."
        )

    credentials = Credentials.from_authorized_user_file(
        TOKEN_FILE,
        scopes=[
            "https://www.googleapis.com/auth/calendar"
        ],
    )

    # --------------------------------------------------------
    # REFRESH TOKEN IF EXPIRED
    # --------------------------------------------------------

    if credentials.expired and credentials.refresh_token:

        credentials.refresh(
            Request()
        )

        # Save refreshed credentials
        with open(
            TOKEN_FILE,
            "w",
            encoding="utf-8",
        ) as token_file:

            token_file.write(
                credentials.to_json()
            )

    return credentials


# ============================================================
# CREATE GOOGLE CALENDAR SERVICE
# ============================================================

def get_calendar_service():

    credentials = get_google_credentials()

    service = build(
        "calendar",
        "v3",
        credentials=credentials,
    )

    return service


# ============================================================
# CREATE INTERVIEW EVENT
# ============================================================

def create_interview_event(
    candidate_name: str,
    candidate_email: str,
    scheduled_at,
    position: str = "Sales Representative",
    duration_minutes: int = 30,
):

    service = get_calendar_service()

    # --------------------------------------------------------
    # CALCULATE END TIME
    # --------------------------------------------------------

    end_time = scheduled_at + timedelta(
        minutes=duration_minutes
    )

    # --------------------------------------------------------
    # CREATE EVENT
    # --------------------------------------------------------

    event = {

        "summary": (
            f"Sales Interview - "
            f"{candidate_name}"
        ),

        "description": (
            "SalesInterviewAI interview "
            "conducted by Alena.\n\n"
            f"Position: {position}"
        ),

        "start": {
            "dateTime": scheduled_at.isoformat(),
            "timeZone": TIMEZONE,
        },

        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": TIMEZONE,
        },

        "attendees": [
            {
                "email": candidate_email,
            }
        ],

        "conferenceData": {

            "createRequest": {

                "requestId": (
                    f"salesinterviewai-"
                    f"{uuid.uuid4()}"
                ),

                "conferenceSolutionKey": {
                    "type": "hangoutsMeet"
                },
            }
        },
    }

    # --------------------------------------------------------
    # SEND EVENT TO GOOGLE
    # --------------------------------------------------------

    created_event = (
        service.events()
        .insert(
            calendarId=CALENDAR_ID,
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all",
        )
        .execute()
    )

    # --------------------------------------------------------
    # GET GOOGLE MEET LINK
    # --------------------------------------------------------

    meet_link = created_event.get(
        "hangoutLink"
    )

    # --------------------------------------------------------
    # FALLBACK: SEARCH CONFERENCE ENTRY POINTS
    # --------------------------------------------------------

    if not meet_link:

        conference_data = created_event.get(
            "conferenceData",
            {}
        )

        entry_points = conference_data.get(
            "entryPoints",
            []
        )

        for entry_point in entry_points:

            if entry_point.get("entryPointType") == "video":

                meet_link = entry_point.get(
                    "uri"
                )

                break

    # --------------------------------------------------------
    # VERIFY MEET LINK
    # --------------------------------------------------------

    if not meet_link:

        raise RuntimeError(
            "Google Calendar event was created, "
            "but Google Meet link was not generated."
        )

    # --------------------------------------------------------
    # RETURN EVENT INFORMATION
    # --------------------------------------------------------

    return {
        "event_id": created_event.get("id"),
        "meet_link": meet_link,
        "calendar_link": created_event.get(
            "htmlLink"
        ),
    }