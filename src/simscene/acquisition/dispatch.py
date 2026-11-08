"""Acquire exactly a frozen selection, reusing the legacy cache and repair path."""
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from ..assets import USDSearch, SearchError
from ..cache import AssetCache
from ..catalog.config import read as configuration
from ..catalog.models import AssetRef, canonical_json
from .glb import acquire_glb
from .locks import copy_acquired_to_job
from .transfer import TransferBudget, transfer_scope


class _BudgetUSDSearch(USDSearch):
    """Use the existing cache protocol with transaction-scoped stream bounds."""
    def __init__(self, budget):
        super().__init__()
        self.budget = budget

    def request(self, path, params=None, body=None, binary=False, output=None, max_bytes=None):
        if path != '/download/asset' or body is not None or binary:
            raise SearchError('selected USD acquisition permits only package requests')
        url = self.base_url + path
        if params:
            url += '?' + urlencode(params)
        headers = {}
        user, password = os.getenv('USD_SEARCH_API_USERNAME'), os.getenv('USD_SEARCH_API_PASSWORD')
        token = os.getenv('USD_SEARCH_API_TOKEN')
        if user and password:
            headers['Authorization'] = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
        elif token and token != 'x':
            headers['Authorization'] = 'Bearer ' + token
        if output is not None:
            size, _ = self.budget.download(url, output, headers=headers, max_bytes=max_bytes)
            return size
        payload = self.budget.download(url, category='metadata', headers=headers, max_bytes=1024 * 1024)
        try:
            result = json.loads(payload)
        except ValueError:
            raise SearchError('selected USD manifest preview is not JSON') from None
        if not isinstance(result, dict):
            raise SearchError('selected USD manifest preview is not an object')
        return result


