#!/usr/bin/env python3
"""Explicit, bounded, same-machine catalog/preparation/physics reproduction.

Public templates contain no asset payloads or host paths. Every invocation needs
its own output directory outside the checkout. Importing this module performs no
network, acquisition, SDK launch, or filesystem mutation.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE = REPOSITORY / 'examples/catalog_gravity_cell'
PREPARED_SHA_MARKER = '${notebook.prepared_manifest_sha256}'


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    from simscene.preparation.jobs import write
    write(path, value)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def assert_portable(value):
    """Templates may contain USD actor paths and public URLs, never host paths."""
    if isinstance(value, dict):
        for item in value.values():
            assert_portable(item)
    elif isinstance(value, list):
        for item in value:
            assert_portable(item)
    elif isinstance(value, str) and ((value.startswith('/') and not value.startswith('/World/')) or re.match(r'^[A-Za-z]:[\\/]', value)):
        raise ValueError('public template contains a host-specific absolute path')


def safe_member(value):
    if not isinstance(value, str) or not value or any(c in value for c in ('\\', '%', '?', '#', ':')) or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('unsafe selected package member')
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError('selected package member must be relative')
    return path


def verify_source_lock(acquired, locked):
    """ZIP timestamps and mutable cache locations are excluded from content identity."""
    from simscene.cache import AssetCache
    if AssetCache.content_identity(acquired.get('files')) != locked['content_sha256']:
        raise ValueError('source_content_changed: selected asset closure differs from assets.lock.json')
    actual = {(f['url'], f['size'], f['sha256']) for f in acquired['files']}
    expected = {(f['url'], f['size'], f['sha256']) for f in locked['files']}
    if actual != expected:
        raise ValueError('source_content_changed: selected file inventory differs')
    if locked.get('source_manifest_sha256') is not None and acquired.get('manifest_sha256') != locked['source_manifest_sha256']:
        raise ValueError('source_content_changed: selected source manifest differs')
    if acquired.get('source_ref') is not None and acquired['source_ref'] != locked['source_ref']:
        raise ValueError('source_content_changed: selected source reference differs')


def compile_scene(recipe, prepared, workbench_member, *, mode='routing', record=False):
    """Substitute named assets into ordinary scene objects; no physics shortcuts."""
    assert_portable(recipe)
    if recipe.get('schema') != 'simscene.catalog_gravity_cell.recipe.v1' or recipe.get('schema_version') != 1:
        raise ValueError('unsupported catalog gravity-cell recipe')
    if mode not in {'routing', 'smoke'}:
        raise ValueError('unsupported diagnostic mode')
    if not re.fullmatch('[0-9a-f]{64}', str(prepared.get('manifest_sha256', ''))):
        raise ValueError('current verified prepared manifest SHA-256 is required')
    objects = deepcopy(recipe['objects'])
    for name in list(objects):
        obj = objects[name]
        if mode == 'smoke' and obj.get('asset_role') == 'notebook' and name != 'book_left_front':
            del objects[name]; continue
        if not record and obj.get('kind') == 'camera':
            del objects[name]; continue
        role = obj.pop('asset_role', None)
        if role == 'notebook':
            if obj.get('kind') != 'asset' or not obj.get('dynamic'):
                raise ValueError('notebook role must remain a dynamic imported asset')
            obj['asset_path'] = prepared['root']
            obj['asset_binding'] = {'manifest_path': prepared['manifest_path'], 'manifest_sha256': prepared['manifest_sha256']}
        elif role == 'workbench':
            obj['asset_path'] = str(workbench_member)
            if obj.get('asset_physics') != 'visual_only':
                raise ValueError('legacy workbench must remain visual-only with explicit proxy support')
        elif role is not None:
            raise ValueError('unknown asset role')
    return {'schema_version': '0.1', 'scene_id': recipe['scene_id'], 'revision': 0,
            'world': deepcopy(recipe['world']), 'objects': objects, 'requests': {},
            'observation': deepcopy(recipe['observation']), 'presentation': deepcopy(recipe['presentation'])}


def freeze_case(template, prepared, source_ref, *, mode='routing'):
    """Freeze this attempt's prepared hash before simulation; never rewrite old evidence."""
    assert_portable(template)
    if template.get('prepared_manifest_sha256') != PREPARED_SHA_MARKER:
        raise ValueError('case must be a template; never reinterpret an already frozen physical run')
    if template.get('source_ref') != source_ref:
        raise ValueError('case source reference differs from the selected locked asset')
    if not re.fullmatch('[0-9a-f]{64}', str(prepared.get('manifest_sha256', ''))):
        raise ValueError('cannot freeze case without a verified prepared manifest SHA')
    result = deepcopy(template)
    result['prepared_manifest_sha256'] = prepared['manifest_sha256']
    if mode == 'smoke':
        result['objects'] = {'book_left_front': result['objects']['book_left_front']}
    elif mode != 'routing':
        raise ValueError('unsupported diagnostic mode')
    from simscene.verification.rigid_asset_smoke import validate_case
    return validate_case(result)


