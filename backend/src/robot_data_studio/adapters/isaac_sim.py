from __future__ import annotations

import os
import json
import math
from pathlib import Path
from typing import Any

from ..config import CONTRACTS_SRC, PROJECT_ROOT, require_directory, require_file, settings
from ..camera_profiles import validate_session_camera_profile
from ..render_profiles import load_renderer_profile, validate_session_renderer_profile
from .base import CollectionAdapter, WorkerLaunch, WorkerReadiness


BIMANUAL_ASSET_ROOT = PROJECT_ROOT / "assets/sources/visual-workstation-v1"
BIMANUAL_FRANKA_USD = Path(os.environ.get(
    "ROBOT_DATA_STUDIO_BIMANUAL_FRANKA_USD", str(BIMANUAL_ASSET_ROOT / "franka.usd")
))

BIMANUAL_CLOTH_USD = PROJECT_ROOT / "assets/sources/robot-cloth-scenes-v1/scenes/fixtures_v4/place_in_basket/v001/cloth.usda"

CLOTHFORGE_SCENE = "bimanual_tabletop_v17_clothforge"
CLOTH_DROP_SCENE = "clothforge_free_drop"
GENESIS_TELEOP_SCENE = "genesis_ipc_clothforge_single"
GENESIS_RIGID_SCENE = "genesis_ipc_rigid_single"
GENESIS_SCENES = {GENESIS_TELEOP_SCENE, GENESIS_RIGID_SCENE}
CLOTHFORGE_SCENES = {CLOTHFORGE_SCENE, CLOTH_DROP_SCENE}
SIMULATION_PRESETS = [
    {"id": "fast", "label": "快速试操作", "values": {"cloth_substeps": 4, "cloth_iterations": 10, "cloth_collision_interval": 0}},
    {"id": "balanced", "label": "平衡", "values": {"cloth_substeps": 8, "cloth_iterations": 20, "cloth_collision_interval": 5}},
    {"id": "precise", "label": "精细接触", "values": {"cloth_substeps": 8, "cloth_iterations": 30, "cloth_collision_interval": 1}},
]
SIMULATION_KEYS = {"simulation_preset", "cloth_substeps", "cloth_collision_interval"}

BIMANUAL_SCENES = {"bimanual_tabletop_v17", "bimanual_tabletop_v17_cloth", CLOTHFORGE_SCENE}


def _number(key, label, default, minimum, maximum, step, unit="", scale="linear"):
    return dict(key=key, label=label, default=default, minimum=minimum, maximum=maximum, step=step, unit=unit, scale=scale)


