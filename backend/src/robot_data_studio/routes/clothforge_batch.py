from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import clothforge_batch_service as service

router = APIRouter(prefix='/clothforge-batches', tags=['clothforge-batches'])


class Garment(BaseModel):
    asset_id: str
    version: int = Field(ge=1)


class PlanRequest(BaseModel):
    garments: list[Garment] = Field(min_length=1, max_length=80)
    scenario: str = 'hanging'
    material_id: str = 'medium'
    material_overrides: dict = Field(default_factory=dict)
    solver_overrides: dict = Field(default_factory=dict)


@router.post('/plans', status_code=201)
def preview(payload: PlanRequest):
    try:
        return service.preview(payload.model_dump())
    except (OSError, ValueError) as error:
        raise HTTPException(422, str(error)) from error


@router.get('/plans/{plan_id}')
def get(plan_id: str):
    try:
        return service.get(plan_id)
    except (OSError, ValueError) as error:
        raise HTTPException(422, str(error)) from error


@router.post('/plans/{plan_id}/start', status_code=202)
def start(plan_id: str):
    try:
        return service.start(plan_id)
    except (OSError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
