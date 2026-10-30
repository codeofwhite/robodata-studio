from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from ..services import generation_service as service
from ..services.worker_manager import worker_manager

router = APIRouter(prefix='/generation', tags=['generation'])


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    episode_ids: list[int] = Field(min_length=1, max_length=100)
    mode: Literal['nominal', 'xy'] = 'xy'
    attempts_per_source: int = Field(default=20, ge=1, le=100)
    range_m: float = Field(default=.02, gt=0, le=.10)
    seed: int = Field(default=20260905, ge=0)


class StartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_name: str = Field(min_length=1, max_length=80)
    gpu: int = Field(default=0, ge=0, le=255)


def call(function, *args):
    try:
        return function(*args)
    except (KeyError, FileNotFoundError) as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, ValueError, RuntimeError) as error:
        raise HTTPException(409, str(error)) from error


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
