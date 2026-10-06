from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import re
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import create_access_token, get_current_user
from app.db import get_session
from app.models import (
    User,
    Workspace,
    WorkspaceMember,
    Project,
    KanbanColumn,
    Task,
    Subtask,
    Note,
)

router = APIRouter(tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar.events",
]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "workspace"


def ensure_user_default_workspace(user: User, session: Session) -> Workspace:
    """Ensures a new user gets a personal Workspace, a starter Project, 4 Kanban columns, a sample Task and a sample Note."""
    existing_ws = session.exec(
        select(Workspace).where(Workspace.owner_id == user.id)
    ).first()
    if existing_ws:
        # Ensure owner membership exists
        member = session.exec(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == existing_ws.id,
                WorkspaceMember.user_id == user.id,
            )
        ).first()
        if not member:
            session.add(WorkspaceMember(workspace_id=existing_ws.id, user_id=user.id, role="owner"))
            session.commit()
        return existing_ws

    import uuid
    base_slug = _slugify(user.full_name or user.email.split("@")[0])
    slug = f"{base_slug}-{user.id}"
    if session.exec(select(Workspace).where(Workspace.slug == slug)).first():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    ws = Workspace(
        name=f"Espacio de {user.full_name or user.email.split('@')[0]}",
        slug=slug,
        is_personal=True,
        owner_id=user.id,
    )
    session.add(ws)
    session.commit()
    session.refresh(ws)

    member = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner")
    session.add(member)

    project = Project(
        workspace_id=ws.id,
        name="Mi Proyecto Principal",
        description="Tablero Kanban conectado con Google Calendar y apuntes enriquecidos",
        icon="Rocket",
        color="#6366f1",
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    default_cols = [
        ("Por hacer", "#64748b", False),
        ("En progreso", "#3b82f6", False),
        ("En revisión", "#f59e0b", False),
        ("Completado", "#10b981", True),
    ]
    created_cols = []
    for idx, (title, color, is_done) in enumerate(default_cols):
        col = KanbanColumn(
            project_id=project.id,
            title=title,
            position=idx,
            color=color,
            is_done_column=is_done,
        )
        session.add(col)
        created_cols.append(col)
    session.commit()
    for col in created_cols:
        session.refresh(col)

    sample_task = Task(
        project_id=project.id,
        column_id=created_cols[0].id,
        assignee_id=user.id,
        title="Probar el nuevo tablero Kanban y comandos (/)",
        description="Haz clic en esta tarjeta para agregar subtareas, bloques de notas o una fecha de entrega para sincronizar con Google Calendar.",
        priority="high",
        labels=["Lanzamiento", "FastAPI + React"],
        position=0,
        content_blocks=[
            {"id": "b1", "type": "heading", "content": "Notas de la tarea"},
            {
                "id": "b2",
                "type": "paragraph",
                "content": "Puedes escribir '/' en el editor de apuntes para insertar encabezados, listas, código o checklists.",
            },
        ],
    )
    session.add(sample_task)
    session.commit()
    session.refresh(sample_task)

    session.add(
        Subtask(
            task_id=sample_task.id,
            title="Conectar cuenta de Google",
            is_completed=True,
            position=0,
        )
    )
    session.add(
        Subtask(
            task_id=sample_task.id,
            title="Arrastrar tarjeta entre columnas en PC, Tablet o Móvil",
            is_completed=False,
            position=1,
        )
    )

    note_slug = f"bienvenido-taskapp-{user.id}"
    if session.exec(select(Note).where(Note.slug == note_slug)).first():
        note_slug = f"{note_slug}-{uuid.uuid4().hex[:6]}"

    sample_note = Note(
        workspace_id=ws.id,
        project_id=project.id,
        author_id=user.id,
        title="Bienvenido a tus Apuntes & Blog en TaskApp",
        slug=note_slug,
        summary="Guía rápida para usar comandos por teclado (/), bloques enriquecidos y publicar notas como Blog.",
        cover_emoji="✨",
        is_public=True,
        published_at=datetime.now(timezone.utc),
        content_blocks=[
            {"id": "n1", "type": "h1", "content": "Tu espacio de trabajo todo en uno"},
            {
                "id": "n2",
                "type": "paragraph",
                "content": "Escribe '/' en cualquier línea vacía para abrir el menú rápido de comandos por teclado o usa atajos Markdown como '#', '-', '[]' o '```'.",
            },
            {
                "id": "n3",
                "type": "callout",
                "content": "Tip: Activa el interruptor 'Público (Blog)' arriba a la derecha para compartir cualquier apunte mediante un enlace de lectura.",
            },
            {
                "id": "n4",
                "type": "code",
                "content": "# TaskApp 2.0\nstack = ['FastAPI', 'SQLModel', 'React PWA', 'Google Calendar API']",
            },
        ],
    )
    session.add(sample_note)
    session.commit()
    return ws


def _get_redirect_uri(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    if "onrender.com" in base and base.startswith("http://"):
        base = base.replace("http://", "https://", 1)
    return f"{base}/accounts/google/login/callback/"


def _resolve_frontend_url(request: Request, state: str | None = None) -> str:
    if state and (state.startswith("http://") or state.startswith("https://")):
        return state.rstrip("/")
    origin = request.headers.get("origin")
    if origin and (origin.startswith("http://") or origin.startswith("https://")):
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if referer and (referer.startswith("http://") or referer.startswith("https://")):
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        return f"{parsed.scheme}://{parsed.netloc}"
    return settings.FRONTEND_URL.rstrip("/")


@router.get("/api/v1/auth/google/login")
def google_login(request: Request, frontend_url: str | None = None):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=400,
            detail="Falta configurar GOOGLE_CLIENT_ID en las variables de entorno",
        )
    caller_frontend = _resolve_frontend_url(request, frontend_url)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _get_redirect_uri(request),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": caller_frontend,
    }
    return {"auth_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@router.get("/accounts/google/login/callback/")
@router.get("/google/login/callback/")
@router.get("/api/v1/auth/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
):
    target_frontend = _resolve_frontend_url(request, state)
    if error or not code:
        return RedirectResponse(url=f"{target_frontend}/?error={error or 'missing_code'}")

    redirect_uri = _get_redirect_uri(request)
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse(url=f"{target_frontend}/?error=token_exchange_failed")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in", 3600))

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            return RedirectResponse(url=f"{target_frontend}/?error=userinfo_failed")

        profile = userinfo_resp.json()

    email = (profile.get("email") or "").strip().lower()
    google_sub = profile.get("sub")
    full_name = profile.get("name") or email.split("@")[0]
    avatar_url = profile.get("picture")

    user = session.exec(select(User).where(User.email == email)).first()
    if not user and google_sub:
        user = session.exec(select(User).where(User.google_sub == google_sub)).first()

    now = datetime.now(timezone.utc)
    if not user:
        user = User(
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
            google_sub=google_sub,
            google_access_token=access_token,
            google_refresh_token=refresh_token,
            token_expiry=now + timedelta(seconds=expires_in),
        )
        session.add(user)
    else:
        user.email = email or user.email
        user.full_name = full_name or user.full_name
        user.avatar_url = avatar_url or user.avatar_url
        user.google_sub = google_sub or user.google_sub
        user.google_access_token = access_token
        if refresh_token:
            user.google_refresh_token = refresh_token
        user.token_expiry = now + timedelta(seconds=expires_in)
        session.add(user)

    session.commit()
    session.refresh(user)
    try:
        ensure_user_default_workspace(user, session)
    except Exception:
        session.rollback()

    jwt_token = create_access_token(user.id, user.email)
    sep = "&" if "?" in target_frontend else "?"
    return RedirectResponse(url=f"{target_frontend}{sep}token={jwt_token}")


@router.get("/api/v1/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "avatar_url": current_user.avatar_url,
        "google_connected": bool(current_user.google_access_token),
    }
