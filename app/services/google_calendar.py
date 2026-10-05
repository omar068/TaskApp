from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import httpx
from sqlmodel import Session

from app.core.config import settings
from app.models import User, Task

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

# Mapeo entre los colores traslúcidos de TaskApp y los IDs de color oficiales de Google Calendar (colorId 1..11)
COLOR_TO_GOOGLE_ID: Dict[str, str] = {
    "indigo": "9",    # Blueberry
    "emerald": "2",   # Sage / Basil
    "amber": "5",     # Banana
    "rose": "11",     # Tomato / Flamingo
    "sky": "7",       # Peacock
    "violet": "3",    # Grape
    "teal": "10",     # Basil
}

GOOGLE_ID_TO_COLOR: Dict[str, str] = {v: k for k, v in COLOR_TO_GOOGLE_ID.items()}


async def get_valid_google_token(user: User, session: Session) -> Optional[str]:
    """Returns a valid Google access token, refreshing it via refresh_token if expired."""
    if not user.google_access_token:
        return None

    now = datetime.now(timezone.utc)
    expiry = user.token_expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if expiry and expiry > now + timedelta(minutes=2):
        return user.google_access_token

    if not user.google_refresh_token or not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return user.google_access_token

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": user.google_refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            user.google_access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
            user.token_expiry = now + timedelta(seconds=expires_in)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user.google_access_token

    return user.google_access_token


async def sync_task_to_google_calendar(user: User, task: Task, session: Session) -> Optional[str]:
    """Creates or updates a Google Calendar event when a task has a due_date, syncing its category and color."""
    token = await get_valid_google_token(user, session)
    if not token or not task.due_date:
        return None

    due = task.due_date
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    end_time = due + timedelta(hours=1)

    color_key = getattr(task, "color", "indigo") or "indigo"
    category_key = getattr(task, "category", "task") or "task"

    event_body = {
        "summary": task.title,
        "description": task.description or "Tarea sincronizada desde el tablero Kanban de TaskApp",
        "colorId": COLOR_TO_GOOGLE_ID.get(color_key, "9"),
        "extendedProperties": {
            "private": {
                "taskapp_category": category_key,
                "taskapp_color": color_key,
                "taskapp_task_id": str(task.id),
            }
        },
        "start": {"dateTime": due.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
    }

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        if task.google_calendar_event_id:
            resp = await client.patch(
                f"{GOOGLE_CALENDAR_BASE}/{task.google_calendar_event_id}",
                headers=headers,
                json=event_body,
            )
            if resp.status_code in (200, 201):
                return resp.json().get("id")

        resp = await client.post(GOOGLE_CALENDAR_BASE, headers=headers, json=event_body)
        if resp.status_code in (200, 201):
            return resp.json().get("id")
    return None


async def delete_google_calendar_event(user: User, event_id: str, session: Session) -> bool:
    token = await get_valid_google_token(user, session)
    if not token or not event_id:
        return False

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(f"{GOOGLE_CALENDAR_BASE}/{event_id}", headers=headers)
        return resp.status_code in (200, 204)


def _serialize_google_item(item: Dict[str, Any]) -> Dict[str, Any]:
    priv = item.get("extendedProperties", {}).get("private", {})
    g_color_id = str(item.get("colorId", ""))
    resolved_color = priv.get("taskapp_color") or GOOGLE_ID_TO_COLOR.get(g_color_id, "emerald")
    resolved_category = priv.get("taskapp_category", "event")
    return {
        "id": item.get("id"),
        "title": item.get("summary", "(Sin título)"),
        "description": item.get("description", ""),
        "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date"),
        "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
        "html_link": item.get("htmlLink"),
        "source": "google",
        "color": resolved_color,
        "category": resolved_category,
    }


async def list_google_calendar_events(
    user: User,
    session: Session,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> List[Dict[str, Any]]:
    token = await get_valid_google_token(user, session)
    if not token:
        return []

    now = datetime.now(timezone.utc)
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": time_min or (now - timedelta(days=45)).isoformat(),
        "timeMax": time_max or (now + timedelta(days=90)).isoformat(),
        "maxResults": 150,
    }
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GOOGLE_CALENDAR_BASE, headers=headers, params=params)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            return [_serialize_google_item(item) for item in items]
    return []


async def create_google_calendar_event(
    user: User,
    session: Session,
    title: str,
    start_iso: str,
    end_iso: Optional[str] = None,
    description: str = "",
    category: str = "event",
    color: str = "emerald",
) -> Optional[Dict[str, Any]]:
    token = await get_valid_google_token(user, session)
    if not token:
        return None

    if not end_iso:
        try:
            dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end_iso = (dt + timedelta(hours=1)).isoformat()
        except Exception:
            end_iso = start_iso

    event_body = {
        "summary": title,
        "description": description,
        "colorId": COLOR_TO_GOOGLE_ID.get(color, "2"),
        "extendedProperties": {
            "private": {
                "taskapp_category": category,
                "taskapp_color": color,
            }
        },
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
    }
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(GOOGLE_CALENDAR_BASE, headers=headers, json=event_body)
        if resp.status_code in (200, 201):
            return _serialize_google_item(resp.json())
    return None


async def update_google_calendar_event(
    user: User,
    session: Session,
    event_id: str,
    title: Optional[str] = None,
    start_iso: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    color: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    token = await get_valid_google_token(user, session)
    if not token:
        return None

    patch_body: Dict[str, Any] = {}
    if title is not None:
        patch_body["summary"] = title
    if description is not None:
        patch_body["description"] = description
    if color is not None:
        patch_body["colorId"] = COLOR_TO_GOOGLE_ID.get(color, "2")
    if category is not None or color is not None:
        priv: Dict[str, str] = {}
        if category is not None:
            priv["taskapp_category"] = category
        if color is not None:
            priv["taskapp_color"] = color
        patch_body["extendedProperties"] = {"private": priv}
    if start_iso is not None:
        try:
            dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end_iso = (dt + timedelta(hours=1)).isoformat()
        except Exception:
            end_iso = start_iso
        patch_body["start"] = {"dateTime": start_iso, "timeZone": "UTC"}
        patch_body["end"] = {"dateTime": end_iso, "timeZone": "UTC"}

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{GOOGLE_CALENDAR_BASE}/{event_id}",
            headers=headers,
            json=patch_body,
        )
        if resp.status_code in (200, 201):
            return _serialize_google_item(resp.json())
    return None