def _manifest_hash(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError('acquire_selected requires an immutable plan object')
    if type(plan.get('schema_version')) is not int or plan['schema_version'] != 1:
        raise ValueError('unsupported acquisition plan schema_version')
    payload = {key: value for key, value in plan.items() if key not in {'plan_id', 'plan_payload_sha256', 'plan_ref'}}
    digest = hashlib.sha256(canonical_json(payload, exclude_volatile=False).encode()).hexdigest()
    if plan.get('plan_id') != digest or plan.get('plan_payload_sha256') != digest:
        raise ValueError('verification_failed: immutable acquisition plan changed')
    if plan.get('ready_to_fetch') is not True or plan.get('blocking_reasons'):
        raise ValueError('acquisition plan is blocked')
    ref = AssetRef.from_dict(plan['asset_ref'])
    ref.validate_selection()
    budgets = plan.get('budget_breakdown', {})
    if set(budgets) != {'download_bytes', 'unpacked_bytes', 'staging_bytes'}:
        raise ValueError('plan must freeze separate download, unpacked and staging budgets')
    for value in budgets.values():
        if type(value) is not int or value <= 0:
            raise ValueError('frozen acquisition budgets must be positive integers')
    return ref, budgets


def acquire_selected(plan, *, config=None, job_directory=None):
    """Acquire a selected closure and optionally freeze verified job input copies.

    Cache capacity comes from configuration; the plan's network, unpacked, and
    staging limits never become a global cache eviction limit.
    """
    ref, limits = _validate_plan(plan)
    config = config or configuration()
    directory = Path(config['asset_cache_directory']).expanduser().resolve()
    capacity = config['asset_cache_capacity_bytes']
    descriptor = plan.get('acquisition', {})
    if ref.source_id == 'local-sand3d' and descriptor.get('kind') == 'generated_package':
        from ..generation.acquisition import acquire_generated
        return acquire_generated(plan,config,job_directory)
    source_record = plan.get('source_snapshot', {})
    license_info = plan.get('license_decision')
    provenance = source_record.get('provenance') or {}
    if descriptor.get('kind') == 'http_files' and ref.source_id=='polyhaven':
        from ..catalog.registry import load_registry
        source=load_registry(config.get('registry_path')).get(ref.source_id)
        if source.adapter!='http_assets' or source.state not in {'audited','enabled'}:
            raise ValueError('HTTP source is not admitted')
        from .http_files import acquire_http_files
        return acquire_http_files(descriptor,ref,limits,config,source_record,license_info,provenance,job_directory)
    if descriptor.get('kind') == 'hf_usd_package':
        from ..catalog.registry import load_registry
        source=load_registry(config.get('registry_path')).get(ref.source_id)
        if (source.state not in {'audited','enabled'} or source.adapter not in {'usdcraft','simready_package'}
                or descriptor.get('repository') != source.repository or descriptor.get('revision') != ref.revision
                or descriptor.get('path') != source_record.get('entry_path')):
            raise ValueError('native selection differs from its admitted source descriptor')
        from .hf_package import acquire_hf_package
        return acquire_hf_package(descriptor,ref,limits,config,source_record,license_info,provenance,job_directory)
    transaction = TransferBudget(limits['download_bytes'], limits['unpacked_bytes'], limits['staging_bytes'])
    try:
        with transfer_scope(transaction):
            if descriptor.get('kind') in {'hf_glb', 'hf_single_glb'}:
                from ..catalog.registry import load_registry
                source=load_registry(config.get('registry_path')).get(ref.source_id)
                if (source.state not in {'audited','enabled'} or source.adapter not in {'abo','hf_manifest'}
                        or descriptor.get('repository') != source.repository or descriptor.get('path') != source_record.get('entry_path')):
                    raise ValueError('GLB selection requires its audited source repository')
                if descriptor.get('revision') != ref.revision:
                    raise ValueError('selected HF revision differs from frozen source reference')
                acquired = acquire_glb(descriptor['repository'], descriptor['revision'], descriptor['path'],
                    directory, download_budget_bytes=limits['download_bytes'], cache_capacity_bytes=capacity,
                    staging_budget_bytes=min(limits['staging_bytes'], limits['unpacked_bytes']),
                    source_ref=ref.to_dict(), metadata=source_record,
                    license=license_info, provenance=provenance,
                    additional_paths=descriptor.get('additional_paths', ['LICENSE-CC-BY-4.0.txt']))
            elif ref.source_id == 'nvidia-usd-search' and descriptor.get('kind') == 'usd_dependency_closure':
                url = descriptor.get('asset_url')
                if not isinstance(url, str):
                    raise ValueError('USD plan has no selected asset locator')
                if ref.asset_id != url:
                    raise ValueError('USD locator differs from frozen asset reference')
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError('USD selection requires a credential-free HTTPS asset locator')
                acquired = AssetCache(_BudgetUSDSearch(transaction), directory, max_bytes=capacity).acquire(url)
            else:
                raise ValueError('unsupported frozen acquisition adapter')
        manifest = _manifest_hash(acquired['files'])
        if acquired.get('manifest_sha256') not in (None, manifest):
            raise SearchError('acquired source manifest changed')
        # With no opt-in GLB hook, retain that downloader's byte accounting.
        actual = transaction.actual_download_bytes or acquired.get('actual_download_bytes', 0)
        acquired = dict(acquired, source_ref=ref.to_dict(), license=license_info, provenance=provenance,
                        manifest_sha256=manifest, source_manifest_hash=manifest,
                        actual_download_bytes=actual, transfer_ledger=transaction.ledger)
        acquired.setdefault('asset_handle', 'acquired:sha256:' + acquired['package_sha256'])
        if job_directory is not None:
            acquired = copy_acquired_to_job(acquired, directory, Path(job_directory) / 'source',
                                            staging_budget_bytes=limits['staging_bytes'])
        return acquired
    except Exception as error:
        # Failed bytes count toward the caller's scene-wide actual download
        # accounting; a failed request is never reclassified as zero cost.
        error.actual_download_bytes = max(transaction.actual_download_bytes,
                                          getattr(error, 'actual_download_bytes', 0))
        error.transfer_ledger = transaction.ledger
        raise
