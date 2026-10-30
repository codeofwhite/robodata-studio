from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ..services import episode_render_service
from ..services.worker_runtime import ResourceConflict

from ..models import QaUpdate
from ..services.episode_scanner import episode_detail, list_episodes, update_qa


router = APIRouter(tags=["episodes"])


@router.get("/episodes")
def index(
    session_id: str | None = None,
    dataset_id: int | None = None,
    qa_status: str | None = None,
    engine_id: str | None = None,
):
    if qa_status and qa_status not in {"pending", "accepted", "rejected"}:
        raise HTTPException(422, "invalid qa_status")
    if engine_id and engine_id not in {"genesis", "isaac_sim", "roboverse"}:
        raise HTTPException(422, "invalid engine_id")
    return list_episodes(
        session_id=session_id, dataset_id=dataset_id, qa_status=qa_status,
        engine_id=engine_id,
    )


@router.get("/episodes/{episode_id}")
def show(episode_id: int):
    episode = episode_detail(episode_id)
    if not episode:
        raise HTTPException(404, "episode not found")
    return episode


@router.patch("/episodes/{episode_id}/qa")
def qa(episode_id: int, payload: QaUpdate):
    episode = update_qa(episode_id, payload.qa_status, payload.failure_reason)
    if not episode:
        raise HTTPException(404, "episode not found")
    return episode


@router.get("/episodes/{episode_id}/frames/{camera}/{index}")
def frame(episode_id: int, camera: str, index: int):
    episode = episode_detail(episode_id)
    if not episode:
        raise HTTPException(404, "episode not found")
    cameras = episode["manifest"].get("camera_names", [])
    if camera not in cameras or index < 0 or index >= episode["num_frames"]:
        raise HTTPException(404, "frame not found")
    root = Path(episode["path"]).resolve()
    candidates = [
        root / f"{camera}_rgb" / f"{index:06d}.jpg",
        root / "images" / camera / f"{index:06d}.jpg",
        root / camera / f"{index:06d}.jpg",
    ]
    path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if path is None or not path.is_relative_to(root):
        raise HTTPException(404, "frame not found")
    return FileResponse(path, media_type="image/jpeg")


class IsaacRenderRequest(BaseModel):
    gpu: int = Field(ge=0, le=255)


@router.get('/episodes/{episode_id}/isaac-render')
def render_jobs(episode_id: int):
    return {'availability':episode_render_service.availability(episode_id),
            'jobs':episode_render_service.jobs(episode_id)}


@router.post('/episodes/{episode_id}/isaac-render', status_code=202)
def start_render(episode_id: int, payload: IsaacRenderRequest):
    try:
        return episode_render_service.start(episode_id, payload.gpu)
    except ResourceConflict as error:
        raise HTTPException(409, str(error)) from error
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
