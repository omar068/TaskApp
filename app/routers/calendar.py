from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.security import get_current_user
from app.db import get_session
from app.models import User, WorkspaceMember, Project, Task
from app.services.google_calendar import (
    list_google_calendar_events,
    create_google_calendar_event,
    update_google_calendar_event,
    delete_google_calendar_event,
)

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])


class CalendarEventCreate(BaseModel):
    title: str
    start: str
    end: Optional[str] = None
    description: str = ""
    category: str = "event"
    color: str = "emerald"


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    start: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None


@router.get("/events")
async def get_calendar_events(
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    google_events = await list_google_calendar_events(current_user, session, time_min, time_max)
    synced_google_ids = {ev["id"] for ev in google_events if ev.get("id")}

    memberships = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.user_id == current_user.id)
    ).all()
    ws_ids = [m.workspace_id for m in memberships]
    projects = (
        session.exec(select(Project).where(Project.workspace_id.in_(ws_ids))).all()
        if ws_ids
        else []
    )
    proj_map = {p.id: p for p in projects}

    tasks_with_dates = (
        session.exec(
            select(Task).where(
                Task.project_id.in_(list(proj_map.keys())),
                Task.due_date.is_not(None),
            )
        ).all()
        if proj_map
        else []
    )

    task_events = []
    for t in tasks_with_dates:
        if t.google_calendar_event_id and t.google_calendar_event_id in synced_google_ids:
            continue
        proj = proj_map.get(t.project_id)
        task_events.append(
            {
                "id": f"task-{t.id}",
                "task_id": t.id,
                "title": t.title,
                "description": t.description,
                "start": t.due_date.isoformat() if t.due_date else None,
                "end": t.due_date.isoformat() if t.due_date else None,
                "source": "taskapp",
                "priority": t.priority,
                "category": getattr(t, "category", "task") or "task",
                "color": getattr(t, "color", "indigo") or "indigo",
                "is_completed": t.is_completed,
                "project_name": proj.name if proj else "",
                "project_color": proj.color if proj else "#6366f1",
            }
        )

    return {
        "google_connected": bool(current_user.google_access_token),
        "events": google_events + task_events,
    }


@router.post("/events")
async def create_event(
    payload: CalendarEventCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not current_user.google_access_token:
        raise HTTPException(
            status_code=400,
            detail="Debes iniciar sesión con tu cuenta de Google para crear eventos directamente en Google Calendar, o crea una tarea con fecha límite en el tablero Kanban.",
        )
    ev = await create_google_calendar_event(
        current_user,
        session,
        title=payload.title,
        start_iso=payload.start,
        end_iso=payload.end,
        description=payload.description,
        category=payload.category,
        color=payload.color,
    )
    if not ev:
        raise HTTPException(
            status_code=502,
            detail="No se pudo crear el evento en Google Calendar. Verifica que Google Calendar API esté habilitada en tu consola de Google Cloud.",
        )
    return ev


@router.patch("/events/{event_id}")
async def edit_event(
    event_id: str,
    payload: CalendarEventUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if event_id.startswith("task-"):
        task_id = int(event_id.replace("task-", ""))
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Tarea no encontrada")
        if payload.title is not None:
            task.title = payload.title
        if payload.description is not None:
            task.description = payload.description
        if payload.category is not None:
            task.category = payload.category
        if payload.color is not None:
            task.color = payload.color
        if payload.start is not None:
            from datetime import datetime
            task.due_date = datetime.fromisoformat(payload.start.replace("Z", "+00:00"))
        session.add(task)
        session.commit()
        session.refresh(task)
        return {"ok": True}

    ev = await update_google_calendar_event(
        current_user,
        session,
        event_id=event_id,
        title=payload.title,
        start_iso=payload.start,
        description=payload.description,
        category=payload.category,
        color=payload.color,
    )
    if not ev:
        raise HTTPException(status_code=400, detail="No se pudo actualizar el evento")
    return ev


@router.delete("/events/{event_id}")
async def remove_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if event_id.startswith("task-"):
        task_id = int(event_id.replace("task-", ""))
        task = session.get(Task, task_id)
        if task:
            task.due_date = None
            session.add(task)
            session.commit()
        return {"ok": True}

    ok = await delete_google_calendar_event(current_user, event_id, session)
    if not ok:
        raise HTTPException(status_code=400, detail="No se pudo eliminar el evento de Google Calendar")
    return {"ok": True}
