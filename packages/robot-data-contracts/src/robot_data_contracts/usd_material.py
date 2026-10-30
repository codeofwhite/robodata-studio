"""Shared UsdPreviewSurface binding; simulator libraries are imported lazily."""
from .pbr_material import verify_maps


def create_material(stage, path, appearance):
    from pxr import UsdShade, Sdf, Gf
    verify_maps(appearance)
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + '/Surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    tint = tuple(int(appearance['color'][i:i+2], 16) / 255 for i in (1, 3, 5))
    if appearance.get('material_id') and appearance.get('color_mode', 'original') == 'original':
        tint = (1., 1., 1.)
    shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*tint))
    shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(appearance['roughness'])
    shader.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(0.)
    reader = UsdShade.Shader.Define(stage, path + '/UV')
    reader.CreateIdAttr('UsdPrimvarReader_float2')
    reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
    reader.CreateOutput('result', Sdf.ValueTypeNames.Float2)
    transform = UsdShade.Shader.Define(stage, path + '/Transform')
    transform.CreateIdAttr('UsdTransform2d')
    transform.CreateInput('in', Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), 'result')
    repeat = appearance.get('uv_scale', 1.)
    transform.CreateInput('scale', Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(repeat, repeat))
    transform.CreateOutput('result', Sdf.ValueTypeNames.Float2)
    maps = appearance.get('maps', {})
    if not maps and appearance.get('texture_path'):
        maps = {'base_color': {'path': appearance['texture_path'], 'sha256': appearance['texture_sha256']}}
        verify_maps({'maps': maps})
    for role, entry in maps.items():
        tex = UsdShade.Shader.Define(stage, path + '/' + role)
        tex.CreateIdAttr('UsdUVTexture')
        tex.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(entry['path']))
        tex.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('sRGB' if role == 'base_color' else 'raw')
        tex.CreateInput('wrapS', Sdf.ValueTypeNames.Token).Set('repeat')
        tex.CreateInput('wrapT', Sdf.ValueTypeNames.Token).Set('repeat')
        tex.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(transform.ConnectableAPI(), 'result')
        tex.CreateOutput('rgb', Sdf.ValueTypeNames.Float3)
        tex.CreateOutput('r', Sdf.ValueTypeNames.Float)
        if role == 'base_color':
            tex.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*tint, 1.))
            shader.GetInput('diffuseColor').ConnectToSource(tex.ConnectableAPI(), 'rgb')
        elif role == 'roughness':
            strength = appearance.get('roughness_multiplier', 1.)
            tex.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(strength, strength, strength, 1.))
            shader.GetInput('roughness').ConnectToSource(tex.ConnectableAPI(), 'r')
        elif role == 'normal':
            strength = appearance.get('normal_strength', 1.)
            tex.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(2*strength, 2*strength, 2., 1.))
            tex.CreateInput('bias', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-strength, -strength, -1., 0.))
            shader.CreateInput('normal', Sdf.ValueTypeNames.Normal3f).ConnectToSource(tex.ConnectableAPI(), 'rgb')
    shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    return material
