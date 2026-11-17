"""Execute the fixed cabinet example with actual installed MCP operations."""
import argparse
import asyncio
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='new directory for full MCP records and artifacts')
    parser.add_argument('--wheel', required=True, help='wheel matching the installed package build-info')
    parser.add_argument('--scene-id', default='compact_cabinet_reproduction')
    parser.add_argument('--mcp-launcher', help='optional Python stdio launcher for this installed MCP server')
    args = parser.parse_args()
    plugin = Path(__file__).resolve().parents[1]
    from simscene.recipes.cabinet_mcp_workflow import WorkflowError, run_installed
    try:
        result = asyncio.run(run_installed(plugin, args.wheel, args.output, args.scene_id, args.mcp_launcher))
    except (WorkflowError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'incomplete', 'error': str(error)[:500], 'directory': args.output,
                          'recovery': 'If physics-job.json exists, reconnect to that exact job ID; do not start a duplicate.'},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
