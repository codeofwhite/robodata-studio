from __future__ import annotations


# Solver ids are engine-agnostic names, so the label table lives here rather than
# on any single adapter. An id missing from this table is a bug in the adapter's
# `physics_backends` tuple, so it raises instead of silently rendering a bare id.
PHYSICS_BACKEND_LABELS: dict[str, tuple[str, str]] = {
    "physx": ("PhysX", "NVIDIA PhysX solver, the existing default"),
    "newton": ("Newton", "Newton MJWarp solver driving the scene, rendered by Isaac Sim"),
    "genesis_ipc": ("Genesis + IPC", "Genesis 刚体／可选 FEM Cloth 与 IPC 接触，Isaac Sim RTX 渲染"),
}


def physics_backend_descriptors(backend_ids: tuple[str, ...]) -> list[dict]:
    descriptors = []
    for backend_id in backend_ids:
        try:
            label, description = PHYSICS_BACKEND_LABELS[backend_id]
        except KeyError as exc:
            raise ValueError(f"physics backend has no label: {backend_id}") from exc
        descriptors.append({"id": backend_id, "label": label, "description": description})
    return descriptors
