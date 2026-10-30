"""Non-colliding, UV-mapped visual surfaces over explicitly selected static prims."""
from .pbr_material import Appearance, EnvironmentAppearance, verify_maps


def validate_environment(raw):
    # Resolved map paths are provenance, not editable schema fields.
    request = {target: {k: v for k, v in value.items() if k in Appearance.model_fields}
               if value is not None else None for target, value in (raw or {}).items()}
    EnvironmentAppearance.model_validate(request)
    for value in (raw or {}).values():
        if value is not None:
            if value.get('material_id') and set(value.get('maps', {})) != {'base_color', 'normal', 'roughness'}:
                raise ValueError('环境 PBR 材质缺少完整贴图')
            verify_maps(value)


def workstation_targets(composition):
    return {'tabletop': [composition['table_prim_path']],
            'background': ['/World/Workstation/Backdrop']}


def replay_targets(stage, binding):
    """Resolve known authored surface names; never infer tables from their material."""
    if binding:
        table = [item['prim'] for item in binding['collision_prims']
                 if stage.GetPrimAtPath(item['prim']).GetName().startswith('Worktop')]
        walls = [item['prim'] for item in binding['collision_prims']
                 if stage.GetPrimAtPath(item['prim']).GetName().startswith(('BackWall', 'SideWall'))]
    else:
        table = [str(p.GetPath()) for p in stage.GetPrimAtPath('/World').GetChildren() if p.GetName().startswith('Table')]
        walls = [str(p.GetPath()) for p in stage.GetPrimAtPath('/World').GetChildren() if p.GetName().startswith('Wall')]
    return {'tabletop': table, 'background': walls}


def apply_environment(stage, environment, targets):
    """Keep source geometry/collision intact; render duplicated faces 0.1 mm outside."""
    from pxr import UsdGeom, UsdShade, Vt, Sdf, Gf
    import numpy as np
    from .usd_material import create_material
    validate_environment(environment)
    applied = []
    transforms = UsdGeom.XformCache()
    for target, appearance in (environment or {}).items():
        if appearance is None:
            continue
        paths = targets.get(target, [])
        if not paths:
            raise ValueError('场景没有可应用材质的表面：' + target)
        material = create_material(stage, '/World/SurfaceAppearance/Materials/' + target, appearance)
        for index, path in enumerate(paths):
            prim = stage.GetPrimAtPath(path)
            if not prim:
                raise ValueError('环境表面不存在：' + path)
            transform = transforms.GetLocalToWorldTransform(prim)
            if prim.IsA(UsdGeom.Cube):
                half = UsdGeom.Cube(prim).GetSizeAttr().Get() / 2
                points = np.array([[x,y,z] for z in (-half,half) for y in (-half,half) for x in (-half,half)])
                faces = [[0,2,3,1], [4,5,7,6], [0,1,5,4], [2,6,7,3], [0,4,6,2], [1,3,7,5]]
            elif prim.IsA(UsdGeom.Mesh):
                source = UsdGeom.Mesh(prim)
                points = np.asarray(source.GetPointsAttr().Get(), dtype=float)
                counts = source.GetFaceVertexCountsAttr().Get()
                indices = source.GetFaceVertexIndicesAttr().Get()
                faces, start = [], 0
                for count in counts:
                    faces.append(list(indices[start:start+count])); start += count
            else:
                raise ValueError('环境表面需要 Cube 或 Mesh：' + path)
            world = np.array([list(transform.Transform(Gf.Vec3d(*point))) for point in points])
            vertices, uv, counts = [], [], []
            for face in faces:
                polygon = world[face]
                normal = np.cross(polygon[1]-polygon[0], polygon[2]-polygon[0])
                length = np.linalg.norm(normal)
                if length < 1e-12:
                    raise ValueError('环境表面包含退化面：' + path)
                normal /= length
                # Metre-based projection keeps patterns useful even on the 200 m backdrop.
                axis = int(np.argmax(np.abs(normal)))
                axes = [a for a in (0,1,2) if a != axis]
                uv.extend(polygon[:, axes].tolist())
                vertices.extend((polygon + normal * .0001).tolist()); counts.append(len(face))
            overlay_path = f'/World/SurfaceAppearance/{target}_{index}'
            mesh = UsdGeom.Mesh.Define(stage, overlay_path)
            mesh.CreatePointsAttr().Set(Vt.Vec3fArray.FromNumpy(np.asarray(vertices, np.float32)))
            mesh.CreateFaceVertexCountsAttr().Set(counts)
            mesh.CreateFaceVertexIndicesAttr().Set(list(range(len(vertices))))
            mesh.CreateSubdivisionSchemeAttr().Set('none'); mesh.CreateDoubleSidedAttr().Set(True)
            UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray, 'faceVarying').Set(
                Vt.Vec2fArray.FromNumpy(np.asarray(uv, np.float32)))
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
            applied.append({'target': target, 'source_prim': path, 'visual_prim': overlay_path,
                            'uv_units': 'metres', 'visual_offset_m': .0001, 'collision_enabled': False})
    return applied
