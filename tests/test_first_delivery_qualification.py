"""Regression checks for admission and terminal accounting of hosted turns."""
import importlib.util
from pathlib import Path

import pytest


def host(monkeypatch):
    file = Path(__file__).resolve().parents[1]/'experiments/qualify_first_delivery.py'
    monkeypatch.syspath_prepend(str(file.parent))
    spec = importlib.util.spec_from_file_location('first_delivery_qualification', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discovery_cannot_consume_the_allowance_reserved_for_review(monkeypatch):
    h = host(monkeypatch)
    limit = h.Budget(total=150, per_turn=60)
    with pytest.raises(ValueError, match='allowance'):
        limit.admit('discover', later_turns=2)
    limit.admit('discover', later_turns=1)
    limit.settle('discover', {'input_tokens': 37, 'cached_input_tokens': 30, 'output_tokens': 3})
    limit.admit('review', later_turns=0)
    limit.settle('review', {'input_tokens': 41, 'cached_input_tokens': 0, 'output_tokens': 2})
    assert limit.spent == 83


def test_missing_or_excess_usage_cannot_borrow_the_next_turn_allowance(monkeypatch):
    h = host(monkeypatch)
    limit = h.Budget(total=100, per_turn=50)
    limit.admit('discover', later_turns=1)
    with pytest.raises(ValueError, match='usage'):
        limit.settle('discover', None)
    with pytest.raises(ValueError, match='allowance'):
        limit.settle('discover', {'input_tokens': 51, 'output_tokens': 1})
    assert limit.spent == 52


def test_review_rejects_a_changed_case_even_when_video_hashes_match(tmp_path):
    from simscene.recipes.first_delivery import record_review, WorkflowError
    from simscene.recipes.cabinet_mcp_workflow import _sha, _write

    files = {'scene': tmp_path/'scene.json', 'case': tmp_path/'case.json',
             'video': tmp_path/'first-delivery.mp4', 'edit_map': tmp_path/'first-delivery.edit.json',
             'check': tmp_path/'physical-check.json'}
    for path in files.values():
        path.write_text('{"passed":true}')
    _write(tmp_path/'delivery.json', {
        'schema': 'simscene.first_delivery.v1', 'status': 'needs_visual_review',
        'physical_status': 'passed', 'media_status': 'passed',
        **{k: str(p) for k, p in files.items()}, **{k+'_sha256': _sha(p) for k, p in files.items()},
    })
    review = tmp_path/'review.json'
    _write(review, {'decision': 'accept', 'reviewer': 'Test reviewer', 'video_sha256': _sha(files['video']),
                    'reviewed_windows': [{'start_s': 0, 'end_s': 4, 'observation': 'Clear fall and settled box.'}]})
    files['case'].write_text('{"passed":false}')
    with pytest.raises(WorkflowError, match='artifacts differ'):
        record_review(tmp_path, review)
    assert not (tmp_path/'reviewed-delivery.json').exists()
    files['case'].write_text('{"passed":true}')
    assert record_review(tmp_path, review)['status'] == 'ready_for_submission'