SCENES = {
    CLOTHFORGE_SCENE: {
        "label": "双 Franka 实验台 v17＋ClothForge 衣物",
        "description": "选择 ClothForge 衣物与材料，在桌面上调参操作；Tab 切换主力臂。参数在启动时生效。",
        "family": "bimanual",
        "simulation_presets": SIMULATION_PRESETS,
        "parameters": [
            {"key": "garment_asset_id", "label": "衣物资产", "default": "MDL-clothforge-tshirt-000", "choices": ["MDL-clothforge-tshirt-000"]},
            _number("garment_version", "衣物资产版本", 1, 1, 100000, 1),
            {"key": "material_preset", "label": "材料预设", "default": "medium", "choices": ["light", "medium", "heavy"]},
            _number("mass_per_area", "面密度", .22, .02, 2, .01, "kg/m²"),
            _number("friction", "摩擦系数", .5, .01, 2, .05),
            _number("tri_ke", "拉伸系数", 3000, 100, 30000, 100, "N/m", "log"),
            _number("tri_ka", "面积约束系数", 3000, 100, 30000, 100, "N/m", "log"),
            _number("edge_ke", "弯曲系数", .005, .00001, 1, .001, "", "log"),
            _number("garment_scale", "衣物缩放", 1, .1, 2, .05),
            _number("garment_rotation_deg", "桌面旋转", 0, -180, 180, 15, "°"),
            _number("garment_offset_x_m", "桌面 X 偏移", 0, -.5, .5, .01, "m"),
            _number("garment_offset_y_m", "桌面 Y 偏移", 0, -.3, .3, .01, "m"),
            _number("cloth_iterations", "布料求解迭代数", 30, 4, 64, 1),
            {"key": "simulation_preset", "label": "仿真预设", "default": "precise", "choices": ["fast", "balanced", "precise", "custom"]},
            _number("cloth_substeps", "物理子步数", 8, 1, 16, 1),
            _number("cloth_collision_interval", "自碰撞刷新间隔（0：每子步首次；1：每次迭代）", 1, 0, 64, 1),
            {"key": "visual_texture", "label": "衣物贴图", "default": "none", "choices": ["none", "cotton", "linen", "denim", "terry"]},
            {"key": "visual_color", "label": "基础颜色", "default": "#386ba1"},
            _number("visual_roughness", "外观粗糙度", .9, 0, 1, .05),
        ],
    },
    "bimanual_tabletop_v17_cloth": {
        "label": "双 Franka 实验台 v17＋布料（Tab 切换）",
        "description": "现有布料 USD 接入 PhysX 可变形仿真；沿用 v17 桌面与四视角，Tab 切换主力臂。",
        "family": "bimanual",
        "parameters": [],
    },
    "bimanual_tabletop_v17": {
        "label": "双 Franka 实验台 v17（Tab 切换）",
        "description": "复用 v17 实验台 USD、材质与灯光；Keyboard / PhysX，Tab 切换主力臂。选择实验台 v4 相机，960×720。",
        "family": "bimanual",
        "parameters": [],
    },
    "franka_empty": {
        "label": "Franka 空场景遥操采集",
        "description": "Isaac Lab Franka 空场景采集。",
        "family": "general",
        "parameters": [],
    },
    "rigid_pick_place": {
        "label": "刚体抓取放置",
        "description": "Isaac Lab 刚体抓取放置场景。",
        "family": "general",
        "parameters": [
            {
                "key": "work_surface_height_m",
                "label": "工作面相对底座高度",
                "unit": "m",
                "minimum": 0.18,
                "maximum": 0.32,
                "step": 0.01,
                "default": 0.25,
                "scale": "linear",
            }
        ],
    },
    "rigid_cube_lift": {
        "label": "刚体方块抓取抬升",
        "description": "固定方块的抓取、抬升 8 cm、保持 1 秒并松开，用于 Isaac→OpenPI 最小闭环。",
        "family": "rigid_pick",
        "automatic_outcome": True,
        "parameters": [
            {
                "key": "work_surface_height_m",
                "label": "工作面相对底座高度",
                "unit": "m",
                "minimum": 0.18,
                "maximum": 0.32,
                "step": 0.01,
                "default": 0.25,
                "scale": "linear",
            }
        ],
    },
    "l_table_basket": {
        "label": "L 形桌放篮子（场景资产）",
        "description": "Isaac Lab 加载 fixtures_v4 的 place_in_basket 场景资产：L 形桌与篮子有碰撞体，机器人按资产位姿放置。",
        "family": "fixtures",
        "parameters": [],
    },
}


SCENES[CLOTH_DROP_SCENE] = {
    "label": "ClothForge 自由下落 · 无机械臂",
    "description": "同一 IsaacLab / Newton 纯 VBD 环境观察衣物下落；没有机械臂、MJWarp 或双向耦合。支持暂停、继续、重置，不生成机器人 Episode。",
    "family": "cloth_observation", "simulation_presets": SIMULATION_PRESETS,
    "parameters": [dict(p) for p in SCENES[CLOTHFORGE_SCENE]["parameters"]] + [
        _number("drop_height_m", "最低点距桌面高度", .25, .02, 1, .05, "m"),
    ],
}
VISUAL_SCENES = BIMANUAL_SCENES | {CLOTH_DROP_SCENE}

