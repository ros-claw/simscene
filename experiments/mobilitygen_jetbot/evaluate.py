"""Independent checks of the recorded fixed-route experiment, with fail-closed fields."""
import json
import math
import sys


def evaluate_horizon(samples, mode):
    result = evaluate(samples, mode)
    errors = list(result.get('errors', []))
    if errors:
        return result
    if len(samples) != 601:
        errors.append('fixed 600-step horizon is incomplete')
    for item in samples:
        readback = item.get('native_wheel_targets_rad_s') if isinstance(item, dict) else None
        command = item.get('wheel_targets_rad_s') if isinstance(item, dict) else None
        if not isinstance(readback, list) or len(readback) != 2 or not isinstance(command, list) or len(command) != 2 or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                for value in readback):
            errors.append('native target readback is malformed')
            break
        if any(abs(a - b) > 1e-5 for a, b in zip(readback, command)):
            errors.append('native target readback differs from command')
            break
    if mode == 'positive':
        first_arrival = next((i for i, item in enumerate(samples) if item.get('arrived') is True), None)
        if first_arrival is None or any(abs(v) > 1e-9 for item in samples[first_arrival + 1:]
                                        for v in item['wheel_targets_rad_s']):
            errors.append('terminal state did not hold zero targets')
        result['first_arrival_step'] = first_arrival
    result.update(passed=not errors, errors=errors)
    return result


def validate_drive_snapshot(snapshot):
    errors = []
    if not isinstance(snapshot, dict) or snapshot.get('drive_type_codes') != [1, 1]:
        errors.append('native wheel drive types must both be force')
    for key in ('max_effort_nm', 'stiffness', 'damping'):
        value = snapshot.get(key) if isinstance(snapshot, dict) else None
        if not isinstance(value, list) or len(value) != 2 or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
            errors.append(f'native {key} missing, nonfinite or wrong shape')
            continue
        if key == 'max_effort_nm' and any(abs(x - 1.) > 1e-6 for x in value):
            errors.append('native drive efforts differ from fixed 1 N m bound')
        if key == 'stiffness' and any(abs(x) > 1e-6 for x in value):
            errors.append('velocity drives must have zero stiffness')
        if key == 'damping' and any(abs(x - 1.) > 1e-5 for x in value):
            errors.append('native wheel damping differs from frozen 1.0 gain')
    return errors


