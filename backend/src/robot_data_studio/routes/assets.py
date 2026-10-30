from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from robot_data_contracts.asset import AssetArtifact, AssetDraft
from ..services.asset_service import AssetRegistry, AssetConflict, AssetNotFound, AssetIntegrityError, is_video_artifact

from ..services.validation_overview import validation_overview
from ..services.cloth_run_service import cloth_run_manager, newton_cloth_run_manager

router = APIRouter(tags=["assets"])


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: AssetDraft
    expected_version: int = Field(default=0, ge=0)


class ClothRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    version: int = Field(ge=1)
    scenario: str | None = None
    material_id: str = "medium"
    material_overrides: dict = Field(default_factory=dict)
    solver_overrides: dict = Field(default_factory=dict)


def failure(error):
    code = 409 if isinstance(error, AssetConflict) else 404 if isinstance(error, AssetNotFound) else 422
    return HTTPException(code, str(error))


@router.get("/assets")
def index(q: str = Query("", max_length=200), kind: str = Query("", max_length=200), engine: str = "", outcome: str = "", integrity: str = "",
          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=250)):
    try:
        return AssetRegistry().catalog(q, kind, engine, outcome, integrity, offset, limit)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/validation-overview")
def overview():
    try:
        return validation_overview(AssetRegistry())
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/sources")
def sources():
    return AssetRegistry().sources()


@router.post("/assets/artifacts/inspect")
def inspect(artifact: AssetArtifact):
    try:
        return AssetRegistry().inspect_artifact(artifact)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.post("/assets", status_code=201)
def publish(request: PublishRequest):
    try:
        registry = AssetRegistry()
        if request.draft.kind == "model" and "clothforge" in request.draft.tags and "appearance" in request.draft.data:
            from ..services.garment_appearance import resolve_appearance, texture_artifact
            appearance = resolve_appearance(registry, request.draft)
            entry = None if appearance.get("material_id") else texture_artifact(registry, appearance["texture"])
            # Pin the texture with the same immutable artifact contract as the mesh.
            request.draft.artifacts = [a for a in request.draft.artifacts if a.role != "visual_texture"] + ([entry] if entry else [])
            from robot_data_contracts.asset import AssetReference
            request.draft.references = [ref for ref in request.draft.references if ref.role != "visual_material"]
            if appearance.get("material_id"):
                request.draft.references.append(AssetReference(asset_id=appearance["material_id"], version=appearance["material_version"], role="visual_material"))
            from robot_data_contracts.pbr_material import Appearance
            request.draft.data["appearance"] = {key: value for key, value in appearance.items() if key in Appearance.model_fields or key == "texture_sha256"}
        record, created = registry.publish(request.draft, request.expected_version)
        return {"record": record, "created": created}
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.post("/assets/runs", status_code=202)
def start_cloth_run(request: ClothRunRequest):
    try:
        selected = AssetRegistry().get(request.asset_id, request.version)
        if "clothforge" in selected.tags and "newton_vbd" in selected.engines:
            return newton_cloth_run_manager.start(
                request.asset_id, request.version, scenario=request.scenario or selected.data.get("scenario", "hanging"),
                material_id=request.material_id, material_overrides=request.material_overrides,
                solver_overrides=request.solver_overrides)
        if request.scenario is not None or request.material_overrides or request.solver_overrides or request.material_id != "medium":
            raise ValueError("tuning parameters are only supported by ClothForge")
        return cloth_run_manager.start(request.asset_id, request.version)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/runs/{run_id}")
def cloth_run(run_id: str):
    try:
        return newton_cloth_run_manager.get(run_id)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/cloth-options")
def cloth_options(asset_id: str, version: int = Query(ge=1)):
    try:
        return newton_cloth_run_manager.options(asset_id, version)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/garment-textures/{texture}")
def garment_texture(texture: str):
    from ..services.garment_appearance import texture_artifact
    try:
        registry = AssetRegistry()
        entry = texture_artifact(registry, texture)
        if entry is None:
            raise ValueError("纯色没有贴图")
        return FileResponse(registry.artifact_path(entry), media_type="image/png")
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/appearance-options")
def garment_appearance(asset_id: str, version: int = Query(ge=1)):
    from ..services.garment_appearance import appearance_options
    try:
        registry = AssetRegistry()
        return appearance_options(registry, registry.get(asset_id, version))
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/garment-mesh")
def garment_mesh(asset_id: str, version: int = Query(ge=1)):
    import numpy as np
    try:
        registry = AssetRegistry()
        record = registry.get(asset_id, version)
        if record.kind != 'model' or 'clothforge' not in record.tags:
            raise ValueError('请选择 ClothForge 衣物模型')
        entry = next(a for a in record.artifacts if a.role == 'simulation_mesh')
        path = registry.artifact_path(registry.inspect_artifact(entry))
        with np.load(path, allow_pickle=False) as mesh:
            if record.data.get('provenance', {}).get('dataset') == 'GarmentCodeData':
                uv = mesh['face_uv'].copy()
            else:
                uv = mesh['rest_triangles'][..., :2].copy()
                low, high = uv.reshape(-1, 2).min(0), uv.reshape(-1, 2).max(0)
                uv = (uv - low) / (high - low)
            return {'asset_id': record.asset_id, 'version': record.version,
                    'vertices': mesh['vertices'].tolist(), 'faces': mesh['faces'].tolist(),
                    'uv': uv.tolist(), 'parameters': record.data['parameters']}
    except (OSError, ValueError) as error:
        raise failure(error) from error