class SceneBudget:
    """Serial accounting for newly downloaded model/dependency payload bytes."""
    def __init__(self, limit=2 * 1024**3):
        self.limit = limit
        self.by_stage = {}
        self.unknown_stages = {}
    @property
    def actual(self):
        return sum(self.by_stage.values())
    @property
    def remaining(self):
        return self.limit - self.actual - sum(self.unknown_stages.values())
    def update(self, stage, cumulative):
        if type(cumulative) is not int or cumulative < self.by_stage.get(stage, 0):
            raise ValueError('invalid cumulative transfer accounting')
        self.by_stage[stage] = cumulative
        self.unknown_stages.pop(stage, None)
        if self.actual > self.limit:
            raise ValueError('scene_download_budget_exceeded')
    def unknown(self, stage, maximum):
        self.unknown_stages[stage] = maximum
    def to_dict(self):
        return {'accounting_complete': not self.unknown_stages, 'unknown_transfer_upper_bounds': dict(self.unknown_stages),
                'limit_bytes': self.limit, 'actual_download_bytes': self.actual,
                'remaining_bytes': self.remaining, 'stages': dict(self.by_stage),
                'scope': 'serial actual model/dependency transfers, including failed reads; metadata indexes use separate budgets'}


@contextmanager
def isolated_environment(output, *, warm_cache=None, runtime_manifest=None):
    from simscene.catalog.config import read
    from simscene.settings import get
    base = read()
    launcher = get('isaac_python')
    observation = Path(runtime_manifest or base['runtime_manifest']).expanduser().resolve()
    if not observation.is_file():
        raise ValueError('environment_probe_required: explicitly configure/probe the runtime before this experiment')
    cache = Path(warm_cache).expanduser().resolve() if warm_cache else output / 'artifact-cache'
    if warm_cache and (not (cache / 'source-cache').is_dir() or not (cache / 'prepared-cache').is_dir()):
        raise ValueError('warm cache root must already contain source-cache and prepared-cache directories')
    if cache.is_relative_to(REPOSITORY):
        raise ValueError('asset caches must stay outside the checkout')
    current_observation = output / 'runtime-observation.json'
    shutil.copyfile(observation, current_observation)
    versioned = {'schema_version': 1, 'index_directory': str(cache / 'catalog-index'),
                 'prepared_directory': str(cache / 'prepared-cache'), 'runtime_manifest': str(current_observation),
                 'asset_download_bytes': 1024**3, 'scene_download_bytes': 2 * 1024**3,
                 'unpacked_bytes': 4 * 1024**3, 'staging_bytes': 4 * 1024**3,
                 'prepared_cache_bytes': 4 * 1024**3, 'metadata_max_bytes': 32 * 1024**2,
                 'search_deadline_seconds': 12}
    if base.get('converter_tools_prefix'):
        versioned['converter_tools_prefix'] = base['converter_tools_prefix']
    config_path = output / 'v2-config.json'; write_json(config_path, versioned)
    changes = {'SIMSCENE_HOME': str(output / 'state'), 'SIMSCENE_CACHE': str(cache / 'source-cache'),
               'SIMSCENE_CACHE_BYTES': str(2 * 1024**3), 'SIMSCENE_V2_CONFIG': str(config_path),
               'SIMSCENE_PHYSICS_DEVICE': 'cpu'}
    if launcher:
        changes['SIMSCENE_ISAAC_PYTHON'] = launcher
    previous = {key: os.environ.get(key) for key in changes}
    os.environ.update(changes)
    try:
        configuration = read()
        from simscene.preparation.environment import current_runtime
        current_runtime(config=configuration)  # CPU-only validation of an actual prior SDK observation.
        yield configuration
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def find_selected(query, locked, config, output):
    from simscene.catalog.models import SearchRequest, AssetRef
    from simscene.catalog.search import search_assets
    from simscene.catalog.store import CatalogStore
    from simscene.catalog.providers.abo import ABOProvider
    from simscene.catalog.providers.nvidia import NvidiaProvider
    source_id = locked['source_ref']['source_id']
    store = CatalogStore(config['index_directory'])
    provider = ABOProvider(store) if source_id == 'abo-glb' else NvidiaProvider(store, candidate_limit=20)
    if source_id == 'abo-glb' and provider.snapshot == 'index_not_refreshed':
        provider.configure(time.monotonic() + 12, [])
        try:
            refreshed = provider.refresh()
            write_json(output / 'abo-index-refresh.json', dict(refreshed, requests=provider.ledger))
        except Exception:
            write_json(output / 'abo-index-refresh-failed.json', {'requests': provider.ledger})
            raise
    request = SearchRequest(query, source_ids=(source_id,), limit=20)
    for number in range(5):
        page = search_assets(request, providers={source_id: provider}, index_directory=config['index_directory'])
        write_json(output / (source_id + '-search-' + str(number) + '.json'), page.to_dict())
        write_json(output / (source_id + '-metadata-ledger.json'), provider.ledger)
        if page.status not in {'ok', 'partial'}:
            raise ValueError('selected_source_unavailable: ' + source_id)
        for item in page.items:
            if item['ref'] == locked['source_ref']:
                return provider.resolve(AssetRef.from_dict(item['ref']))
        if not page.next_cursor:
            break
        from dataclasses import replace
        request = replace(request, cursor=page.next_cursor)
    raise ValueError('locked_selection_not_found: no replacement asset is permitted')


