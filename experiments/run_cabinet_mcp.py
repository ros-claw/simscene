"""Execute the fixed cabinet example with actual installed MCP operations."""
import argparse
import asyncio
import json
from pathlib import Path
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='new directory for full MCP records and artifacts')
    parser.add_argument('--wheel', required=True, help='wheel matching the installed package build-info')
    parser.add_argument('--scene-id', help='optional new unique scene ID')
    parser.add_argument('--mcp-launcher', help='optional Python stdio launcher for this installed MCP server')
    parser.add_argument('--resume', action='store_true', help='reconnect using saved physics and export requests')
    parser.add_argument('--collect-only', action='store_true', help='wait for saved jobs without starting new jobs')
    args = parser.parse_args()
    if args.collect_only and not args.resume:
        parser.error('--collect-only requires --resume')
    plugin = Path(__file__).resolve().parents[1]
    from simscene.recipes.cabinet_mcp_workflow import new_scene_id, run_installed
    try:
        scene_id = args.scene_id if args.resume else (args.scene_id or new_scene_id())
        result = asyncio.run(run_installed(plugin, args.wheel, args.output, scene_id, args.mcp_launcher,
                                           resume=args.resume, collect_only=args.collect_only))
    except Exception as error:
        directory = Path(args.output)
        if directory.is_dir():
            for index in range(10000):
                log = directory/f'workflow-error-{index:04d}.log'
                try:
                    with log.open('x', encoding='utf8') as stream:stream.write(traceback.format_exc())
                    break
                except FileExistsError:
                    continue
        print(json.dumps({'status': 'incomplete', 'error': str(error)[:500], 'directory': args.output,
                          'recovery': 'If physics-request.json exists, rerun with --resume and the same output and wheel; existing jobs keep their original request IDs.'},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
