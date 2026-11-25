"""Build, verify and record the installed first delivery example."""
import argparse
import asyncio
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='new output directory, or original directory for recovery or review')
    parser.add_argument('--wheel', help='wheel matching the installed package')
    parser.add_argument('--resume', action='store_true', help='recover the same scene and job requests')
    parser.add_argument('--collect-only', action='store_true', help='recover existing jobs without new starts')
    parser.add_argument('--review', help='record an attributed review of a verified delivery')
    args = parser.parse_args()
    if args.collect_only and not args.resume:
        parser.error('--collect-only requires --resume')
    if args.review and args.resume:
        parser.error('--review records the review of an already completed delivery')
    if not args.review and not args.wheel:
        parser.error('--wheel is required to start or recover a run')
    plugin = Path(__file__).resolve().parents[1]
    from simscene.recipes.cabinet_mcp_workflow import new_scene_id, run_installed
    from simscene.recipes.first_delivery import record_review, run
    try:
        if args.review:
            result = record_review(args.output, args.review)
        else:
            scene_id = new_scene_id().replace('compact_cabinet_', 'first_delivery_', 1)
            result = asyncio.run(run_installed(plugin, args.wheel, args.output, scene_id,
                                              resume=args.resume, collect_only=args.collect_only, workflow=run))
    except Exception as error:
        print(json.dumps({'status': 'incomplete', 'directory': args.output, 'error': str(error)[:900]},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