def acquire_workbench(locked, config, output, budget):
    from simscene.acquisition.dispatch import _BudgetUSDSearch
    from simscene.acquisition.transfer import TransferBudget, transfer_scope
    from simscene.acquisition.locks import copy_acquired_to_job
    from simscene.cache import AssetCache
    limit = min(512 * 1024**2, budget.remaining)
    transaction = TransferBudget(limit, 1024**3, 2 * 1024**3)
    record = {'schema_version': 1, 'route': 'legacy_usd_compatibility', 'license': locked['license'],
              'source_terms': locked['source_terms'], 'state': 'acquiring'}
    try:
        with transfer_scope(transaction):
            acquired = AssetCache(_BudgetUSDSearch(transaction), config['asset_cache_directory'],
                                  max_bytes=config['asset_cache_capacity_bytes']).acquire(locked['source_url'])
        verify_source_lock(acquired, locked)
        if acquired.get('dependency_status') not in {'resolved_locally', 'resolved_with_runtime'}:
            raise ValueError('legacy_workbench_dependency_closure_incomplete')
        acquired = dict(acquired, source_ref=locked['source_ref'], license=locked['license'],
                        provenance={'source_terms': locked['source_terms']}, actual_download_bytes=transaction.actual_download_bytes,
                        transfer_ledger=transaction.ledger)
        copied = copy_acquired_to_job(acquired, config['asset_cache_directory'], output / 'asset-inputs' / acquired['package_sha256'], 2 * 1024**3)
        relative_root = next(f['path'] for f in copied['files'] if f['url'] == copied['source'])
        base = Path(copied['root'])
        for _ in PurePosixPath(relative_root).parts:
            base = base.parent
        member = base.joinpath(*safe_member(locked['selected_member']['path']).parts)
        if not member.is_file() or sha256(member) != locked['selected_member']['sha256']:
            raise ValueError('source_content_changed: selected bare-table member changed')
        record.update(state='completed', acquired=copied, selected_member=str(member))
        return member
    except Exception as error:
        record.update(state='failed', error=str(error))
        raise
    finally:
        budget.update('legacy_workbench', transaction.actual_download_bytes)
        record.update(actual_download_bytes=transaction.actual_download_bytes, transfer_ledger=transaction.ledger)
        write_json(output / 'workbench-acquisition.json', record)
        write_json(output / 'download-budget.json', budget.to_dict())


