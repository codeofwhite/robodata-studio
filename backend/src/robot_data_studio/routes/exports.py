from fastapi import APIRouter, HTTPException

from ..models import ExportCreate
from ..services.export_service import create_export, list_exports, preflight_export


router = APIRouter(tags=["exports"])


@router.get("/exports")
def index():
    return list_exports()


@router.post("/exports", status_code=202)
def create(payload: ExportCreate):
    try:
        return create_export(payload)
    except KeyError:
        raise HTTPException(404, "dataset not found") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/exports/preflight")
def preflight(payload: ExportCreate):
    try:
        return preflight_export(payload)
    except KeyError:
        raise HTTPException(404, "dataset not found") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
