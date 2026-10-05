from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.security import get_current_user
from app.db import get_session
from app.models import (
    User,
    WorkspaceMember,
    Project,
    KanbanColumn,
    Task,
    Subtask,
)
from app.services.google_calendar import (
    sync_task_to_google_calendar,
    delete_google_calendar_event,
)

router = APIRouter(prefix="/api/v1", tags=["projects & kanban"])


class ProjectCreate(BaseModel):
    workspace_id: int
    name: str
    description: str = ""
    icon: str = "FolderKanban"
    color: str = "#6366f1"


class ColumnCreate(BaseModel):
    title: str
    color: str = "#64748b"
    is_done_column: bool = False


class TaskCreate(BaseModel):
    project_id: int
    column_id: int
    title: str
    description: str = ""
    priority: str = "medium"
    category: str = "task"
    color: str = "indigo"
    labels: List[str] = []
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None
    content_blocks: List[dict] = []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_id: Optional[int] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    labels: Optional[List[str]] = None
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None
    position: Optional[int] = None
    is_completed: Optional[bool] = None
    content_blocks: Optional[List[dict]] = None


class SubtaskCreate(BaseModel):
    title: str


class SubtaskUpdate(BaseModel):
    title: Optional[str] = None
    is_completed: Optional[bool] = None


