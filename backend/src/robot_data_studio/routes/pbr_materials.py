from fastapi import APIRouter, File, Form, UploadFile, Query
from fastapi.responses import FileResponse
from robot_data_contracts.asset import AssetArtifact
from ..services import pbr_material_service as service
from ..services.asset_service import AssetRegistry
from .assets import failure

router = APIRouter(prefix='/pbr-materials', tags=['pbr-materials'])


@router.get('')
def index():
    try:
        return {'items': service.catalog()}
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.post('', status_code=201)
async def upload(name: str = Form(...), origin: str = Form(''), license_name: str = Form(''), category: str = Form('fabric'),
                 base_color: UploadFile = File(...), normal: UploadFile = File(...), roughness: UploadFile = File(...)):
    try:
        images = {}
        for role, file in zip(service.ROLES, (base_color, normal, roughness)):
            images[role] = await file.read(32*1024*1024 + 1)
        return service.import_material(name, images, origin=origin, license_name=license_name or 'user-provided', category=category)
    except (OSError, ValueError) as error:
        raise failure(error) from error
    finally:
        for file in (base_color, normal, roughness):
            await file.close()


@router.get('/{asset_id}/maps/{role}')
def image(asset_id: str, role: str, version: int = Query(ge=1)):
    try:
        registry = AssetRegistry()
        entry = service.describe(registry.get(asset_id, version), registry)['maps'].get(role)
        if not entry:
            raise ValueError('unknown PBR map')
        return FileResponse(registry.artifact_path(AssetArtifact.model_validate(entry['artifact'])), media_type='image/png')
    except (OSError, ValueError) as error:
        raise failure(error) from error
