"""Check known pinned motion envelopes against a saved current scene."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True, help='JSON saved from the current scene')
    parser.add_argument('--owner', required=True, help='prepared articulated object ID')
    parser.add_argument('--profile', required=True, help='known source-specific motion profile')
    parser.add_argument('--object', action='append', default=[], help='external object ID; repeat as needed')
    parser.add_argument('--clearance-m', type=float, default=.05)
    parser.add_argument('--output', required=True, help='new JSON output path')
    args = parser.parse_args(argv)
    from simscene.recipes.motion_keepouts import check_motion_clearance
    from simscene.scene import SceneError
    try:
        scene = json.loads(Path(args.scene).read_text())
        report = check_motion_clearance(scene, args.owner, args.profile, args.object, args.clearance_m)
    except (SceneError, ValueError, TypeError, KeyError, OSError) as error:
        report = {'schema': 'simscene.motion_clearance.v1', 'status': 'error',
                  'error': str(error), 'physics_tested': False}
    with Path(args.output).open('x', encoding='utf8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'output': args.output,
                      'physics_tested': False}, ensure_ascii=False))
    return 1 if report['status'] == 'error' else 2 if report['status'] == 'conflict' else 0


if __name__ == '__main__':
    raise SystemExit(main())
