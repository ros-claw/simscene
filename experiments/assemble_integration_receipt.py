"""Recheck and assemble a fixed cabinet-example delivery receipt."""
import argparse
import hashlib
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('scene', 'run', 'case', 'recipe', 'identity', 'video', 'edit-map', 'review', 'example-directory'):
        parser.add_argument('--' + name)
    parser.add_argument('--output', required=True, help='new receipt JSON path')
    args = parser.parse_args(argv)
    from simscene.recipes.integration_delivery import collect_delivery
    paths = {name: getattr(args, name) for name in ('scene', 'run', 'case', 'recipe', 'identity', 'video',
                                                    'edit_map', 'review', 'example_directory')
             if getattr(args, name) is not None}
    report = collect_delivery(paths)
    output = Path(args.output)
    with output.open('x', encoding='utf8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'physical_status': report['physical_status'],
                      'media_status': report['media_status'], 'visual_review': report['visual_review'],
                      'missing': report['missing'], 'errors': [value[:300] for value in report['errors'][:5]],
                      'receipt': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()},
                     ensure_ascii=False))
    return 0 if report['status'] == 'ready_for_submission' else 2


if __name__ == '__main__':
    raise SystemExit(main())
