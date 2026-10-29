"""Check one preregistered route edit against real saved simulation evidence."""
import hashlib
import json
import math
from pathlib import Path
import sys
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs
from simscene.verification.case_runner import evaluate

if len(sys.argv) != 2:
    raise SystemExit('usage: verify_agent_route_edit.py EVALUATION_DIRECTORY')
root = Path(sys.argv[1]).resolve()
case_path = root / 'pre_registered_case.json'
case = json.loads(case_path.read_text())
config = json.loads((root / 'evaluation-config.json').read_text())
mode = config['mode']
if case.get('schema') != 'simscene.agent_route_edit_case.v1' or mode not in ('swap', 'relocate'):
    raise SystemExit('unsupported case or edit')
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
before = json.loads((root / 'before.json').read_text())
after = json.loads((root / 'after.json').read_text())
old, new = before['objects'], after['objects']
checks = {'case_copy_hash_matches': (root / 'pre_registered_case.sha256').read_text().strip() == digest(case_path),
          'agent_session_completed': (root / 'exit-code.txt').read_text().strip() == '0',
          'no_external_intervention': not (root / 'external-intervention.json').exists() and not (root / 'external-interventions.jsonl').exists(),
          'same_scene_and_new_revision': before['scene_id'] == after['scene_id'] and after['revision'] > before['revision']}
try:
    frozen = (root / 'frozen-checker.sha256').read_text().strip()
    checks['checker_matches_frozen_copy'] = frozen == digest(root / 'frozen-checker.py') == digest(Path(__file__).resolve())
except OSError:
    checks['checker_matches_frozen_copy'] = False
aliases = {'red':'red', '红':'red', '红色':'red', 'green':'green', '绿':'green', '绿色':'green', 'blue':'blue', '蓝':'blue', '蓝色':'blue'}
def canonical(label):
    return aliases.get(label.strip().lower(), label) if isinstance(label, str) else label

def owners(objects):
    out = {}
    for robot, obj in objects.items():
        for phase in obj.get('pose_follower', {}).get('sequence', []):
            if phase.get('type') != 'wait_object':
                continue
            part = objects.get(phase.get('object'), {})
            label = canonical(part.get('class_label'))
            if label:
                out.setdefault(label, set()).add(robot)
    return out
old_owners, new_owners = owners(old), owners(new)
classes = case['swap_classes']
checks['before_classes_have_distinct_owners'] = len(classes) == 2 and all(len(old_owners.get(c, set())) == 1 for c in classes) and old_owners[classes[0]] != old_owners[classes[1]]
if mode == 'swap':
    checks['requested_owners_swapped'] = bool(checks['before_classes_have_distinct_owners'] and new_owners.get(classes[0]) == old_owners[classes[1]] and new_owners.get(classes[1]) == old_owners[classes[0]])
    checks['other_class_owners_preserved'] = all(new_owners.get(c) == value for c, value in old_owners.items() if c not in classes)
else:
    checks['class_owners_preserved'] = old_owners == new_owners
runs = []
for directory in (root / 'state' / 'runs').glob('*'):
    try:
        spec = json.loads((directory / 'spec.json').read_text())
        result = json.loads((directory / 'result.json').read_text())
        if spec['scene_id'] == after['scene_id'] and spec['revision'] == after['revision'] and result.get('actual_physics_steps') == result.get('requested_physics_steps') and result.get('actual_physics_steps', 0) > 0:
            runs.append((directory, spec, result))
    except (OSError, ValueError, KeyError, TypeError):
        continue
