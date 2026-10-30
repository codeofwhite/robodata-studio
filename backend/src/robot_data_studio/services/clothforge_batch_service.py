"""Sequential ClothForge batches using the existing isolated Newton runner."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from ..config import BACKEND_ROOT, CONTRACTS_SRC, PROJECT_ROOT, settings
from .cloth_run_service import newton_cloth_run_manager


def directory(plan_id):
    if len(plan_id) != 32 or any(c not in '0123456789abcdef' for c in plan_id):
        raise ValueError('invalid ClothForge plan ID')
    return settings.data_root / 'clothforge_batches' / plan_id


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def preview(payload):
    plan_id = uuid4().hex
    attempts = []
    for garment in payload['garments']:
        prepared = newton_cloth_run_manager.prepare(**garment, scenario=payload['scenario'],
            material_id=payload['material_id'], material_overrides=payload['material_overrides'],
            solver_overrides=payload['solver_overrides'])
        attempts.append({**garment, 'name': prepared['model'].name,
                         'category': prepared['manifest']['category'],
                         'mesh_sha256': prepared['manifest']['mesh_sha256'],
                         'config': prepared['config'], 'status': 'pending', 'run_id': None})
    plan = {'plan_id': plan_id, 'status': 'preview', 'scenario': payload['scenario'],
            'material_id': payload['material_id'], 'material_overrides': payload['material_overrides'],
            'solver_overrides': payload['solver_overrides'], 'gpu': settings.clothforge_gpu_id,
            'attempts': attempts, 'error': None}
    root = directory(plan_id)
    root.mkdir(parents=True)
    write(root / 'state.json', plan)
    return get(plan_id)


def get(plan_id):
    plan = json.loads((directory(plan_id) / 'state.json').read_text())
    for attempt in plan['attempts']:
        if attempt['run_id']:
            run = newton_cloth_run_manager.get(attempt['run_id'])
            attempt.update(status=run['status'], progress=run['progress'], outcome=run['outcome'],
                           error=run['error'], validation_asset_id=run['validation_asset_id'],
                           config_asset_id=run['config_asset_id'])
    plan['total'] = len(plan['attempts'])
    plan['completed'] = sum(a['status'] in {'completed', 'failed'} for a in plan['attempts'])
    plan['succeeded'] = sum(a.get('outcome') == 'passed' for a in plan['attempts'])
    return plan


def start(plan_id):
    root = directory(plan_id)
    with (root / '.start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan = get(plan_id)
        if plan['status'] != 'preview':
            raise ValueError('该批次已启动，请查看进度或新建计划')
        plan['status'] = 'running'
        write(root / 'state.json', plan)
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join([str(BACKEND_ROOT / 'src'), str(CONTRACTS_SRC), env.get('PYTHONPATH', '')])
        with (root / 'supervisor.log').open('w') as log:
            try:
                child = subprocess.Popen([sys.executable, '-B', '-m', __name__, '--execute', plan_id],
                    cwd=PROJECT_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as error:
                plan.update(status='failed', error=str(error))
                write(root / 'state.json', plan)
                raise
        # The child owns state updates; page/API reloads do not stop its runs.
        return {**plan, 'worker_pid': child.pid}


def execute(plan_id):
    root = directory(plan_id)
    plan = json.loads((root / 'state.json').read_text())
    for attempt in plan['attempts']:
        try:
            prepared = newton_cloth_run_manager.prepare(attempt['asset_id'], attempt['version'],
                scenario=plan['scenario'], material_id=plan['material_id'],
                material_overrides=plan['material_overrides'], solver_overrides=plan['solver_overrides'])
            if prepared['config'] != attempt['config']:
                raise ValueError('衣物参数在预览后变化，请新建计划')
            run = newton_cloth_run_manager.start(attempt['asset_id'], attempt['version'],
                scenario=plan['scenario'], material_id=plan['material_id'],
                material_overrides=plan['material_overrides'], solver_overrides=plan['solver_overrides'])
            attempt.update(run_id=run['run_id'], status=run['status'])
            write(root / 'state.json', plan)
            while run['status'] in {'queued', 'running'}:
                time.sleep(1)
                run = newton_cloth_run_manager.get(run['run_id'])
            attempt.update(status=run['status'], outcome=run['outcome'], error=run['error'])
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            attempt.update(status='failed', error=str(error))
        write(root / 'state.json', plan)
    plan['status'] = 'completed'
    write(root / 'state.json', plan)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', required=True)
    execute(parser.parse_args().execute)
