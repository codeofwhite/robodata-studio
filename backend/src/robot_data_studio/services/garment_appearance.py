"""Existing cloth textures and startup appearance for versioned garments."""
import re

from robot_data_contracts.asset import AssetArtifact

TEXTURES = {"none": "纯色", "cotton": "棉布", "linen": "亚麻", "denim": "牛仔", "terry": "毛巾"}
DEFAULT = {"texture": "none", "color": "#386ba1", "roughness": 0.9}
PARAMETERS = {"visual_material_id": "material_id", "visual_material_version": "material_version", "visual_color_mode": "color_mode", "visual_roughness_multiplier": "roughness_multiplier", "visual_normal_strength": "normal_strength", "visual_uv_scale": "uv_scale", "visual_texture": "texture", "visual_color": "color", "visual_roughness": "roughness"}


def texture_artifact(registry, texture):
    if texture not in TEXTURES:
        raise ValueError("visual_texture=未知衣物贴图")
    if texture == "none":
        return None
    return registry.inspect_artifact(AssetArtifact(source_id="robot-cloth-scenes-v1",
        path=f"textures/{texture}_color.png", role="visual_texture"))


def resolve_appearance(registry, record, params=None):
    saved = record.data.get("appearance", {})
    appearance = {**DEFAULT, **saved}
    appearance.update({target: params[key] for key, target in PARAMETERS.items() if params and key in params})
    if appearance.get("material_id"):
        from .pbr_material_service import resolve
        from robot_data_contracts.pbr_material import Appearance
        resolved = resolve({key: value for key, value in appearance.items() if key in Appearance.model_fields}, registry)
        return {**resolved, "texture_path": None, "texture_sha256": None, "uv_mapping": "pattern_xy_face_varying"}
    color, roughness = appearance["color"], appearance["roughness"]
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("visual_color=颜色必须是 #RRGGBB")
    if isinstance(roughness, bool) or not isinstance(roughness, (int, float)) or not 0 <= roughness <= 1:
        raise ValueError("visual_roughness=粗糙度必须在 0 到 1 之间")
    artifact = texture_artifact(registry, appearance["texture"])
    if artifact and appearance["texture"] == saved.get("texture") and saved.get("texture_sha256"):
        if artifact.sha256 != saved["texture_sha256"]:
            raise ValueError("visual_texture=衣物版本引用的贴图已变化")
    return {"texture": appearance["texture"], "color": color.lower(), "roughness": float(roughness),
            "texture_path": str(registry.artifact_path(artifact)) if artifact else None,
            "texture_sha256": artifact.sha256 if artifact else None,
            "uv_mapping": "pattern_xy_face_varying"}


def appearance_options(registry, record):
    if record.kind != "model" or "clothforge" not in record.tags:
        raise ValueError("请选择 ClothForge 衣物模型")
    textures = []
    for key, label in TEXTURES.items():
        artifact = texture_artifact(registry, key)
        textures.append({"id": key, "label": label, "artifact": artifact.model_dump() if artifact else None,
                         "thumbnail_url": f"/assets/garment-textures/{key}" if artifact else None})
    from .pbr_material_service import catalog
    return {"appearance": resolve_appearance(registry, record), "textures": textures, "materials": catalog()}
