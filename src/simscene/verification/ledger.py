"""Conservative material ledger: successful placement requires physical evidence."""
from collections import Counter

TERMINAL = {'correct', 'wrong_bin', 'failed'}

def evaluate(objects, expected_bins, stability_s):
    """Evaluate one final observation per generated object.

    Observations need a unique id, class, and terminal state. A success claim
    must include observed grasp, release, destination containment and stable
    duration. Unknown/incomplete observations remain pending or fail, never
    become successes by reaching a controller state.
    """
    if stability_s <= 0:
        raise ValueError('stability_s must be positive')
    seen = set()
    counts = Counter()
    results = []
    for item in objects:
        object_id = item['id']
        if object_id in seen: raise ValueError(f'duplicate object id: {object_id}')
        seen.add(object_id)
        cls = item['class']
        if cls not in expected_bins: raise ValueError(f'unknown class: {cls}')
        state = item.get('state', 'pending')
        if state not in TERMINAL | {'pending'}: raise ValueError(f'unknown state: {state}')
        reason = None
        if state in ('correct', 'wrong_bin'):
            bin_id = item.get('contained_in')
            if not bin_id or not item.get('released') or item.get('stable_s', 0) < stability_s:
                state, reason = 'failed', 'placement lacks release, containment or stability evidence'
            elif bin_id != expected_bins[cls]:
                state, reason = 'wrong_bin', 'object is contained in the wrong bin'
            elif not item.get('grasp_observed'):
                state, reason = 'failed', 'grasp not observed'
            else:
                state = 'correct'
        counts[state] += 1
        results.append({'id':object_id, 'class':cls, 'state':state, 'reason':reason})
    return {'generated':len(objects), 'correct':counts['correct'], 'wrong_bin':counts['wrong_bin'], 'failed':counts['failed'], 'pending':counts['pending'], 'success_rate':counts['correct']/len(objects) if objects else None, 'objects':results}
