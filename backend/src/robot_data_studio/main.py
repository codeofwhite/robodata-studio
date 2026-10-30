from contextlib import asynccontextmanager
from importlib import import_module

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import PROJECT_ROOT, require_file, settings
from .db import initialize
from .routes import datasets, episodes, exports, health, sessions
from .services.worker_manager import worker_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    worker_manager.start_monitor()
    try:
        yield
    finally:
        worker_manager.shutdown_monitor()


app = FastAPI(title="RoboData Studio API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
for core_router in (health.router, datasets.router, sessions.router, exports.router):
    app.include_router(core_router, prefix="/api")

# The existing episodes module also contains an experimental rendering API.
# Only register that API when its explicitly selected runtime is present.
if "offline_render" in settings.enabled_extensions:
    require_file(PROJECT_ROOT / "expert_demos/curobo_cloth_v1/render_episode.py",
                 "ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS=offline_render (render runtime)")
episode_router = APIRouter(routes=[
    route for route in episodes.router.routes
    if not route.path.endswith("/isaac-render") or "offline_render" in settings.enabled_extensions
])
app.include_router(episode_router, prefix="/api")

OPTIONAL_ROUTES = {
    "assets": ("assets", "pbr_materials"),
    "cloth": ("cloth", "clothforge_batch"),
    "generation": ("generation", "cloth_generation"),
    "consumer_smokes": ("consumer_smokes",),
}
# The legacy assets router mixes registry APIs with cloth execution/style APIs.
# Selecting the registry must not implicitly enable those execution routes.
REGISTRY_PATHS = {
    "/assets", "/assets/sources", "/assets/artifacts/inspect", "/assets/validation-overview",
    "/assets/{asset_id}", "/assets/{asset_id}/versions/{version}/artifacts/{index}",
    "/assets/{asset_id}/versions/{version}/artifacts/{index}/viewer",
}
for extension, modules in OPTIONAL_ROUTES.items():
    if extension in settings.enabled_extensions:
        for module in modules:
            router = import_module(f".routes.{module}", __package__).router
            if module == "assets" and "cloth" not in settings.enabled_extensions:
                router = APIRouter(routes=[route for route in router.routes if route.path in REGISTRY_PATHS])
            app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"name": "RoboData Studio API", "docs": "/docs"}
