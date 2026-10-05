from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import init_db
from app.routers import auth, workspaces, projects, notes, calendar


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="2.0.0",
    description="API moderna de TaskApp con Workspaces, Tableros Kanban, Apuntes con comandos (/), Blog público y sincronización con Google Calendar.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(projects.router)
app.include_router(notes.router)
app.include_router(calendar.router)


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "version": "2.0.0",
        "docs": "/docs",
    }
