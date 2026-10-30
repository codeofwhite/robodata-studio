from fastapi import APIRouter

from ..services.consumer_smoke_service import list_consumer_smokes


router = APIRouter(tags=["consumer-smokes"])


@router.get("/consumer-smokes")
def index():
    return list_consumer_smokes()
