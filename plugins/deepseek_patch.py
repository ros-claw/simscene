"""Generate a local DeepSeek Harness Cordis MCP overlay without installing it."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def write_patch(plugin_root, output, python):
    import yaml

    root = Path(plugin_root).expanduser().resolve()
    launcher = root / 'server' / 'launch.py'
    if not launcher.is_file():
        raise FileNotFoundError(f'packaged server not found: {launcher}')
    executable = shutil.which(os.path.expanduser(python))
    if not executable:
        raise FileNotFoundError(f'Python executable not found: {python}')
    # Preserve virtual environment symlinks so Python uses the selected environment.
    executable = str(Path(executable).absolute())
    output = Path(output).expanduser().resolve()
    patch = [{'insert': [{
        'id': 'simscene-mcp',
        'name': '@deepseek-ai/dsh-mcp-client',
        'config': {
            'serverName': 'simscene',
            'transport': 'stdio',
            'command': executable,
            'args': [str(launcher)],
            'env': {},
            'cwd': str(root),
        },
    }]}]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf8') as file:
        yaml.safe_dump(patch, file, allow_unicode=True, sort_keys=False)
    return {'patch': str(output), 'plugin_root': str(root), 'status': 'generated_not_installed'}


if __name__ == '__main__':
    local_root = Path(__file__).resolve().parent
    vendor = local_root / 'server' / 'vendor'
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-root', type=Path, default=local_root)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    output = args.output or args.plugin_root / 'cordis.patch.yml'
    print(json.dumps(write_patch(args.plugin_root, output, args.python), indent=2))