def evaluate(samples, mode):
    errors = []
    if mode not in ("positive", "zero") or not isinstance(samples, list) or len(samples) < 2:
        return {"passed": False, "errors": ["invalid mode or insufficient samples"]}
    vectors = {"base_position_m": 3, "base_orientation_wxyz": 4,
               "base_com_linear_velocity_m_s": 3, "base_angular_velocity_rad_s": 3,
               "wheel_positions_rad": 2, "wheel_targets_rad_s": 2, "wheel_velocities_rad_s": 2}
    flags = ("arrived", "obstacle_collision", "map_out_of_bounds", "map_collision", "ground_contact")
    initial_callback = samples[0].get('physics_callback_count') if isinstance(samples[0], dict) else None
    if type(initial_callback) is not int:
        errors.append('missing initial physics callback count')
    for index, item in enumerate(samples):
        if not isinstance(item, dict) or item.get("step") != index:
            errors.append(f"nonconsecutive or malformed sample {index}")
            continue
        if type(initial_callback) is not int or item.get('physics_callback_count') != initial_callback + index:
            errors.append(f"physics callback discontinuity at {index}")
        time_s = item.get('time_s')
        if (isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or not math.isfinite(time_s)
                or abs(time_s - index / 60) > 1e-8):
            errors.append(f'invalid physical time at {index}')
        for key, size in vectors.items():
            value = item.get(key)
            if not isinstance(value, list) or len(value) != size or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value
            ):
                errors.append(f"invalid {key} at {index}")
        for key in flags:
            if type(item.get(key)) is not bool:
                errors.append(f"missing or invalid {key} at {index}")
        distance = item.get("goal_distance_m")
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance):
            errors.append(f"invalid goal distance at {index}")
        pairs = item.get('contact_actor_pairs')
        if (not isinstance(pairs, list) or any(not isinstance(pair, list) or len(pair) != 2 or
                any(not isinstance(path, str) or not path.startswith('/World/') for path in pair) for pair in pairs)):
            errors.append(f'invalid contact actor pairs at {index}')
            continue
        ground = False
        obstacle = False
        for pair in pairs:
            robot = [path for path in pair if path == '/World/Jetbot' or path.startswith('/World/Jetbot/')]
            if not robot:
                errors.append(f'contact pair lacks robot actor at {index}')
                continue
            for path in pair:
                if path in robot:
                    continue
                if path == '/World/Ground' or path.startswith('/World/Ground/'):
                    ground = True
                elif any(path == '/World/Wall' + side or path.startswith('/World/Wall' + side + '/')
                         for side in ('East', 'West', 'North', 'South')):
                    obstacle = True
                else:
                    errors.append(f'unexpected non-robot contact actor at {index}')
        if item.get('ground_contact') is not ground or item.get('obstacle_collision') is not obstacle:
            errors.append(f'contact flags disagree with raw actors at {index}')
    if errors:
        return {"passed": False, "errors": errors}
    for item in samples:
        pos = item["base_position_m"]
        measured_distance = math.hypot(0.8 - pos[0], pos[1])
        if abs(measured_distance - item["goal_distance_m"]) > 1e-5:
            errors.append("goal distance does not agree with measured position")
            break
        if item['arrived'] is not (measured_distance <= .08):
            errors.append('arrival flag disagrees with measured position')
            break
        if abs(math.sqrt(sum(x * x for x in item['base_orientation_wxyz'])) - 1.) > 1e-4:
            errors.append('chassis quaternion is not normalized')
            break
    if any(x["obstacle_collision"] or x["map_out_of_bounds"] or x["map_collision"] for x in samples):
        errors.append("obstacle collision or out of map")
    task_contacts = samples[1:]
    if not task_contacts or any(not any(row['ground_contact'] for row in task_contacts[start:start + 60])
                                for start in range(max(1, len(task_contacts) - 59))):
        errors.append('task has a one-second window without ground contact')
    for side in ('left', 'right'):
        wheel = '/World/Jetbot/' + side + '_wheel'
        def wheel_touches_ground(row):
            return any(any(p == wheel or p.startswith(wheel + '/') for p in pair) and
                       any(p == '/World/Ground' or p.startswith('/World/Ground/') for p in pair)
                       for pair in row['contact_actor_pairs'])
        if not task_contacts or any(not any(wheel_touches_ground(row) for row in task_contacts[start:start + 60])
                                    for start in range(max(1, len(task_contacts) - 59))):
            errors.append(side + ' wheel has a task window without ground contact')
    if any(abs(row['base_position_m'][0]) >= 1.9 or abs(row['base_position_m'][1]) >= 1.9
           for row in samples):
        errors.append('native chassis origin is outside the frozen inner wall boundary')
    start, end = samples[0]["base_position_m"], samples[-1]["base_position_m"]
    displacement = math.hypot(end[0] - start[0], end[1] - start[1])
    peak_displacement = max(math.hypot(x['base_position_m'][0] - start[0],
                                       x['base_position_m'][1] - start[1]) for x in samples)
    max_step_displacement = max(math.dist(a['base_position_m'], b['base_position_m'])
                                for a, b in zip(samples, samples[1:]))
    if max_step_displacement > 1.0 / 60.0:
        errors.append('position jumps exceed 1 m/s at the fixed 1/60 s step')
    if any(abs(q) > 8.0 + 1e-5 for sample in samples for q in sample['wheel_targets_rad_s']):
        errors.append('wheel target exceeds the frozen limit')
    commanded_progress = None
    sampled_wheel_changes = None
    if mode == "positive":
        if not samples[-1]["arrived"] or samples[-1]["goal_distance_m"] > 0.08 or displacement < 0.3:
            errors.append("positive run did not physically reach the goal")
        first_arrival = next((index for index, item in enumerate(samples) if item['arrived']), len(samples))
        driven_steps = sum(any(abs(q) > .01 for q in sample['wheel_targets_rad_s'])
                           for sample in samples[1:first_arrival + 1])
        if any(abs(q) > 1e-9 for q in samples[0]['wheel_targets_rad_s']) or driven_steps < 10:
            errors.append('positive run lacks ten nonzero task drive steps before arrival')
        commanded_progress = sum(samples[i]['base_position_m'][0] - samples[i - 1]['base_position_m'][0]
                                 for i in range(1, min(first_arrival + 1, len(samples)))
                                 if any(abs(q) > .01 for q in samples[i]['wheel_targets_rad_s']))
        if commanded_progress < .3:
            errors.append('less than 0.3 m forward progress was observed during nonzero targets')
        sampled_wheel_changes = [sum(abs(math.atan2(math.sin(samples[i]['wheel_positions_rad'][wheel] -
                                                                  samples[i - 1]['wheel_positions_rad'][wheel]),
                                                        math.cos(samples[i]['wheel_positions_rad'][wheel] -
                                                                 samples[i - 1]['wheel_positions_rad'][wheel])))
                                     for i in range(1, min(first_arrival + 1, len(samples))))
                                 for wheel in (0, 1)]
        if any(change < .1 for change in sampled_wheel_changes):
            errors.append('positive run lacks sampled position changes on both wheels')
    else:
        if any(abs(q) > 1e-9 for sample in samples for q in sample["wheel_targets_rad_s"]):
            errors.append("zero control issued a nonzero wheel target")
        if peak_displacement > 0.04 or any(sample["arrived"] for sample in samples):
            errors.append("zero control moved or reached the goal")
    return {"passed": not errors, "errors": errors, "samples": len(samples),
            "displacement_m": displacement, "peak_displacement_m": peak_displacement,
            "max_step_displacement_m": max_step_displacement,
            "final_goal_distance_m": samples[-1]["goal_distance_m"],
            "forward_progress_during_nonzero_targets_m": commanded_progress,
            "sampled_wheel_short_angle_changes_rad": sampled_wheel_changes}


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf8") as stream:
        rows = [json.loads(line) for line in stream]
    result = evaluate_horizon(rows, sys.argv[2])
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
