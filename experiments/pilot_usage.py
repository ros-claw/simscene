"""Reconcile Codex JSONL usage without double-counting cache or reasoning.

Missing usage stays unknown. This reader does not infer historical tokens from
elapsed time, monthly allowances, prose length or tool-output bytes.
"""
import argparse
import json
from pathlib import Path

FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
          'output_tokens', 'reasoning_output_tokens')


def rows(path):
    good, bad = [], []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            good.append((number, json.loads(line)))
        except ValueError:
            bad.append(number)
    return good, bad


def normalize(value):
    if not isinstance(value, dict) or any(type(value.get(k)) is not int or value[k] < 0
                                         for k in ('input_tokens', 'output_tokens')):
        raise ValueError('actual nonnegative input/output usage required')
    result = {k: value.get(k) for k in FIELDS}
    for key in FIELDS[1:]:
        if result[key] is not None and (type(result[key]) is not int or result[key] < 0):
            raise ValueError('invalid reported token category')
    cached = result['cached_input_tokens']
    if cached is not None and cached > result['input_tokens']:
        raise ValueError('cached input is a subset, not an additional token bucket')
    result['total_tokens'] = result['input_tokens']+result['output_tokens']
    result['uncached_input_tokens'] = result['input_tokens']-cached if cached is not None else None
    return result


def collect(events_path, session_path=None):
    events, invalid = rows(events_path)
    aggregate, thread_ids = [], []
    for _, row in events:
        if row.get('type') == 'thread.started':
            thread_ids.append(row['thread_id'])
        if row.get('type') == 'turn.completed' and row.get('usage') is not None:
            aggregate.append(normalize(row['usage']))
    total = None
    if aggregate:
        total = {k: sum(v[k] for v in aggregate) if all(v[k] is not None for v in aggregate) else None
                 for k in (*FIELDS, 'total_tokens', 'uncached_input_tokens')}
    requests, seen, previous, epoch = [], set(), None, 0
    invalid_session, contexts = [], []
    if session_path is not None:
        session, invalid_session = rows(session_path)
        for number, row in session:
            payload = row.get('payload', {})
            if row.get('type') == 'turn_context':
                contexts.append({k: payload.get(k) for k in ('model', 'effort', 'reasoning_effort')})
            if row.get('type') != 'event_msg' or payload.get('type') != 'token_count':
                continue
            info = payload.get('info') or {}
            cumulative, last = info.get('total_token_usage'), info.get('last_token_usage')
            if cumulative is None or last is None:
                continue
            current, usage = normalize(cumulative), normalize(last)
            if previous and (current['input_tokens'] < previous['input_tokens'] or current['output_tokens'] < previous['output_tokens']):
                epoch += 1; previous = None
            key = (epoch, current['input_tokens'], current['cached_input_tokens'], current['output_tokens'])
            if key in seen:
                continue
            seen.add(key)
            delta = {k: current[k]-(previous[k] if previous else 0)
                     for k in ('input_tokens', 'output_tokens', 'total_tokens')}
            requests.append({'source_line': number, 'timestamp': row.get('timestamp'),
                             'request_id': payload.get('request_id'), 'counter_epoch': epoch,
                             'raw_usage': last, 'normalized': usage,
                             'counter_delta_matches_last': all(delta[k] == usage[k] for k in delta),
                             'last_usage_includes_reasoning': info.get('last_usage_includes_reasoning')})
            previous = current
    request_total = None
    if requests:
        request_total = {k: sum(r['normalized'][k] for r in requests)
                         if all(r['normalized'][k] is not None for r in requests) else None
                         for k in (*FIELDS, 'total_tokens', 'uncached_input_tokens')}
    reconciled = total is not None and request_total is not None and total == request_total
    return {'schema': 'simscene.codex_pilot_usage.v1', 'thread_ids': thread_ids,
            'aggregate_reported_usage': total, 'request_event_sum': request_total,
            'request_events': requests, 'cli_and_request_counters_reconcile': reconciled,
            'usage_availability': ('request_events_and_reconciled_totals' if reconciled else
                                   'aggregate_only' if total is not None and not requests else
                                   'partial_or_unreconciled' if requests or total else 'unknown'),
            'model_contexts': contexts, 'invalid_event_lines': invalid,
            'invalid_session_lines': invalid_session,
            'billing_amount': None, 'billing_scope': 'No invoice or pricing estimate obtained.',
            'coverage_scope': 'Only provider usage reported by these exact CLI/session logs. Absent request IDs and hidden retries remain unknown; local source-line identities are not server request IDs.',
            'normalization': 'Total=input+output. Cache is an input subset; reasoning is already in reported output, never added again.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('events'); p.add_argument('--session'); p.add_argument('--output', required=True)
    a = p.parse_args(); value = collect(a.events, a.session)
    with Path(a.output).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')
    print(json.dumps({k: value[k] for k in ('aggregate_reported_usage','request_event_sum','usage_availability')}, ensure_ascii=False))
