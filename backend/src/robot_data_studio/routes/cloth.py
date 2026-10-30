import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel,ConfigDict,Field
from ..services.cloth_catalog_service import catalog
from ..services.cloth_episode_importer import import_completed
from ..services.cloth_run_service import cloth_comparison_manager

router=APIRouter(tags=['cloth'])
class ImportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    batch:str|None=None
    run_id:str|None=None
    dry_run:bool=True
class CompareRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    asset_id:str
    version:int=Field(default=1,ge=1)
    scenario:str='hanging'
    material_id:str='medium'
    engine_ids:list[str]|None=None
    reuse:bool=True

def call(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except (ValueError,KeyError,OSError) as e:raise HTTPException(422,str(e)) from e
@router.get('/cloth/tasks')
def tasks():return call(catalog)
@router.post('/cloth/import')
def import_episodes(request:ImportRequest):return call(import_completed,**request.model_dump())
@router.post('/cloth/comparisons',status_code=202)
def compare(request:CompareRequest):return call(cloth_comparison_manager.start_pair,**request.model_dump())
@router.get('/cloth/solver-results')
def saved_results(asset_id:str,version:int=1,scenario:str='hanging',material_id:str='medium'):
    return call(cloth_comparison_manager.saved_trajectories,asset_id,version,scenario,material_id)
@router.get('/cloth/comparisons')
def comparisons():
    rows=[]
    for path in sorted(cloth_comparison_manager.run_root.glob('run-*/state.json'),reverse=True):
        state=json.loads(path.read_text())
        if state.get('engine_id')=='comparison':rows.append({k:state.get(k) for k in ['run_id','status','asset_id','scenario','material_id','engine_ids','reused_children']})
    return {'items':rows[:100]}
@router.get('/cloth/comparisons/{run_id}')
def comparison(run_id:str):return call(cloth_comparison_manager.get_pair,run_id)
@router.get('/cloth/comparisons/{run_id}/trajectory')
def trajectory(run_id:str):return call(cloth_comparison_manager.trajectories,run_id)