checks['completed_run_of_edited_revision'] = bool(runs)
directory = None
measurements = {}
if runs:
    directory, spec, result = max(runs, key=lambda row: row[0].stat().st_mtime)
    try:
        job_id = json.loads((directory/'job.json').read_text()).get('job_id')
        calls = [event.get('item', {}) for event in (json.loads(line) for line in (root/'trace.jsonl').read_text().splitlines())
                 if event.get('type') == 'item.completed' and event.get('item', {}).get('type') == 'mcp_tool_call'
                 and event.get('item', {}).get('status') == 'completed' and event.get('item', {}).get('arguments', {}).get('job_id') == job_id]
        checks['agent_observed_edited_run'] = any(call.get('tool') in ('run_observe','scene_observe') for call in calls)
        def completed_call(call):
            if call.get('tool') == 'run_verify': return True
            if call.get('tool') != 'job_status': return False
            try: return json.loads(call['result']['content'][0]['text']).get('state') == 'completed'
            except (KeyError, IndexError, TypeError, ValueError): return False
        checks['agent_saw_completed_run'] = any(completed_call(call) for call in calls)
        checks['input_integrity'] = verify_inputs(directory)['passed']
        sealed = verify_outputs(directory)
        checks['output_integrity'] = sealed['passed'] and not sealed['partial']
        lock = json.loads((directory / 'run-lock.json').read_text())
        package = json.loads((root / 'package-hashes.json').read_text())
        prefix = 'server/vendor/simscene/'
        worker = {name[len(prefix):]: value for name, value in package.items() if name.startswith(prefix)}
        checks['worker_matches_frozen_package'] = bool(worker) and worker == lock.get('worker_code_sha256')
        prefix = 'skills/'
        expected = {name[len(prefix):]: value for name, value in package.items() if name.startswith(prefix)}
        skill_root = root / 'work' / '.agents' / 'skills'
        actual = {str(p.relative_to(skill_root)): digest(p) for p in skill_root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        checks['skill_matches_frozen_package'] = bool(expected) and expected == actual
        report = evaluate(directory)
        checks['pinned_physical_case_passed'] = bool(report['case_pinned_to_run'] and report['passed'])
        checks['no_wrong_bin'] = report['ledger']['wrong_bin'] == 0
        physical_case = json.loads((directory / lock['acceptance_case_file']).read_text())
        case_owners = {}
        for entry in physical_case['objects']:
            case_owners.setdefault(canonical(entry.get('class_label')), set()).add(entry.get('robot_id'))
        checks['physical_case_owners_match_edited_scene'] = all(case_owners.get(label) == robots for label, robots in new_owners.items())
        correct = {}
        for item in report['ledger']['objects']:
            if item.get('state') == 'correct':
                label = canonical(item.get('class_label'))
                correct[label] = correct.get(label, 0) + 1
        needed = classes if mode == 'swap' else [classes[0]]
        checks['changed_classes_physically_placed'] = all(correct.get(c, 0) >= case['minimum_correct_per_changed_class'] for c in needed)
        checks['camera_observation_saved'] = bool(result.get('images'))
        # Validate the archived bounds against actual USD collision boxes,
        # independently of destination bounds proposed by the agent.
        from pxr import Usd, UsdGeom
        stage = Usd.Stage.Open(str(directory / 'scene.usda'))
        bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render], useExtentsHint=True)
        boxes = {}
        for name, obj in spec['objects'].items():
            if obj.get('kind') != 'box' or not obj.get('collision') or obj.get('dynamic') or obj.get('conveyor'):
                continue
            prim = stage.GetPrimAtPath('/World/' + name.replace('-', '_'))
            if prim:
                bounds = bbox.ComputeWorldBound(prim).ComputeAlignedRange()
                boxes[name] = ([float(x) for x in bounds.GetMin()], [float(x) for x in bounds.GetMax()])
        def enclosed(bounds):
            lo, hi = bounds['min'], bounds['max']
            for name, (a, b) in boxes.items():
                if not (a[0]-.003 <= lo[0] and hi[0] <= b[0]+.003 and a[1]-.003 <= lo[1] and hi[1] <= b[1]+.003 and abs(lo[2]-b[2]) <= .02):
                    continue
                walls = set()
                for other, (c, d) in boxes.items():
                    if other == name or d[2] < hi[2] or c[2] > lo[2]+.06:
                        continue
                    if c[1] <= lo[1] and d[1] >= hi[1]:
                        if abs((c[0]+d[0])/2-a[0]) <= .04: walls.add('left')
                        if abs((c[0]+d[0])/2-b[0]) <= .04: walls.add('right')
                    if c[0] <= lo[0] and d[0] >= hi[0]:
                        if abs((c[1]+d[1])/2-a[1]) <= .04: walls.add('front')
                        if abs((c[1]+d[1])/2-b[1]) <= .04: walls.add('back')
                if len(walls) == 4:
                    return name
            return None
        bins = {}
        archived = result.get('archived_objects', {})
        for label in needed:
            found = {enclosed(archived[item['id']]['bounds']) for item in report['ledger']['objects']
                     if canonical(item.get('class_label')) == label and item.get('state') == 'correct'
                     and item['id'] in archived and 'bounds' in archived[item['id']]}
            if len(found) == 1 and None not in found:
                bins[label] = next(iter(found))
        checks['changed_classes_in_real_enclosed_bins'] = len(bins) == len(needed) and len(set(bins.values())) == len(needed)
        measurements['correct_by_class'] = correct
        if mode == 'relocate':
            # Compare the original and edited destination for the same robot and
            # part. The bin must cross the axis of its original horizontal
            # displacement from the base, and the modelled floor must move.
            robot = next(iter(old_owners.get(classes[0], set())), None)
            old_seq = old.get(robot, {}).get('pose_follower', {}).get('sequence', [])
            new_seq = new.get(robot, {}).get('pose_follower', {}).get('sequence', [])
            def release_target(seq):
                for i, phase in enumerate(seq):
                    if phase.get('type') == 'gripper' and i and isinstance(seq[i-1].get('position'), list):
                        return seq[i-1]['position']
                return None
            a, b = release_target(old_seq), release_target(new_seq)
            base = old.get(robot, {}).get('position', [0, 0, 0])
            moved = bool(a and b and math.dist(a, b) >= case['minimum_bin_move_m'])
            axis = max(range(2), key=lambda i: abs(a[i]-base[i])) if a else None
            checks['bin_moved_to_other_side_of_arm'] = bool(moved and (a[axis]-base[axis])*(b[axis]-base[axis]) < 0)
            candidates = [name for name, obj in old.items() if obj.get('kind') == 'box' and obj.get('collision') and not obj.get('dynamic') and obj.get('position') and obj.get('size') and a and abs(obj['position'][0]-a[0]) <= obj['size'][0]/2 and abs(obj['position'][1]-a[1]) <= obj['size'][1]/2 and obj['position'][2] < a[2] and obj['size'][2] <= .1]
            floor_moved = []
            for name in candidates:
                x, y = old[name]['position'], new.get(name, {}).get('position')
                if y and math.dist(x, y) >= case['minimum_bin_move_m'] and b and abs(y[0]-b[0]) <= old[name]['size'][0]/2 and abs(y[1]-b[1]) <= old[name]['size'][1]/2:
                    floor_moved.append(name)
            checks['physical_bin_floor_moved_with_destination'] = bool(floor_moved)
            checks['placed_in_moved_bin'] = bins.get(classes[0]) in floor_moved
            from simscene.verification.acceptance import COLLISION_POLICY
            suffixes = {'kawasaki':'/Kawasaki/RS007L/rs007l_onrobot_rg2.usd', 'franka':'/FrankaRobotics/FrankaPanda/franka.usd', 'ur10':'/UniversalRobots/ur10/ur10.usd'}
            assets = json.loads((directory/'asset-lock.json').read_text())
            def matches_reviewed_asset(name, obj, suffix):
                """Bind the reviewed source identity to the actual run snapshot."""
                entry = assets.get(name, {})
                path = obj.get('asset_path')
                if not isinstance(path, str): return False
                if entry.get('kind') != 'snapshot':
                    return path.lower().endswith(suffix.lower())
                from urllib.parse import urlsplit
                source = entry.get('source', '')
                if not isinstance(source, str): return False
                parsed = urlsplit(source)
                relative = entry.get('root_relative_to_run')
                if (parsed.scheme != 'https' or parsed.hostname != 'omniverse-content-production.s3-us-west-2.amazonaws.com'
                        or parsed.query or parsed.fragment or not parsed.path.lower().endswith(suffix.lower())
                        or not isinstance(relative, str)):
                    return False
                root = (directory/relative).resolve()
                return ((directory/'assets').resolve() in root.parents and root == Path(path).resolve()
                        and checks.get('input_integrity') is True)
            robot_names = {kind: next((name for name, obj in spec['objects'].items()
                                     if matches_reviewed_asset(name, obj, suffix)), None)
                           for kind, suffix in suffixes.items()}
            reviewed = {section: {robot_names[kind]: value for kind, value in mapping.items()}
                        for section, mapping in COLLISION_POLICY.items()}
            checks['collision_exceptions_match_reviewed_models'] = bool(all(robot_names.values()) and physical_case.get('collision_policy') == reviewed)
            checks['full_sampled_path_collision_audit'] = bool(report.get('collision_audit', {}).get('passed'))
            measurements.update(old_release_target=a, new_release_target=b, moved_floors=floor_moved, crossing_axis=axis)
    except (OSError, ValueError, KeyError, TypeError, IndexError, RuntimeError, ImportError, AttributeError):
        checks['recorded_run_verifiable'] = False
else:
    checks['recorded_run_verifiable'] = False
report = {'passed': all(checks.values()), 'checks': checks, 'run_directory': str(directory) if directory else None,
          'measurements': measurements, 'scope': case['scope']}
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report['passed'] else 1)
