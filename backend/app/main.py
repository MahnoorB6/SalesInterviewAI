import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.candidates import router as candidates_router
from app.api.interviews import router as interviews_router
from app.api.evaluations import router as evaluations_router
from app.api.dashboard import router as dashboard_router
from app.api.auth import router as auth_router
from app.api.google import router as google_router

from app.services.scheduler import start_scheduler


app = FastAPI(
    title="SalesInterviewAI",
    description="AI Sales Interview Platform with Alena",
    version="1.0.0",
)


# ============================================================
# SESSION MIDDLEWARE
# ============================================================

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv(
        "SESSION_SECRET_KEY",
        "salesinterviewai-dev-secret-change-this",
    ),
    same_site="lax",
    https_only=False,
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
   allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTERS
# ============================================================

app.include_router(candidates_router)
app.include_router(interviews_router)
app.include_router(evaluations_router)
app.include_router(dashboard_router)
app.include_router(auth_router)
app.include_router(google_router)


# ============================================================
# SCHEDULER STARTUP
# ============================================================

@app.on_event("startup")
async def startup_event():

    print("=" * 70)
    print("SalesInterviewAI Backend Starting")
    print("=" * 70)

    start_scheduler()

    print("[STARTUP] Interview scheduler started.")
    print("[STARTUP] Alena automation is ready.")


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "message": "SalesInterviewAI backend is running",
        "interviewer": "Alena",
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "healthy",
        "service": "SalesInterviewAI",
        "interviewer": "Alena",
    }