import os
from dotenv import load_dotenv

# Must run before any module that reads env vars at import time
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.database import engine, Base
from routers import chat, auth, chunks, agents

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Specific origin needed for credentials (cookies)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(chunks.router, prefix="/api", tags=["chunks"])
app.include_router(agents.router, prefix="/api", tags=["agents"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the Building Permit Agent API"}