class TrouserPreviewRequest(BaseModel):
    asset_id: str
    version: int = Field(ge=1)
    style_id: str
    parameters: dict[str, float] = Field(default_factory=dict)


@router.get('/assets/trouser-styles/options')
def trouser_options():
    from ..services.trouser_style_service import options
    return options()


@router.post('/assets/trouser-styles/previews')
def trouser_preview(payload: TrouserPreviewRequest):
    from ..services.trouser_style_service import preview
    try:
        return preview(payload.model_dump())
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.post('/assets/trouser-styles/previews/{preview_id}/save', status_code=201)
def save_trouser(preview_id: str, appearance: dict):
    from ..services.trouser_style_service import save
    try:
        return save(preview_id, appearance)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get('/assets/tshirt-styles/options')
def tshirt_options():
    from ..services.trouser_style_service import options
    return options('tshirt')


@router.post('/assets/tshirt-styles/previews')
def tshirt_preview(payload: TrouserPreviewRequest):
    from ..services.trouser_style_service import preview
    try:
        return preview(payload.model_dump(),'tshirt')
    except (OSError,ValueError) as error:
        raise failure(error) from error


@router.post('/assets/tshirt-styles/previews/{preview_id}/save',status_code=201)
def save_tshirt(preview_id: str,appearance: dict):
    from ..services.trouser_style_service import save
    try:
        return save(preview_id,appearance,'tshirt')
    except (OSError,ValueError) as error:
        raise failure(error) from error


@router.get('/assets/skirt-styles/options')
def skirt_options():
    from ..services.trouser_style_service import options
    return options('skirt')


@router.post('/assets/skirt-styles/previews')
def skirt_preview(payload: TrouserPreviewRequest):
    from ..services.trouser_style_service import preview
    try:
        return preview(payload.model_dump(),'skirt')
    except (OSError,ValueError) as error:
        raise failure(error) from error


@router.post('/assets/skirt-styles/previews/{preview_id}/save',status_code=201)
def save_skirt(preview_id: str,appearance: dict):
    from ..services.trouser_style_service import save
    try:
        return save(preview_id,appearance,'skirt')
    except (OSError,ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}")
def detail(asset_id: str, version: int | None = Query(None, ge=1)):
    try:
        return AssetRegistry().detail(asset_id, version)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/versions/{version}/artifacts/{index}")
def artifact(asset_id: str, version: int, index: int):
    try:
        registry = AssetRegistry()
        record = registry.get(asset_id, version)
        if index < 0 or index >= len(record.artifacts):
            raise AssetNotFound("artifact index does not exist")
        entry = record.artifacts[index]
        registry.inspect_artifact(entry)
        path = registry.artifact_path(entry)
        suffix = path.suffix.lower()
        if is_video_artifact(entry.role, entry.path):
            return FileResponse(path, media_type="video/mp4" if suffix == ".mp4" else "video/webm",
                                headers={"X-Content-Type-Options": "nosniff"})
        image_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        if entry.role == "preview" and suffix in image_types:
            return FileResponse(path, media_type=image_types[suffix], headers={"X-Content-Type-Options": "nosniff"})
        return FileResponse(path, media_type="application/octet-stream", filename=path.name, headers={"X-Content-Type-Options": "nosniff"})
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/versions/{version}/artifacts/{index}/viewer")
def viewer(asset_id: str, version: int, index: int):
    try:
        registry = AssetRegistry()
        record = registry.get(asset_id, version)
        if index < 0 or index >= len(record.artifacts):
            raise AssetNotFound("artifact index does not exist")
        entry = record.artifacts[index]
        if (entry.role not in {"interactive_preview", "interactive_replay"}
                or entry.source_id not in {"clothforge-pilot-v1", "clothforge-library-v1", "clothforge-trouser-styles-v1", "clothforge-tshirt-styles-v1", "clothforge-skirt-styles-v1", "garmentcodedata-v2-phase2", "clothforge-repair-v2", "studio-cloth-runs"}):
            raise ValueError("artifact is not an interactive cloth viewer")
        if registry.integrity(record)["status"] != "current":
            raise AssetIntegrityError("viewer evidence is stale")
        path = registry.artifact_path(registry.inspect_artifact(entry))
        if path.suffix.lower() != ".html":
            raise ValueError("unsupported viewer type")
        return FileResponse(path, media_type="text/html", headers={
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer",
        })
    except (OSError, ValueError) as error:
        raise failure(error) from error
