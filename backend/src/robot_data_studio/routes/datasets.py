from fastapi import APIRouter

from ..services.dataset_service import list_datasets


router = APIRouter(tags=["datasets"])


@router.get("/datasets")
def index():
    return list_datasets()
