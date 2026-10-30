from fastapi import APIRouter, HTTPException

from ..adapters import engine_descriptors
from ..models import SessionCreate, SessionDeleteConfirm
from ..services.episode_scanner import scan_session
from ..services.session_service import (
    create_session,
    get_session,
    list_sessions,
    permanently_delete_session,
    restore_session,
    trash_session,
)
from ..services.worker_manager import worker_manager


router = APIRouter(tags=["sessions"])


@router.get("/adapters")
def adapters():
    return engine_descriptors()


@router.get("/engines")
def engines():
    return engine_descriptors()


@router.post("/sessions", status_code=201)
def create(payload: SessionCreate):
    try:
        return create_session(payload)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/sessions")
def index(include_trashed: bool = False):
    return list_sessions(include_trashed=include_trashed)


@router.get("/sessions/{session_id}")
def show(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    return session


@router.post("/sessions/{session_id}/scan")
def scan(session_id: str):
    try:
        return scan_session(session_id)
    except KeyError:
        raise HTTPException(404, "session not found") from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/sessions/{session_id}/workers/start")
def start(session_id: str):
    try:
        return worker_manager.start(session_id)
    except KeyError:
        raise HTTPException(404, "session not found") from None
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(409, str(error)) from error


@router.get("/sessions/{session_id}/workers/status")
def worker_status(session_id: str):
    try:
        return worker_manager.status(session_id)
    except KeyError:
        raise HTTPException(404, "session not found") from None


@router.post("/sessions/{session_id}/workers/stop")
def stop(session_id: str):
    try:
        return worker_manager.stop(session_id)
    except KeyError:
        raise HTTPException(404, "session not found") from None


@router.post("/sessions/{session_id}/trash")
def trash(session_id: str):
    if worker_manager.is_running(session_id):
        raise HTTPException(409, "stop the session worker before moving it to trash")
    try:
        return trash_session(session_id)
    except KeyError:
        raise HTTPException(404, "session not found") from None
    except (OSError, ValueError) as error:
        raise HTTPException(409, str(error)) from error


@router.post("/sessions/{session_id}/restore")
def restore(session_id: str):
    try:
        return restore_session(session_id)
    except KeyError:
        raise HTTPException(404, "session not found") from None
    except (OSError, ValueError) as error:
        raise HTTPException(409, str(error)) from error


@router.delete("/sessions/{session_id}")
def delete(session_id: str, payload: SessionDeleteConfirm):
    if worker_manager.is_running(session_id):
        raise HTTPException(409, "stop the session worker before deleting it")
    try:
        return permanently_delete_session(
            session_id,
            confirm_session_id=payload.confirm_session_id,
            delete_accepted_data=payload.delete_accepted_data,
        )
    except KeyError:
        raise HTTPException(404, "session not found") from None
    except (OSError, ValueError) as error:
        raise HTTPException(409, str(error)) from error
