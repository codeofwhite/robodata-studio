from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..services import cloth_generation_service as service
from ..services.worker_manager import worker_manager
from .generation import StartRequest, call

router = APIRouter(prefix='/cloth-generation', tags=['cloth-generation'])


from robot_data_contracts.pbr_material import AppearanceVariant as AppearanceRequest


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    episode_ids: list[int] = Field(min_length=1, max_length=20)
    appearances: list[AppearanceRequest] = Field(min_length=1, max_length=20)


@router.get('/sources')
def sources():
    return call(service.sources)


@router.post('/plans', status_code=201)
def preview(payload: PreviewRequest):
    return call(service.preview, payload.model_dump())


@router.get('/plans/{plan_id}')
def plan(plan_id: str):
    return call(service.get_plan, plan_id)


@router.post('/plans/{plan_id}/start')
def start(plan_id: str, payload: StartRequest):
    return call(service.start, plan_id, payload.model_dump())


@router.get('/jobs')
def jobs():
    return call(service.jobs)


@router.get('/jobs/{session_id}')
def job(session_id: str):
    return call(service.job, session_id)


@router.post('/jobs/{session_id}/stop')
def stop(session_id: str):
    call(service.job, session_id)
    return call(worker_manager.stop, session_id)


@router.post('/jobs/{session_id}/scan')
def scan(session_id: str):
    return call(service.scan, session_id)
