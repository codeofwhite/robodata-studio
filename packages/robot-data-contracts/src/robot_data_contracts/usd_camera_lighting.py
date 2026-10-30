"""Apply visual parameters to live USD/RTX and report the effective calibration."""
import math
from .camera_lighting import CameraLightingValues

def apply_camera(stage, path, raw, width, height):
    from pxr import UsdGeom, Gf
    import numpy as np
    import omni.kit.commands
    value = CameraLightingValues.model_validate(raw or {})
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsA(UsdGeom.Camera):
        raise ValueError('相机不存在：' + path)
    camera = UsdGeom.Camera(prim)
    focal = float(camera.GetFocalLengthAttr().Get())
    vertical = float(camera.GetVerticalApertureAttr().Get())
    horizontal = float(camera.GetHorizontalApertureAttr().Get())
    fov = math.degrees(2 * math.atan(vertical / (2 * focal))) + value.fov_offset_deg
    if not 5 <= fov <= 150:
        raise ValueError('采样后相机 FOV 超出 5–150 度')
    if value.fov_offset_deg:
        focal = vertical / (2 * math.tan(math.radians(fov) / 2))
        camera.GetFocalLengthAttr().Set(focal)
    world = np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(prim)).T.copy()
    angles = [math.radians(getattr(value, 'camera_r'+axis+'_deg')) for axis in 'xyz']
    cx, cy, cz = [math.cos(a) for a in angles]; sx, sy, sz = [math.sin(a) for a in angles]
    rotation = np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]]) @ np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]]) @ np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
    world[:3,:3] = rotation @ world[:3,:3]
    world[:3,3] += [value.camera_x_m, value.camera_y_m, value.camera_z_m]
    if any(angles) or any((value.camera_x_m, value.camera_y_m, value.camera_z_m)):
        parent_inverse = UsdGeom.XformCache().GetLocalToWorldTransform(prim.GetParent()).GetInverse()
        local = Gf.Matrix4d(world.T.tolist()) * parent_inverse
        # The command also propagates transforms to the renderer's GPU hierarchy.
        omni.kit.commands.create('TransformPrimCommand', path=prim.GetPath(), new_transform_matrix=local,
                                 old_transform_matrix=UsdGeom.Xformable(prim).GetLocalTransformation()).do()
    world = np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(prim)).T
    return {'prim': path, 'nominal_vertical_fov_deg': fov,
            'intrinsics': [[width*focal/horizontal,0,width/2],[0,height*focal/vertical,height/2],[0,0,1]],
            'camera_to_world': world.tolist(), 'axes': 'OpenGL +X right +Y up -Z forward',
            'calibration_kind': 'effective_virtual_pinhole'}

def apply_lighting(stage, raw):
    from pxr import UsdLux
    value = CameraLightingValues.model_validate(raw or {})
    lights = []
    for prim in stage.Traverse():
        if not prim.HasAPI(UsdLux.LightAPI):
            continue
        light = UsdLux.LightAPI(prim)
        original = float(light.GetIntensityAttr().Get())
        intensity = original * value.light_intensity_multiplier
        if value.light_intensity_multiplier != 1:
            light.GetIntensityAttr().Set(intensity)
        if value.light_temperature_k is not None:
            light.GetEnableColorTemperatureAttr().Set(True)
            light.GetColorTemperatureAttr().Set(value.light_temperature_k)
        lights.append({'prim': str(prim.GetPath()), 'source_intensity': original, 'intensity': intensity,
                       'temperature_enabled': bool(light.GetEnableColorTemperatureAttr().Get()),
                       'temperature_k': float(light.GetColorTemperatureAttr().Get()),
                       'color': list(light.GetColorAttr().Get())})
    if not lights and (value.light_intensity_multiplier != 1 or value.light_temperature_k is not None):
        raise ValueError('场景没有可调整的 USD 灯光')
    return lights

def apply_imaging(settings, raw):
    from pxr import UsdLux
    value = CameraLightingValues.model_validate(raw or {})
    iso_key, white_key = '/rtx/post/tonemap/filmIso', '/rtx/post/tonemap/whitepoint'
    iso = settings.get(iso_key)
    white = settings.get(white_key)
    if value.exposure_ev:
        if iso is None:
            raise ValueError('Kit 未提供 Film ISO 设置')
        settings.set_float(iso_key, float(iso) * 2**value.exposure_ev)
    if value.white_balance_k is not None:
        if white is None:
            raise ValueError('Kit 未提供 Tone Mapping White Point 设置')
        settings.set_float_array(white_key, list(UsdLux.BlackbodyTemperatureAsRgb(value.white_balance_k)))
    return {'film_iso': settings.get(iso_key), 'white_point_rgb': list(settings.get(white_key)),
            'tone_mapping_operator': settings.get('/rtx/post/tonemap/op'),
            'exposure_time_s': settings.get('/rtx/post/tonemap/exposureTime'),
            'f_number': settings.get('/rtx/post/tonemap/fNumber'),
            'white_balance_method': 'USD blackbody temperature to RTX white point'}