SCENES[GENESIS_TELEOP_SCENE] = {
    "label": "单 Franka＋ClothForge · Genesis IPC 遥操采集",
    "description": "Genesis FEM Cloth＋IPC 物理、Isaac Sim RTX 渲染；统一 Collector 键盘操作并记录 Episode，可选现有 ClothForge 衣物与材料。",
    "family": "single_arm",
    "parameters": [dict(p) for p in SCENES[CLOTHFORGE_SCENE]['parameters']
                   if p['key'] in {'garment_asset_id', 'garment_version', 'material_preset',
                                   'garment_scale', 'garment_rotation_deg', 'garment_offset_x_m', 'garment_offset_y_m'}],
}


SCENES[GENESIS_RIGID_SCENE] = {
    "label": "单 Franka＋刚体方块 · Genesis IPC 对照",
    "description": "Genesis 刚体＋IPC 物理、Isaac Sim RTX 渲染；无布料，固定方块作接触障碍物；复用同一 Collector 遥操与 Episode 采集，显示分段耗时。",
    "family": "single_arm", "parameters": [],
}

class IsaacSimAdapter(CollectionAdapter):
    adapter_id = "isaac_sim"
    label = "Isaac Sim / Isaac Lab"
    @property
    def scenes(self):
        if "cloth" in settings.enabled_extensions:
            # IPC entrypoints were excluded from this release draft. They cannot
            # be restored by a feature flag without supplying their runtime.
            return {key: value for key, value in SCENES.items() if key not in GENESIS_SCENES}
        return {"rigid_cube_lift": SCENES["rigid_cube_lift"]}

    @property
    def control_modes(self):
        return ("keyboard", "gello", "scripted") if {"cloth", "generation"} & settings.enabled_extensions else ("keyboard", "gello")
    @property
    def camera_profile_ids(self):
        if "cloth" not in settings.enabled_extensions:
            return ("lab_d435i_dual_v1",)
        profiles = ("lab_d435i_dual_v1", "isaac_bimanual_tabletop_visual_v4", "isaac_bimanual_tabletop_visual_v5")
        return profiles + (("isaac_fr3_dual_wrist_v1",) if settings.isaac_robot_model == "fr3" else ())
    renderer_profile_ids = ("isaac_performance_v1", "isaac_balanced_v1", "isaac_quality_v1")
    @property
    def physics_backends(self):
        return ("physx", "newton") if "cloth" in settings.enabled_extensions else ("physx",)
    capabilities = {
        "webrtc": True,
        "recording": True,
        "automatic_outcome": False,
        "scene_reconfigure": False,
    }
    worker_entrypoint = "gello_remote.isaaclab_gello"

    def scene_descriptors(self):
        scenes = {key: {**value, "parameters": [dict(p) for p in value["parameters"]]} for key, value in self.scenes.items()}
        garment_scenes = (CLOTHFORGE_SCENES | {GENESIS_TELEOP_SCENE}) & scenes.keys()
        if not garment_scenes:
            return scenes
        from ..services.asset_service import AssetRegistry
        ids = sorted({record.asset_id for record in AssetRegistry().all()
                      if record.kind == "model" and "clothforge" in record.tags})
        for scene_id in garment_scenes:
            field = scenes[scene_id]["parameters"][0]
            field["choices"] = ids
            if ids and field["default"] not in ids:
                field["default"] = ids[0]
        return scenes

    def _clothforge_selection(self, params, scene_id=CLOTHFORGE_SCENE):
        from ..services.asset_service import AssetRegistry
        registry = AssetRegistry()
        version = params.get('garment_version', None if scene_id == GENESIS_TELEOP_SCENE else 1)
        record = registry.get(str(params.get("garment_asset_id", "MDL-clothforge-tshirt-000")), int(version) if version is not None else None)
        if record.kind != "model" or "clothforge" not in record.tags:
            raise ValueError("garment_asset_id=请选择 ClothForge 衣物模型")
        paths = {a.role: registry.artifact_path(registry.inspect_artifact(a)) for a in record.artifacts if a.role in {"simulation_mesh", "provenance"}}
        if not {"simulation_mesh", "provenance"}.issubset(paths):
            raise ValueError("garment_asset_id=衣物资产缺少网格或清单")
        manifest = json.loads(paths["provenance"].read_text())
        if paths["simulation_mesh"] != paths["provenance"].parent / "mesh.npz":
            raise ValueError("garment_asset_id=衣物网格和清单必须来自同一目录")
        preset = str(params.get("material_preset", "medium"))
        material = json.loads((paths["provenance"].parent / f"config-{preset}.json").read_text())["material"]
        resolved = {p["key"]: params.get(p["key"], material.get(p["key"], p["default"])) for p in self.scenes[scene_id]["parameters"]}
        from ..services.garment_appearance import PARAMETERS, resolve_appearance
        appearance = resolve_appearance(registry, record, params)
        resolved = {key: value for key, value in resolved.items() if key not in SIMULATION_KEYS or key in params}
        preset_values = next((item["values"] for item in SIMULATION_PRESETS if item["id"] == params.get("simulation_preset")), None)
        if preset_values is not None:
            resolved.update(preset_values)
            resolved.update({key: params[key] for key in preset_values if key in params})
            if any(resolved[key] != value for key, value in preset_values.items()):
                resolved["simulation_preset"] = "custom"
        resolved.update({key: appearance[target] for key, target in PARAMETERS.items() if target in appearance})
        return paths["provenance"].parent, {**resolved, "garment_id": manifest["id"],
            "appearance": appearance, "garment_asset_id": record.asset_id, "garment_version": record.version}

    def validate_config(self, config: dict[str, Any]) -> None:
        if config.get("scene_id") not in self.scenes:
            raise ValueError("unsupported or disabled Isaac Sim scene; the public core provides rigid_cube_lift")
        if config.get("cloth_generation_plan_id"):
            settings.require_extension("generation")
            settings.require_extension("cloth")
            from ..services.cloth_generation_service import validate_session
            validate_session(config)
            return
        generation = None
        if config.get("generation_plan_id"):
            settings.require_extension("generation")
            from ..services.generation_service import generation_session
            generation = generation_session(config)
        if not generation and config.get("control_mode") not in self.control_modes:
            raise ValueError("Isaac Sim supports keyboard or GELLO control only")
        if config.get("scene_id") not in self.scenes:
            raise ValueError("unsupported Isaac Sim scene")
        backend = str(config.get('physics_backend') or settings.isaac_physics_backend)
        if config['scene_id'] in GENESIS_SCENES:
            if config['control_mode'] != 'keyboard' or backend != 'genesis_ipc':
                raise ValueError('单臂 Genesis IPC 场景使用 Keyboard 与 Genesis + IPC')
            params = config.get('scene_params', {})
            fields = self.scenes[config['scene_id']]['parameters']
            if set(params) - {field['key'] for field in fields}:
                raise ValueError('Genesis IPC 示例收到不支持的场景参数')
            for field in fields:
                if field['key'] not in params:
                    continue
                value = params[field['key']]
                if field['key'] == 'garment_asset_id':
                    continue
                if 'choices' in field:
                    if value not in field['choices']:
                        raise ValueError(f"{field['key']}=unsupported choice")
                elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not field['minimum'] <= value <= field['maximum']:
                    raise ValueError(f"{field['key']}=参数超出范围")
            if config['scene_id'] == GENESIS_TELEOP_SCENE:
                self._clothforge_selection(params, GENESIS_TELEOP_SCENE)
        elif backend == 'genesis_ipc':
            raise ValueError('Genesis IPC 当前仅支持单臂 ClothForge 与纯刚体场景')
        if config["scene_id"] in BIMANUAL_SCENES:
            if settings.isaac_robot_model not in {"panda", "fr3"}:
                raise ValueError("Isaac robot model must be panda or fr3")
            if settings.isaac_robot_model == "fr3" and (not settings.isaac_fr3_usd or not Path(settings.isaac_fr3_usd).is_file() or backend != "physx"):
                raise ValueError("FR3 requires an existing explicit FR3 USD and PhysX")
        if config.get("camera_profile_id") == "isaac_fr3_dual_wrist_v1" and (
            config["scene_id"] not in BIMANUAL_SCENES or settings.isaac_robot_model != "fr3" or backend != "physx"
        ):
            raise ValueError("真实双腕配置仅用于双 FR3 / PhysX")
        if config["scene_id"] in VISUAL_SCENES:
            from ..services.surface_appearance import resolve_environment
            resolve_environment(config.get('scene_params', {}).get('environment_appearance'))
            from ..services.camera_lighting import resolve_camera_lighting
            resolve_camera_lighting(config.get('scene_params', {}).get('camera_lighting'))
            if config["scene_id"] == CLOTH_DROP_SCENE:
                if config["control_mode"] != "scripted" or str(config.get("physics_backend") or settings.isaac_physics_backend) != "newton":
                    raise ValueError("自由下落场景使用 Scripted 观察模式和 Newton")
            elif config["control_mode"] not in {"keyboard", "gello"}:
                raise ValueError("双臂实验台使用 Keyboard 或双 GELLO")
            if config["scene_id"] not in CLOTHFORGE_SCENES and str(config.get("physics_backend") or settings.isaac_physics_backend) != "physx":
                raise ValueError("双臂实验台 v17 当前仅支持 PhysX")
            if config.get("camera_profile_id") not in {"isaac_bimanual_tabletop_visual_v4", "isaac_bimanual_tabletop_visual_v5", "isaac_fr3_dual_wrist_v1"}:
                raise ValueError("双臂实验台 v17 请使用四视角 v4/v5 或 FR3 双腕配置和 960×720")
            for path in (BIMANUAL_ASSET_ROOT / "bimanual_tabletop_lab_v17.usda",
                         BIMANUAL_ASSET_ROOT / "asset_manifest_bimanual_v17.json",
                         BIMANUAL_ASSET_ROOT / "hdri/photo_studio_01_4k.hdr") + (() if config["scene_id"] == CLOTH_DROP_SCENE else (Path(settings.isaac_fr3_usd) if settings.isaac_robot_model == "fr3" else BIMANUAL_FRANKA_USD,)):
                if not path.is_file():
                    raise ValueError(f"bimanual tabletop asset missing: {path}")
        if config.get("control_mode") == "scripted" and config["scene_id"] != CLOTH_DROP_SCENE and not generation:
            raise ValueError("Scripted 观察模式仅用于自由下落场景")
        allowed_params = {
            item["key"] for item in self.scenes[config["scene_id"]]["parameters"]
        }
        if config['scene_id'] in VISUAL_SCENES:
            allowed_params.update({'environment_appearance', 'camera_lighting'})
        if config['scene_id'] in CLOTHFORGE_SCENES:
            from ..services.garment_appearance import PARAMETERS
            allowed_params.update(PARAMETERS)
        unknown_params = sorted(set(config.get("scene_params", {})) - allowed_params)
        if unknown_params:
            raise ValueError(
                f"Isaac Sim scene parameter is not allowlisted: {', '.join(unknown_params)}"
            )
        if config["scene_id"] in CLOTHFORGE_SCENES:
            params = config.get("scene_params", {})
            if SIMULATION_KEYS.intersection(params) and str(config.get("physics_backend") or settings.isaac_physics_backend) != "newton":
                raise ValueError("simulation_preset=这些仿真参数仅适用于 Newton 衣物工位")
            for field in self.scenes[config["scene_id"]]["parameters"]:
                if field["key"] not in params:
                    continue
                value = params[field["key"]]
                if field["key"] in {"garment_asset_id", "visual_color"}:
                    continue
                if "choices" in field:
                    if value not in field["choices"]:
                        raise ValueError(f"{field['key']}=unsupported choice")
                elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not field["minimum"] <= value <= field["maximum"]:
                    raise ValueError(f"{field['key']}=参数超出范围")
                elif field["key"] in {"garment_version", "cloth_iterations", "cloth_substeps", "cloth_collision_interval"} and int(value) != value:
                    raise ValueError(f"{field['key']}=必须是整数")
            self._clothforge_selection(params, config["scene_id"])
        profile_id = str(config.get("camera_profile_id", "lab_d435i_dual_v1"))
        if profile_id not in self.camera_profile_ids:
            raise ValueError(f"unsupported Isaac Sim camera profile: {profile_id}")
        validate_session_camera_profile(profile_id, width=int(config["width"]), height=int(config["height"]))
        renderer_profile_id = str(config.get("renderer_profile_id") or "isaac_balanced_v1")
        if renderer_profile_id not in self.renderer_profile_ids:
            raise ValueError(f"unsupported Isaac renderer profile: {renderer_profile_id}")
        validate_session_renderer_profile(renderer_profile_id)
        physics_backend = str(config.get("physics_backend") or settings.isaac_physics_backend)
        if physics_backend not in self.physics_backends:
            raise ValueError(f"unsupported Isaac physics backend: {physics_backend}")
        if config["scene_id"] == "l_table_basket" and not settings.isaac_l_table_basket_scene_usd.is_file():
            raise ValueError(
                f"l_table_basket scene asset is missing: {settings.isaac_l_table_basket_scene_usd}"
            )

    def build_collect_command(self, config: dict[str, Any], output_dir: Path) -> list[str]:
        self.validate_config(config)
        if config['scene_id'] in GENESIS_SCENES:
            if config['scene_id'] == GENESIS_RIGID_SCENE:
                scene_args = ['--rigid-only']
            else:
                directory, parameters = self._clothforge_selection(config.get('scene_params', {}), GENESIS_TELEOP_SCENE)
                scene_args = ['--garment-dir', str(directory), '--parameters', json.dumps(parameters, ensure_ascii=False)]
            return [settings.cloth_genesis_python, '-B',
                    str(PROJECT_ROOT / 'expert_demos/curobo_cloth_v1/teleop/live.py'),
                    *scene_args,
                    '--output', str(output_dir), '--isaac-python', settings.cloth_render_python,
                    '--control-fps', str(config['control_fps']),
                    '--target-episodes', str(config.get('target_episodes', 50)),
                    '--collector-ui-root', str(settings.gello_remote_root / 'src/gello_remote/web/genesis'),
                    '--host', '127.0.0.1', '--port', str(config['port']),
                    '--width', str(config['width']), '--height', str(config['height'])]
        renderer_profile_id = str(config.get("renderer_profile_id") or "isaac_balanced_v1")
        renderer_profile = load_renderer_profile(renderer_profile_id)
        kit_settings = " ".join(
            f"--{key}={'true' if value is True else 'false' if value is False else value}"
            for key, value in sorted(renderer_profile["kit_settings"].items())
        )
        command = [
            str(settings.isaaclab_launcher),
            "-p",
            "-m",
            "gello_remote.isaaclab_gello",
            "--control-source",
            str(config["control_mode"]),
            "--gpu-id",
            str(config["gpu"]),
            "--enable_cameras",
            "--livestream",
            "1",
            "--rendering_mode",
            renderer_profile["rendering_mode"],
            "--physics-backend",
            str(config.get("physics_backend") or settings.isaac_physics_backend),
            "--host",
            "127.0.0.1",
            "--port",
            str(config["port"]),
            "--stream-host",
            settings.public_ip,
            "--signaling-port",
            str(settings.isaac_signaling_port),
            "--media-port",
            str(settings.isaac_media_port),
            "--control_hz",
            str(config["control_fps"]),
            "--data-dir",
            str(output_dir),
            "--scene",
            config["scene_id"],
            "--width",
            str(config["width"]),
            "--height",
            str(config["height"]),
            "--camera-profile-file",
            str(validate_session_camera_profile(
                str(config.get("camera_profile_id", "lab_d435i_dual_v1")),
                width=int(config["width"]),
                height=int(config["height"]),
            )),
            "--renderer-profile-file",
            str(validate_session_renderer_profile(renderer_profile_id)),
            "--franka-usd",
            settings.isaac_franka_usd,
            "--kit_args",
            (kit_settings + " --/app/window/width=960 --/app/window/height=720").strip(),
        ]
        if settings.isaac_local_display and not config.get("generation_plan_id") and config["scene_id"] != CLOTH_DROP_SCENE:
            command[command.index("--livestream") + 1] = "0"
            command += ["--local-display"]
        if config["scene_id"] in {"rigid_pick_place", "rigid_cube_lift"}:
            height = config.get("scene_params", {}).get("work_surface_height_m", 0.25)
            command += ["--work-surface-height-m", str(height)]
        if config["scene_id"] == "l_table_basket":
            command += ["--scene-usd", str(settings.isaac_l_table_basket_scene_usd)]
        if config["scene_id"] in VISUAL_SCENES:
            command[command.index("--franka-usd") + 1] = (settings.isaac_fr3_usd if settings.isaac_robot_model == "fr3" and config["scene_id"] in BIMANUAL_SCENES else str(BIMANUAL_FRANKA_USD))
            if config["scene_id"] in BIMANUAL_SCENES:
                command += ["--robot-model", settings.isaac_robot_model]
            from ..services.surface_appearance import resolve_environment
            from ..services.camera_lighting import resolve_camera_lighting
            environment = resolve_environment(config.get('scene_params', {}).get('environment_appearance'))
            command += [
                '--environment-appearance', json.dumps(environment, ensure_ascii=False, allow_nan=False),
                '--camera-lighting', json.dumps(resolve_camera_lighting(config.get('scene_params', {}).get('camera_lighting')), allow_nan=False),
                "--visual-style", "dual_franka_tabletop",
                "--workstation-usd", str(BIMANUAL_ASSET_ROOT / "bimanual_tabletop_lab_v17.usda"),
                "--workstation-manifest-file", str(BIMANUAL_ASSET_ROOT / "asset_manifest_bimanual_v17.json"),
                "--hdri-file", str(BIMANUAL_ASSET_ROOT / "hdri/photo_studio_01_4k.hdr"),
            ]
        if config["scene_id"] == "bimanual_tabletop_v17_cloth":
            command += ["--scene-usd", str(BIMANUAL_CLOTH_USD), "--cloth"]
        if config["scene_id"] in CLOTHFORGE_SCENES:
            directory, parameters = self._clothforge_selection(config.get("scene_params", {}), config["scene_id"])
            command += ["--clothforge-dir", str(directory), "--clothforge-params", json.dumps(parameters, ensure_ascii=False, allow_nan=False)]
        if config["scene_id"] == CLOTH_DROP_SCENE:
            index = command.index("--franka-usd")
            del command[index:index + 2]
            command[command.index("--livestream") + 1] = "0"
        if config.get("generation_plan_id"):
            from ..services.generation_service import plan_directory, report_for
            command[command.index("--control-source") + 1] = "trajectory"
            command[command.index("--livestream") + 1] = "0"
            command += ["--headless", "--dataset-fps", "10", "--generation-plan",
                        str(plan_directory(config["generation_plan_id"]) / "plan.json")]
            report = report_for({"config": {**config, "episode_root": str(output_dir)}})
            if report:
                if report["status"] == "completed":
                    raise ValueError("generation batch already completed")
                command.append("--resume-generation")
        return command

    def build_worker_launch(self, config: dict[str, Any], output_dir: Path) -> WorkerLaunch:
        self.validate_config(config)
        require_directory(settings.gello_remote_root, "ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT")
        require_file(settings.gello_remote_root / "src/gello_remote/isaaclab_gello.py", "ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT")
        require_file(settings.isaaclab_launcher, "ROBOT_DATA_STUDIO_ISAACLAB_LAUNCHER", executable=True)
        require_directory(settings.isaaclab_conda_prefix, "ROBOT_DATA_STUDIO_ISAACLAB_CONDA_PREFIX")
        if not settings.isaac_franka_usd.strip():
            raise ValueError("Configure ROBOT_DATA_STUDIO_ISAAC_FRANKA_USD: a Panda asset is required")
        if "://" not in settings.isaac_franka_usd:
            require_file(Path(settings.isaac_franka_usd), "ROBOT_DATA_STUDIO_ISAAC_FRANKA_USD")
        if config.get('scene_id') in GENESIS_SCENES:
            import uuid
            # Each launch gets fresh state/preview files, including session restarts.
            work = output_dir / 'teleop' / uuid.uuid4().hex[:12]
            libraries = Path(settings.cloth_genesis_python).resolve().parents[1] / 'lib'
            cuda = sorted(libraries.glob('python*/site-packages/nvidia/*/lib'))
            command = self.build_collect_command(config, work) + ['--episode-root', str(output_dir)]
            return WorkerLaunch(command=command, cwd=PROJECT_ROOT,
                env_updates={'CUDA_VISIBLE_DEVICES': str(config['gpu']), 'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONPATH': str(settings.clothforge_root / 'src') + ':' + str(CONTRACTS_SRC),
                    'LD_LIBRARY_PATH': ':'.join(map(str, cuda)) + ':' + os.environ.get('LD_LIBRARY_PATH', ''),
                    'GS_CACHE_FILE_PATH': str(output_dir / 'cache/genesis'),
                    'XDG_CACHE_HOME': str(output_dir / 'cache'), 'OMP_NUM_THREADS': '4'},
                readiness=WorkerReadiness(kind='tcp', timeout_s=600, host='127.0.0.1', port=int(config['port'])),
                resources=('simulator:global', f"gpu:{int(config['gpu'])}", f"tcp:{int(config['port'])}",
                           f"output:{output_dir.resolve()}"))
        if config.get("cloth_generation_plan_id"):
            import sys
            from ..services.cloth_generation_service import plan_directory, report_for, validate_session
            validate_session(config)
            report = report_for({"config": {**config, "episode_root": str(output_dir)}})
            if report and report['status'] == 'completed':
                raise ValueError('衣物外观批次已完成')
            return WorkerLaunch(
                command=[sys.executable, '-B', '-m', 'robot_data_generation.cloth_appearance_runner',
                    '--plan', str(plan_directory(config['cloth_generation_plan_id']) / 'plan.json'),
                    '--output', str(output_dir.resolve()), '--studio-root', str(PROJECT_ROOT),
                    '--isaac-python', settings.cloth_render_python, '--export-python', settings.cloth_genesis_python],
                cwd=PROJECT_ROOT,
                env_updates={'PYTHONDONTWRITEBYTECODE': '1', 'CUDA_VISIBLE_DEVICES': str(config['gpu']),
                    'PYTHONPATH': str(settings.generation_root / 'src') + ':' + str(CONTRACTS_SRC)},
                readiness=WorkerReadiness(kind='marker', timeout_s=600.0),
                resources=('simulator:global', f"gpu:{int(config['gpu'])}", f"output:{output_dir.resolve()}"),
            )
        python_paths = [
            str(settings.gello_remote_root / "src"),
            str(CONTRACTS_SRC),
        ]
        if config.get("scene_id") in CLOTHFORGE_SCENES:
            require_directory(settings.clothforge_root / "src/clothforge", "ROBOT_DATA_STUDIO_CLOTHFORGE_ROOT")
            python_paths.append(str(settings.clothforge_root / "src"))
        if config.get("generation_plan_id"):
            python_paths.append(str(settings.generation_root / "src"))
        if os.environ.get("PYTHONPATH"):
            python_paths.append(os.environ["PYTHONPATH"])
        return WorkerLaunch(
            command=self.build_collect_command(config, output_dir),
            cwd=settings.gello_remote_root,
            env_updates={
                "CONDA_PREFIX": str(settings.isaaclab_conda_prefix),
                "CUDA_VISIBLE_DEVICES": str(config["gpu"]),
                "PYTHONPATH": ":".join(python_paths),
            },
            readiness=(WorkerReadiness(kind="marker", timeout_s=600.0) if config.get("generation_plan_id") else WorkerReadiness(
                kind="tcp", timeout_s=600.0, host="127.0.0.1", port=int(config["port"])
            )),
            resources=(("simulator:global", f"gpu:{int(config['gpu'])}", f"output:{output_dir.resolve()}") if config.get("generation_plan_id") else (
                "simulator:global",
                f"gpu:{int(config['gpu'])}",
                f"tcp:{int(config['port'])}",
                *((f"tcp:{settings.isaac_signaling_port}", f"udp:{settings.isaac_media_port}") if not settings.isaac_local_display else ()),
                f"output:{output_dir.resolve()}",
            )),
        )
