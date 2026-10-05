from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    full_name: str = Field(default="")
    avatar_url: Optional[str] = Field(default=None)
    google_sub: Optional[str] = Field(default=None, index=True, unique=True)
    google_access_token: Optional[str] = Field(default=None)
    google_refresh_token: Optional[str] = Field(default=None)
    token_expiry: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(index=True, unique=True)
    is_personal: bool = Field(default=False)
    owner_id: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utc_now)


class WorkspaceMember(SQLModel, table=True):
    __tablename__ = "workspace_members"

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspaces.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member")  # owner | admin | member
    joined_at: datetime = Field(default_factory=utc_now)


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspaces.id", index=True)
    name: str
    description: str = Field(default="")
    icon: str = Field(default="FolderKanban")
    color: str = Field(default="#6366f1")
    created_at: datetime = Field(default_factory=utc_now)


class KanbanColumn(SQLModel, table=True):
    __tablename__ = "kanban_columns"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    title: str
    position: int = Field(default=0)
    color: str = Field(default="#94a3b8")
    is_done_column: bool = Field(default=False)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    column_id: int = Field(foreign_key="kanban_columns.id", index=True)
    assignee_id: Optional[int] = Field(default=None, foreign_key="users.id")
    title: str
    description: str = Field(default="")
    content_blocks: List[dict] = Field(default_factory=list, sa_column=Column(JSON))
    priority: str = Field(default="medium")  # low | medium | high | urgent
    category: str = Field(default="task")  # task | meeting | milestone | personal | study
    color: str = Field(default="indigo")  # indigo | emerald | amber | rose | sky | violet | teal
    labels: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    position: int = Field(default=0)
    due_date: Optional[datetime] = Field(default=None)
    google_calendar_event_id: Optional[str] = Field(default=None)
    is_completed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Subtask(SQLModel, table=True):
    __tablename__ = "subtasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="tasks.id", index=True)
    title: str
    is_completed: bool = Field(default=False)
    position: int = Field(default=0)


class NoteFolder(SQLModel, table=True):
    __tablename__ = "note_folders"

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspaces.id", index=True)
    name: str
    icon: str = Field(default="📁")
    created_at: datetime = Field(default_factory=utc_now)


class Note(SQLModel, table=True):
    __tablename__ = "notes"

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspaces.id", index=True)
    folder_id: Optional[int] = Field(default=None, foreign_key="note_folders.id", index=True)
    project_id: Optional[int] = Field(default=None, foreign_key="projects.id", index=True)
    author_id: int = Field(foreign_key="users.id")
    title: str
    slug: str = Field(index=True, unique=True)
    summary: str = Field(default="")
    cover_emoji: str = Field(default="📝")
    content_blocks: List[dict] = Field(default_factory=list, sa_column=Column(JSON))
    is_public: bool = Field(default=False)
    published_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
