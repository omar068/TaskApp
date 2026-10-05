import re
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.security import get_current_user
from app.db import get_session
from app.models import User, Workspace, WorkspaceMember, Project, KanbanColumn

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str
    is_personal: bool = False


class MemberInvite(BaseModel):
    email: str
    role: str = "member"


class JoinByCodeRequest(BaseModel):
    invite_code: str


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "grupo"


@router.get("")
def list_workspaces(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    memberships = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.user_id == current_user.id)
    ).all()
    ws_ids = [m.workspace_id for m in memberships]
    if not ws_ids:
        return []

    workspaces = session.exec(select(Workspace).where(Workspace.id.in_(ws_ids))).all()
    result = []
    for ws in workspaces:
        members = session.exec(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == ws.id)
        ).all()
        projects = session.exec(
            select(Project).where(Project.workspace_id == ws.id)
        ).all()
        result.append(
            {
                "id": ws.id,
                "name": ws.name,
                "slug": ws.slug,
                "is_personal": ws.is_personal,
                "owner_id": ws.owner_id,
                "projects": projects,
                "members": [
                    {
                        "id": u.id,
                        "email": u.email,
                        "full_name": u.full_name,
                        "avatar_url": u.avatar_url,
                        "role": m.role,
                    }
                    for m, u in members
                ],
            }
        )
    return result


@router.post("")
def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    base_slug = _slugify(payload.name)
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    ws = Workspace(
        name=payload.name,
        slug=slug,
        is_personal=payload.is_personal,
        owner_id=current_user.id,
    )
    session.add(ws)
    session.commit()
    session.refresh(ws)

    session.add(WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role="owner"))

    project = Project(
        workspace_id=ws.id,
        name="Tablero del Equipo",
        description=f"Proyecto colaborativo de {ws.name}",
        icon="Users",
        color="#8b5cf6",
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
    return ws


@router.post("/join")
def join_workspace_by_code(
    payload: JoinByCodeRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    code = payload.invite_code.strip().lower()
    ws = session.exec(select(Workspace).where(Workspace.slug == code)).first()
    if not ws:
        raise HTTPException(
            status_code=404,
            detail="No se encontró ningún grupo con ese código de invitación.",
        )

    existing = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not existing:
        ws.is_personal = False
        session.add(ws)
        session.add(
            WorkspaceMember(
                workspace_id=ws.id,
                user_id=current_user.id,
                role="member",
            )
        )
        session.commit()

    return {"ok": True, "workspace_id": ws.id, "name": ws.name}


@router.post("/{workspace_id}/members")
def invite_member(
    workspace_id: int,
    payload: MemberInvite,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    membership = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="No tienes acceso a este grupo")

    clean_email = payload.email.strip().lower()
    target_user = session.exec(select(User).where(User.email == clean_email)).first()
    if not target_user:
        target_user = User(
            email=clean_email,
            full_name=clean_email.split("@")[0],
            avatar_url=f"https://api.dicebear.com/7.x/initials/svg?seed={clean_email}",
        )
        session.add(target_user)
        session.commit()
        session.refresh(target_user)

    ws = session.get(Workspace, workspace_id)
    if ws and ws.is_personal:
        ws.is_personal = False
        session.add(ws)

    existing = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target_user.id,
        )
    ).first()
    if existing:
        session.commit()
        return {
            "id": target_user.id,
            "email": target_user.email,
            "full_name": target_user.full_name,
            "avatar_url": target_user.avatar_url,
            "role": existing.role,
        }

    new_member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=payload.role,
    )
    session.add(new_member)
    session.commit()
    return {
        "id": target_user.id,
        "email": target_user.email,
        "full_name": target_user.full_name,
        "avatar_url": target_user.avatar_url,
        "role": new_member.role,
    }


@router.delete("/{workspace_id}/members/{member_user_id}")
def remove_member(
    workspace_id: int,
    member_user_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    membership = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="No tienes acceso a este grupo")

    target_membership = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == member_user_id,
        )
    ).first()
    if not target_membership:
        raise HTTPException(status_code=404, detail="Miembro no encontrado")
    if target_membership.role == "owner":
        raise HTTPException(status_code=400, detail="No se puede eliminar al propietario del grupo")

    session.delete(target_membership)
    session.commit()
    return {"ok": True}