def _verify_project_access(project_id: int, user_id: int, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == project.workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Sin acceso a este proyecto")
    return project


@router.post("/projects")
def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == payload.workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Sin acceso al espacio de trabajo")

    project = Project(
        workspace_id=payload.workspace_id,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        color=payload.color,
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    for idx, (title, color, is_done) in enumerate(
        [
            ("Por hacer", "#64748b", False),
            ("En progreso", "#3b82f6", False),
            ("En revisión", "#f59e0b", False),
            ("Completado", "#10b981", True),
        ]
    ):
        session.add(
            KanbanColumn(
                project_id=project.id,
                title=title,
                position=idx,
                color=color,
                is_done_column=is_done,
            )
        )
    session.commit()
    return project


@router.get("/projects/{project_id}/board")
def get_project_board(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = _verify_project_access(project_id, current_user.id, session)
    columns = session.exec(
        select(KanbanColumn)
        .where(KanbanColumn.project_id == project_id)
        .order_by(KanbanColumn.position)
    ).all()
    tasks = session.exec(
        select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.position, Task.created_at.desc())
    ).all()

    task_ids = [t.id for t in tasks]
    subtasks = (
        session.exec(select(Subtask).where(Subtask.task_id.in_(task_ids)).order_by(Subtask.position)).all()
        if task_ids
        else []
    )
    subtasks_by_task = {}
    for st in subtasks:
        subtasks_by_task.setdefault(st.task_id, []).append(st)

    members = session.exec(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == project.workspace_id)
    ).all()
    users_by_id = {u.id: u for u in members}

    enriched_tasks = []
    for t in tasks:
        assignee = users_by_id.get(t.assignee_id) if t.assignee_id else None
        enriched_tasks.append(
            {
                "id": t.id,
                "project_id": t.project_id,
                "column_id": t.column_id,
                "title": t.title,
                "description": t.description,
                "content_blocks": t.content_blocks or [],
                "priority": t.priority,
                "category": getattr(t, "category", "task") or "task",
                "color": getattr(t, "color", "indigo") or "indigo",
                "labels": t.labels or [],
                "position": t.position,
                "due_date": t.due_date,
                "google_calendar_event_id": t.google_calendar_event_id,
                "is_completed": t.is_completed,
                "assignee_id": t.assignee_id,
                "assignee": (
                    {
                        "id": assignee.id,
                        "full_name": assignee.full_name,
                        "email": assignee.email,
                        "avatar_url": assignee.avatar_url,
                    }
                    if assignee
                    else None
                ),
                "subtasks": subtasks_by_task.get(t.id, []),
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
        )

    return {
        "project": project,
        "columns": columns,
        "tasks": enriched_tasks,
        "members": [
            {
                "id": u.id,
                "full_name": u.full_name,
                "email": u.email,
                "avatar_url": u.avatar_url,
            }
            for u in members
        ],
    }


@router.post("/projects/{project_id}/columns")
def create_column(
    project_id: int,
    payload: ColumnCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _verify_project_access(project_id, current_user.id, session)
    existing_cols = session.exec(
        select(KanbanColumn).where(KanbanColumn.project_id == project_id)
    ).all()
    col = KanbanColumn(
        project_id=project_id,
        title=payload.title,
        color=payload.color,
        is_done_column=payload.is_done_column,
        position=len(existing_cols),
    )
    session.add(col)
    session.commit()
    session.refresh(col)
    return col


@router.post("/tasks")
async def create_task(
    payload: TaskCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _verify_project_access(payload.project_id, current_user.id, session)
    col = session.get(KanbanColumn, payload.column_id)
    is_done = bool(col and col.is_done_column)

    task = Task(
        project_id=payload.project_id,
        column_id=payload.column_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        category=payload.category,
        color=payload.color,
        labels=payload.labels,
        assignee_id=payload.assignee_id or current_user.id,
        due_date=payload.due_date,
        content_blocks=payload.content_blocks,
        is_completed=is_done,
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    if task.due_date:
        event_id = await sync_task_to_google_calendar(current_user, task, session)
        if event_id:
            task.google_calendar_event_id = event_id
            session.add(task)
            session.commit()
            session.refresh(task)

    return task


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    _verify_project_access(task.project_id, current_user.id, session)

    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(task, k, v)

    if "column_id" in update_data:
        col = session.get(KanbanColumn, task.column_id)
        if col:
            task.is_completed = col.is_done_column

    task.updated_at = datetime.now(timezone.utc)
    session.add(task)
    session.commit()
    session.refresh(task)

    if any(k in update_data for k in ("due_date", "title", "description", "color", "category")):
        if task.due_date:
            event_id = await sync_task_to_google_calendar(current_user, task, session)
            if event_id and event_id != task.google_calendar_event_id:
                task.google_calendar_event_id = event_id
                session.add(task)
                session.commit()
                session.refresh(task)

    return task


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    _verify_project_access(task.project_id, current_user.id, session)

    if task.google_calendar_event_id:
        await delete_google_calendar_event(current_user, task.google_calendar_event_id, session)

    subtasks = session.exec(select(Subtask).where(Subtask.task_id == task_id)).all()
    for st in subtasks:
        session.delete(st)

    session.delete(task)
    session.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/subtasks")
def create_subtask(
    task_id: int,
    payload: SubtaskCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    _verify_project_access(task.project_id, current_user.id, session)

    existing = session.exec(select(Subtask).where(Subtask.task_id == task_id)).all()
    st = Subtask(task_id=task_id, title=payload.title, position=len(existing))
    session.add(st)
    session.commit()
    session.refresh(st)
    return st


@router.patch("/subtasks/{subtask_id}")
def update_subtask(
    subtask_id: int,
    payload: SubtaskUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    st = session.get(Subtask, subtask_id)
    if not st:
        raise HTTPException(status_code=404, detail="Subtarea no encontrada")
    task = session.get(Task, st.task_id)
    _verify_project_access(task.project_id, current_user.id, session)

    if payload.title is not None:
        st.title = payload.title
    if payload.is_completed is not None:
        st.is_completed = payload.is_completed
    session.add(st)
    session.commit()
    session.refresh(st)
    return st


@router.delete("/subtasks/{subtask_id}")
def delete_subtask(
    subtask_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    st = session.get(Subtask, subtask_id)
    if not st:
        raise HTTPException(status_code=404, detail="Subtarea no encontrada")
    task = session.get(Task, st.task_id)
    _verify_project_access(task.project_id, current_user.id, session)
    session.delete(st)
    session.commit()
    return {"ok": True}
