"""Plot original accepted per-step masks; never generate or relax those masks.

Use the complete individual report, its frozen network case and run lock.
The figure is a presentation artifact, not an independent physical checker.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def intervals(flags, predicate, start, dt):
    result, first = [], None
    for row in flags:
        left = row['physics_step']-1
        if predicate(row):
            if first is None:
                first = left
        elif first is not None:
            result.append(((first-start)*dt, (left-first)*dt));first = None
    if first is not None:
        result.append(((first-start)*dt, (flags[-1]['physics_step']-first)*dt))
    return result


def bounded_prefix(flags, metrics, report_path, lock_path, dt, certificate_path):
    """Select an independently certified prefix without changing any source row."""
    certificate = json.loads(Path(certificate_path).read_text())
    require(certificate.get('schema') in ('simscene.bounded_entry_clock.v1', 'simscene.bounded_entry_clock.v2', 'simscene.bounded_entry_clock.v3', 'simscene.bounded_entry_clock.v4', 'simscene.bounded_entry_clock.v5', 'simscene.bounded_entry_clock.v6') and
            all(certificate.get(k) is True for k in ('file_integrity_verified', 'supplemental_complete',
                'physical_entry_no_escape_complete', 'bounded_timing_floors_passed', 'inner_no_escape')),
            'use a complete file-verified collapsed entry certificate')
    provenance = certificate['provenance']
    require(provenance['independently_retained_full_report_sha256'] == sha(report_path) and
            provenance['original_files_sha256']['run-lock.json'] == sha(lock_path),
            'entry certificate belongs to another original report/run lock')
    start, original_end = metrics['window_start_step'], metrics['window_end_step']
    timing = certificate['every_possible_original_prefix']
    canonical = json.dumps(flags, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    require(timing['original_full_masks_sha256'] == hashlib.sha256(canonical).hexdigest() and
            timing['original_full_window'] == [start, original_end] and timing.get('source_flags_unchanged') is True,
            'entry certificate differs from the complete original masks/window')
    bounds = certificate['actual_first_entry_observed_step_bounds_inclusive']
    require(isinstance(bounds, list) and len(bounds) == 2 and type(bounds[0]) is int and
            bounds[0] == bounds[1] and start < bounds[0] <= original_end,
            'plot requires one collapsed covered entry boundary')
    end = bounds[0]
    prefixes = timing['prefixes']
    require(len(prefixes) == 1 and prefixes[0]['end_boundary_step'] == end and
            prefixes[0]['interval_start_inclusive'] == start and prefixes[0]['interval_end_exclusive'] == end and
            prefixes[0]['passed'] is True and all(v is True for v in prefixes[0]['checks'].values()),
            'inconsistent certified prefix')
    selected = [row for row in flags if row['physics_step'] <= end]
    require([row['physics_step'] for row in selected] == list(range(start+1, end+1)),
            'missing original physical intervals in the certified prefix')
    active = sum(row['active'] for row in selected)
    idle = intervals(selected, lambda row: not row['active'], start, dt)
    measured = {'chain_duration_s': (end-start)*dt, 'net_effective_action_s': active*dt,
                'motion_occupancy': active/len(selected), 'maximum_idle_s': max((width for _, width in idle), default=0.)}
    require(all(math.isclose(value, prefixes[0]['metrics'][key], abs_tol=1e-9, rel_tol=1e-10)
                for key, value in measured.items()), 'plot prefix differs from the certified clock')
    return selected, {**metrics, **measured, 'window_end_step': end}, {
        'path':str(Path(certificate_path).resolve()), 'sha256':sha(certificate_path),
        'original_stock_window_end_step':original_end, 'physical_entry_step':end,
        'scope':'Presentation of a prefix of unchanged accepted source flags; no new physical verdict.'}


def plot(report_path, case_path, lock_path, destination, groups=None, title='Purposeful action in original simulation', font_path=None, entry_certificate_path=None):
    source = json.loads(Path(report_path).read_text())
    stock = source.get('stock', source)
    require(source.get('passed') is True and stock.get('passed') is True, 'use an accepted positive report, not a failed/unknown run')
    require(stock.get('mode') == 'positive', 'positive functional activity report required')
    case = json.loads(Path(case_path).read_text());lock = json.loads(Path(lock_path).read_text())
    require(stock['case_sha256'] == lock['acceptance_case_sha256'] == sha(case_path), 'report/case/run-lock binding differs')
    if source.get('run_lock_sha256'):
        require(source['run_lock_sha256'] == sha(lock_path), 'individual report identifies another run lock')
    dt = lock['physics_dt_s'];require(type(dt) in (int, float) and math.isfinite(dt) and dt > 0, 'invalid actual timestep')
    activity = stock['activity'];metrics = activity['metrics'];flags = activity['per_step_motion_flags']
    start, end = metrics['window_start_step'], metrics['window_end_step']
    require(type(start) is int and type(end) is int and start < end, 'invalid original timing window')
    require([row['physics_step'] for row in flags] == list(range(start+1, end+1)), 'missing/duplicate/unordered original physical intervals')
    certificate_record = None
    if entry_certificate_path is not None:
        flags, metrics, certificate_record = bounded_prefix(flags, metrics, report_path, lock_path, dt, entry_certificate_path)
        start, end = metrics['window_start_step'], metrics['window_end_step']
    stages = {stage['id'] for stage in case['activity']['stages']}
    if groups is None:
        groups = {name: [name] for name in sorted(stages)}
    require(isinstance(groups, dict) and 1 <= len(groups) <= 20, 'provide 1..20 explicit act groups')
    names = [name for values in groups.values() for name in values]
    require(all(isinstance(label, str) and label and isinstance(values, list) and values for label, values in groups.items()), 'invalid group labels/stage lists')
    require(len(names) == len(set(names)) and set(names) == stages, 'act groups must partition all frozen stage IDs exactly once')
    require(all(set(row['stage_ids']) <= stages and type(row['active']) is bool and row['active'] == bool(row['stage_ids']) == bool(row['body_ids']) for row in flags), 'original motion flags are inconsistent')
    union = intervals(flags, lambda row: row['active'], start, dt)
    idle = intervals(flags, lambda row: not row['active'], start, dt)
    calculated = {'chain_duration_s': (end-start)*dt, 'net_effective_action_s': sum(width for _, width in union),
                  'motion_occupancy': sum(row['active'] for row in flags)/len(flags),
                  'maximum_idle_s': max((width for _, width in idle), default=0.)}
    require(all(math.isclose(calculated[key], metrics[key], abs_tol=1e-9, rel_tol=1e-10) for key in calculated), 'plot intervals disagree with the accepted clock')
    rows = [(label, intervals(flags, lambda row, values=set(values): bool(set(row['stage_ids']) & values), start, dt)) for label, values in groups.items()]
    rows.append(('Union (counted once)', union))
    confirmation = stock['terminal']['stable_confirmation_step']
    require(type(confirmation) is int and confirmation >= end, 'missing original stability confirmation')
    span = calculated['chain_duration_s'];last = (confirmation-start)*dt
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname=str(font_path)) if font_path else FontProperties(family='DejaVu Sans')
    fig, ax = plt.subplots(figsize=(12, 2.1+.48*len(rows)))
    palette = ['#226d8f', '#c15e44', '#9b7a20', '#5c7d48', '#72558d']
    for index, (label, pieces) in enumerate(rows):
        ax.broken_barh(pieces, (index-.30, .60), facecolors='#182d3b' if index == len(rows)-1 else palette[index % len(palette)])
    ax.axvline(span, color='#ae4335', linewidth=1.2)
    if last > span:
        ax.axvspan(span, last, color='#e7ebee', zorder=0)
    ax.set_xlim(0, max(last, span)*1.015)
    ax.set_ylim(len(rows)-.25, -.75)
    ax.set_yticks(range(len(rows)), [label for label, _ in rows], fontproperties=font)
    ax.set_xlabel('Seconds since unique release', fontproperties=font)
    ax.set_title(title, loc='left', pad=16, fontproperties=font, fontsize=14)
    ax.grid(axis='x', color='#d7dfe3', alpha=.65);ax.set_axisbelow(True)
    for edge in ('top', 'right', 'left'):
        ax.spines[edge].set_visible(False)
    boundary_label = 'certified physical whole entry' if certificate_record else 'first sustained stock whole entry'
    fig.text(.02, .025, f"Span {span:.3f}s   Useful union {calculated['net_effective_action_s']:.3f}s   Occupancy {calculated['motion_occupancy']:.2%}   Longest idle {calculated['maximum_idle_s']:.3f}s\nRed line: {boundary_label}. Grey: confirmation wait, excluded. Act rows can overlap; never sum their durations.", fontsize=9, fontproperties=font)
    fig.tight_layout(rect=(0,.11,1,1))
    destination = Path(destination).resolve()
    require(not destination.exists(), 'preserve prior plot artifacts; choose a fresh directory')
    destination.mkdir(parents=True)
    paths = [destination/('activity.'+extension) for extension in ('png', 'svg', 'pdf')]
    for path in paths:
        fig.savefig(path, dpi=220, facecolor='white')
    plt.close(fig)
    result = {'schema': 'simscene.activity_plot.v1', 'source_report': str(Path(report_path).resolve()), 'source_report_sha256': sha(report_path),
              'case_sha256': sha(case_path), 'run_lock_sha256': sha(lock_path), 'physics_dt_s': dt,
              'window_start_step_inclusive': start, 'window_end_step_exclusive': end, 'groups': groups,
              'original_clock_metrics': calculated, 'confirmation_wait_s_excluded': last-span,
              'act_union_seconds': {label: sum(width for _, width in pieces) for label, pieces in rows[:-1]},
              'matplotlib_version': matplotlib.__version__, 'font_file': str(font_path) if font_path else None,
              'font_sha256': sha(font_path) if font_path else None, 'artifacts_sha256': {str(path): sha(path) for path in paths},
              'scope': 'Presentation of original accepted physical masks and clock only; no new physical criteria, thresholds, missing-data fill or simulation.'}
    if certificate_record is not None:
        result['bounded_entry_certificate'] = certificate_record
    (destination/'plot.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report');parser.add_argument('case');parser.add_argument('run_lock');parser.add_argument('destination')
    parser.add_argument('--groups');parser.add_argument('--title', default='Purposeful action in original simulation');parser.add_argument('--font')
    parser.add_argument('--entry-certificate', help='Complete independent bounded-entry certificate for the same accepted full report')
    args = parser.parse_args()
    result = plot(args.report, args.case, args.run_lock, args.destination,
                  json.loads(Path(args.groups).read_text()) if args.groups else None, args.title, args.font, args.entry_certificate)
    print(json.dumps({'metrics': result['original_clock_metrics'], 'artifacts': list(result['artifacts_sha256'])}))