def wait_job(identifier, *, preparation, config, output, budget=None, timeout=1800):
    from simscene import jobs
    from simscene.preparation import jobs as preparation_jobs
    deadline = time.monotonic() + timeout
    history = output / ('prepare-status.jsonl' if preparation else 'simulation-status.jsonl')
    while True:
        status = preparation_jobs.status(identifier, config=config) if preparation else jobs.status(identifier)
        with history.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(status, ensure_ascii=False, allow_nan=False) + '\n')
        if preparation and budget is not None:
            actual = status.get('actual_download_bytes')
            if actual is None:
                actual = (status.get('result') or {}).get('actual_download_bytes')
            if actual is not None:
                budget.update('notebook_prepare', actual)
                write_json(output / 'download-budget.json', budget.to_dict())
        if status['state'] in {'completed', 'failed', 'cancelled', 'uncertain'}:
            write_json(output / ('prepare-status.json' if preparation else 'simulation-status.json'), status)
            if status['state'] != 'completed':
                if preparation and budget is not None and actual is None:
                    budget.unknown('notebook_prepare', 16 * 1024**2)
                    write_json(output / 'download-budget.json', budget.to_dict())
                raise ValueError('job_' + status['state'] + ': ' + identifier)
            return status
        if time.monotonic() >= deadline:
            if preparation and budget is not None and actual is None:
                budget.unknown('notebook_prepare', 16 * 1024**2)
                write_json(output / 'download-budget.json', budget.to_dict())
            cancelled = preparation_jobs.cancel(identifier, config=config) if preparation else jobs.cancel(identifier)
            write_json(output / 'timeout-cancellation-request.json', cancelled)
            raise TimeoutError('job wait deadline exceeded; cancellation requested, inspect retained worker state')
        time.sleep(0.5)


