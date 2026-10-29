"""Reject a collision case that cannot produce a complete discrete audit.

This validates configuration consistency, not geometry, asset identity or
actual safety. The independent post-run audit still decides whether it passed.
"""
def validate(scene, case):
    policy = case.get('collision_policy')
    if policy is None:
        return
    if not isinstance(policy, dict) or set(policy) != {'mechanical_pairs', 'grasp_bodies', 'allowed_mechanical_contacts'}:
        raise ValueError('collision_policy requires mechanical_pairs, grasp_bodies and allowed_mechanical_contacts')
    if not isinstance(case.get('expected_spawn_order'), list):
        raise ValueError('collision_policy requires a stream case with expected_spawn_order')
    items = case.get('objects')
    if not isinstance(items, list) or not items or not all(isinstance(x, dict) and isinstance(x.get('robot_id'), str) and x['robot_id'] for x in items):
        raise ValueError('collision_policy requires stream case objects with robot_id')
    robots = {x['robot_id'] for x in items}
    for section in policy:
        if not isinstance(policy[section], dict) or set(policy[section]) != robots:
            raise ValueError(f'collision_policy {section} must cover exactly all case robots: {sorted(robots)}')
    def body(value):
        return isinstance(value, str) and bool(value) and '/' not in value and value not in ('.', '..')
    def pairs(value):
        return isinstance(value, list) and all(isinstance(x, list) and len(x) == 2 and all(body(y) for y in x) and x[0] != x[1] for x in value)
    objects = scene.get('objects', {})
    for robot in robots:
        follower = objects.get(robot, {}).get('pose_follower')
        if not isinstance(follower, dict) or any(follower.get(key) is not True for key in ('monitor_collisions', 'self_collision_enabled', 'diagnose_overlaps')):
            raise ValueError(f'collision audit requires monitor_collisions, self_collision_enabled and diagnose_overlaps on {robot}')
        mechanical = policy['mechanical_pairs'][robot]
        allowed = policy['allowed_mechanical_contacts'][robot]
        grasp = policy['grasp_bodies'][robot]
        if not pairs(mechanical) or not pairs(allowed) or not isinstance(grasp, list) or not grasp or not all(body(x) for x in grasp):
            raise ValueError(f'collision policy has invalid body names or pairs for {robot}')
        configured = follower.get('self_collision_exclusions', [])
        if not pairs(configured) or {tuple(sorted(x)) for x in configured} != {tuple(sorted(x)) for x in mechanical}:
            raise ValueError(f'collision policy mechanical_pairs do not match {robot} self_collision_exclusions')
