from datetime import datetime, timezone
from typing import Optional, List
import re
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.security import get_current_user
from app.db import get_session
from app.models import User, WorkspaceMember, Note, NoteFolder

router = APIRouter(prefix="/api/v1", tags=["notes & blog"])


class FolderCreate(BaseModel):
    workspace_id: int
    name: str
    icon: str = "📁"


class NoteCreate(BaseModel):
    workspace_id: int
    folder_id: Optional[int] = None
    project_id: Optional[int] = None
    title: str = "Sin título"
    summary: str = ""
    cover_emoji: str = "📝"
    content_blocks: List[dict] = []
    is_public: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    cover_emoji: Optional[str] = None
    folder_id: Optional[int] = None
    project_id: Optional[int] = None
    content_blocks: Optional[List[dict]] = None
    is_public: Optional[bool] = None


def _slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "apunte"
    return f"{base}-{uuid.uuid4().hex[:6]}"


@router.get("/note-folders")
def list_folders(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Sin acceso a este espacio")

    return session.exec(
        select(NoteFolder)
        .where(NoteFolder.workspace_id == workspace_id)
        .order_by(NoteFolder.created_at)
    ).all()


@router.post("/note-folders")
def create_folder(
    payload: FolderCreate,
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
        raise HTTPException(status_code=403, detail="Sin acceso a este espacio")

    folder = NoteFolder(
        workspace_id=payload.workspace_id,
        name=payload.name,
        icon=payload.icon or "📁",
    )
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return folder


@router.delete("/note-folders/{folder_id}")
def delete_folder(
    folder_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    folder = session.get(NoteFolder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")

    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == folder.workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Sin permiso")

    notes_in_folder = session.exec(
        select(Note).where(Note.folder_id == folder_id)
    ).all()
    for n in notes_in_folder:
        n.folder_id = None
        session.add(n)

    session.delete(folder)
    session.commit()
    return {"ok": True}


@router.get("/notes")
def list_notes(
    workspace_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    memberships = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.user_id == current_user.id)
    ).all()
    allowed_ws = [m.workspace_id for m in memberships]
    if not allowed_ws:
        return []

    query = select(Note).where(Note.workspace_id.in_(allowed_ws))
    if workspace_id:
        if workspace_id not in allowed_ws:
            raise HTTPException(status_code=403, detail="Sin acceso a este espacio")
        query = query.where(Note.workspace_id == workspace_id)

    return session.exec(query.order_by(Note.updated_at.desc())).all()


@router.post("/notes")
def create_note(
    payload: NoteCreate,
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

    now = datetime.now(timezone.utc)
    note = Note(
        workspace_id=payload.workspace_id,
        folder_id=payload.folder_id,
        project_id=payload.project_id,
        author_id=current_user.id,
        title=payload.title,
        slug=_slugify(payload.title),
        summary=payload.summary,
        cover_emoji=payload.cover_emoji,
        content_blocks=payload.content_blocks
        or [{"id": "b-init", "type": "paragraph", "content": ""}],
        is_public=payload.is_public,
        published_at=now if payload.is_public else None,
        created_at=now,
        updated_at=now,
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.patch("/notes/{note_id}")
def update_note(
    note_id: int,
    payload: NoteUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    note = session.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == note.workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Sin permiso para editar esta nota")

    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(note, k, v)

    if payload.is_public is True and not note.published_at:
        note.published_at = datetime.now(timezone.utc)

    note.updated_at = datetime.now(timezone.utc)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.delete("/notes/{note_id}")
def delete_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    note = session.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == note.workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Sin permiso")

    session.delete(note)
    session.commit()
    return {"ok": True}


@router.get("/blog")
def list_public_blog_posts(session: Session = Depends(get_session)):
    notes = session.exec(
        select(Note, User)
        .join(User, User.id == Note.author_id)
        .where(Note.is_public == True)
        .order_by(Note.published_at.desc())
    ).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "slug": n.slug,
            "summary": n.summary,
            "cover_emoji": n.cover_emoji,
            "published_at": n.published_at,
            "updated_at": n.updated_at,
            "author": {
                "full_name": u.full_name,
                "avatar_url": u.avatar_url,
            },
        }
        for n, u in notes
    ]


@router.get("/blog/{slug}")
def get_public_blog_post(slug: str, session: Session = Depends(get_session)):
    row = session.exec(
        select(Note, User)
        .join(User, User.id == Note.author_id)
        .where(Note.slug == slug, Note.is_public == True)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Publicación no encontrada o es privada")
    note, author = row
    return {
        "id": note.id,
        "title": note.title,
        "slug": note.slug,
        "summary": note.summary,
        "cover_emoji": note.cover_emoji,
        "content_blocks": note.content_blocks,
        "published_at": note.published_at,
        "updated_at": note.updated_at,
        "author": {
            "full_name": author.full_name,
            "avatar_url": author.avatar_url,
        },
    }
