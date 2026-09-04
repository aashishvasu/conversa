"""App assembly: construct the FastAPI app and wire the routers in; every route lives in api/."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Before the api imports: their modules read provider keys and defaults from the environment at import time.
load_dotenv()

from api.auth import router as auth_router  # noqa: E402
from api.chat import router as chat_router  # noqa: E402
from api.research import router as research_router  # noqa: E402
from api.transfers import router as transfers_router  # noqa: E402

app = FastAPI(title="conversa")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(research_router)
app.include_router(transfers_router)

# Serve the built SPA in production (same origin, so no CORS needed).
# API lives under /api.
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