def run(args):
    recipe = read_json(args.recipe); template = read_json(args.case)
    lock_path = Path(args.assets_lock) if args.assets_lock else Path(args.recipe).with_name('assets.lock.json')
    locked = read_json(lock_path)
    for value in (recipe, template, locked):
        assert_portable(value)
    if locked.get('schema') != 'simscene.catalog_gravity_cell.assets.v1' or locked.get('schema_version') != 1:
        raise ValueError('unsupported public asset lock')
    if recipe['asset_roles']['notebook']['source_ref'] != locked['assets']['notebook']['source_ref']:
        raise ValueError('recipe source differs from public asset lock')
    output = Path(args.output).expanduser().resolve()
    if output.is_relative_to(REPOSITORY) or output.exists():
        raise ValueError('output must be a NEW directory outside the checkout; failed attempts are retained')
    output.mkdir(parents=True)
    budget = SceneBudget()
    try:
        frozen = output / 'frozen-inputs'; frozen.mkdir()
        for source, name in ((args.recipe, 'recipe.json'), (args.case, 'case-template.json'), (lock_path, 'assets.lock.json'), (__file__, 'driver.py')):
            shutil.copyfile(source, frozen / name)
        write_json(output / 'invocation.json', {'schema_version': 1, 'mode': args.mode, 'record': args.record,
                   'cache_mode': 'warm_explicit' if args.warm_cache else 'cold_isolated',
                   'scope': 'same-machine fixed-layout rebuild; physical success is determined by this new frozen run',
                   'input_sha256': {p.name: sha256(p) for p in frozen.iterdir()}})
        with isolated_environment(output, warm_cache=args.warm_cache, runtime_manifest=args.runtime_manifest) as config:
            notebook = locked['assets']['notebook']; bench = locked['assets']['workbench']
            find_selected(recipe['asset_roles']['workbench']['search_query'], bench, config, output)
            member = acquire_workbench(bench, config, output, budget)
            record = find_selected(recipe['asset_roles']['notebook']['search_query'], notebook, config, output)
            from simscene.acquisition.plans import make_plan
            role = recipe['asset_roles']['notebook']
            plan = make_plan(notebook['source_ref'], role['profile_id'], role['parameters'],
                             budgets={'download_bytes': min(16 * 1024**2, budget.remaining)}, record=record, config=config)
            write_json(output / 'notebook-plan.json', plan)
            if not plan['ready_to_fetch']:
                raise ValueError('notebook_plan_blocked: ' + json.dumps(plan['blocking_reasons']))
            from simscene.preparation import jobs as preparation_jobs
            receipt = preparation_jobs.start(plan['plan_id'], request_id='catalog-mvp-notebook-prepare', config=config)
            write_json(output / 'prepare-receipt.json', receipt)
            prepared_status = wait_job(receipt['job_id'], preparation=True, config=config, output=output, budget=budget, timeout=args.timeout)
            prepared = prepared_status['result']
            acquired = read_json(Path(prepared_status['record_path']).parent / 'acquired.json')
            verify_source_lock(acquired, notebook)
            from simscene.physics_binding import validate_asset_binding
            metadata = validate_asset_binding({'manifest_path': prepared['manifest_path'], 'manifest_sha256': prepared['manifest_sha256']}, require_dynamic=True, asset_path=prepared['root'])
            if metadata['source_ref'] != notebook['source_ref']:
                raise ValueError('prepared source reference differs from public lock')
            scene = compile_scene(recipe, prepared, member, mode=args.mode, record=args.record)
            case = freeze_case(template, prepared, notebook['source_ref'], mode=args.mode)
            case_path = output / 'case.frozen.json'; write_json(case_path, case)
            write_json(output / 'scene.compiled.json', scene)
            write_json(output / 'prepared-selection.json', dict(prepared, source_ref=notebook['source_ref'],
                       case_sha256=sha256(case_path), case_scope='new attempt; earlier proof hashes are never reinterpreted'))
            from simscene.scene import SceneStore
            store = SceneStore(); current = store.open(scene['scene_id'])
            operations = [{'op': 'add', 'id': name, 'object': value} for name, value in scene['objects'].items()]
            operations += [{'op': 'set_observation', 'observation': scene['observation']},
                           {'op': 'set_presentation', 'presentation': scene['presentation']}]
            applied = store.apply(scene['scene_id'], current['revision'], 'catalog-mvp-compile', operations)
            write_json(output / 'scene-apply.json', applied)
            from simscene import jobs
            receipt = jobs.start(scene['scene_id'], steps=recipe['run']['steps'], seed=recipe['run']['seed'],
                                 case_path=str(case_path), request_id='catalog-mvp-physical-run')
            write_json(output / 'simulation-receipt.json', receipt)
            status = wait_job(receipt['job_id'], preparation=False, config=config, output=output, timeout=args.timeout)
            from simscene.verification.case_runner import evaluate
            run_directory = Path(status['result_file']).parent
            verification = evaluate(run_directory, case_path, case_type='rigid_asset_smoke')
            write_json(output / 'verification.json', verification)
            summary = {'schema_version': 1, 'passed': verification['passed'], 'scope': 'same-machine fixed-layout physical rebuild',
                       'mode': args.mode, 'run_directory': str(run_directory), 'case_sha256': sha256(case_path),
                       'prepared_manifest_sha256': prepared['manifest_sha256'], 'download_budget': budget.to_dict(),
                       'workbench_route': 'legacy_usd_compatibility', 'workbench_license': bench['license'],
                       'recording_requested': args.record, 'video_delivery_complete': False}
            write_json(output / 'summary.json', summary)
            return summary
    except Exception as error:
        write_json(output / 'failed-attempt.json', {'schema_version': 1, 'state': 'failed', 'error': str(error),
                   'download_budget': budget.to_dict(), 'scope': 'all attempt files retained; no automatic asset substitution or retry'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', default=str(EXAMPLE / 'recipe.json'))
    parser.add_argument('--case', default=str(EXAMPLE / 'case.json'))
    parser.add_argument('--assets-lock')
    parser.add_argument('--output', required=True)
    parser.add_argument('--warm-cache', help='explicit existing root with source-cache and prepared-cache; default is isolated cold cache')
    parser.add_argument('--runtime-manifest', help='actual prior SDK observation; no automatic probe or tool installation')
    parser.add_argument('--timeout', type=float, default=1800)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--smoke', dest='mode', action='store_const', const='smoke')
    mode.add_argument('--routing', dest='mode', action='store_const', const='routing')
    parser.set_defaults(mode='routing')
    parser.add_argument('--record', action='store_true', help='retain the recipe diagnostic cameras; no final-video delivery claim')
    args = parser.parse_args()
    if not 0 < args.timeout <= 7200:
        parser.error('--timeout must be between 0 and 7200 seconds')
    try:
        result = run(args)
        print(json.dumps(result, indent=2))
        return 0 if result['passed'] else 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
