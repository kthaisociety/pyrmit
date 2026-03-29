import os
from dotenv import load_dotenv

# Must run before any module that reads env vars at import time
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from db.database import engine, Base
from dev_access import (
    is_access_gate_exempt_path,
    is_dev_access_enabled,
    request_has_dev_access,
)
from routers import access_gate, chat, auth, chunks, agents
from logging_config import setup_logging

setup_logging()

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI()


@app.middleware("http")
async def development_access_middleware(request, call_next):
    if (
        request.method != "OPTIONS"
        and is_dev_access_enabled()
        and not is_access_gate_exempt_path(request.url.path)
        and not request_has_dev_access(request)
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Access password required"},
        )

    return await call_next(request)

cors_allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(access_gate.router, prefix="/api/access-gate", tags=["access-gate"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(chunks.router, prefix="/api", tags=["chunks"])
app.include_router(agents.router, prefix="/api", tags=["agents"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the Building Permit Agent API"}
