"""Install a portable SimScene package and optionally register Codex MCP.

No existing package, skill, or MCP registration is replaced. Registration is
performed by the host's own CLI and verified by reading it back.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def install(package, destination, project=None, register_codex=False, isaac_python=None, codex='codex'):
    package = Path(package).expanduser().resolve()
    destination_path = Path(destination).expanduser()
    if destination_path.is_symlink():
        raise FileExistsError(f'installation destination is a symlink: {destination_path}')
    destination = destination_path.resolve()
    required = ('plugin.json', 'mcp.json', 'server/launch.py',
                'server/vendor/simscene/__init__.py', 'skills/build-scene/SKILL.md')
    if any(not (package / item).is_file() for item in required):
        raise ValueError('source is not a complete portable SimScene package')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'installation destination already exists: {destination}')
    if destination.is_relative_to(package) or package.is_relative_to(destination):
        raise ValueError('package and installation destination must not contain one another')
    project = Path(project).expanduser().resolve() if project else None
    if project is not None and not project.is_dir():
        raise ValueError('project must be an existing directory')
    skill = project / '.agents/skills/build-scene' if project else None
    if skill and (skill.exists() or skill.is_symlink()):
        raise FileExistsError(f'project skill already exists: {skill}')
    if isaac_python is not None:
        isaac_python = str(Path(isaac_python).expanduser().resolve())
        if not Path(isaac_python).is_file():
            raise ValueError('Isaac Python launcher does not exist')
    env = os.environ.copy()
    if register_codex:
        query = subprocess.run([codex, 'mcp', 'list', '--json'], capture_output=True, text=True, env=env, check=True)
        registrations = json.loads(query.stdout)
        if any(item.get('name') == 'simscene' for item in registrations):
            raise FileExistsError('Codex already has a simscene MCP registration; it was not changed')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()  # exclusive: do not overwrite a pre-existing package
    skill_created = False
    try:
        shutil.copytree(package, destination, dirs_exist_ok=True, symlinks=False)
        if any(not (destination / item).is_file() for item in required):
            raise RuntimeError('installed package is incomplete')
        if skill:
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.mkdir()
            skill_created = True
            shutil.copytree(destination / 'skills/build-scene', skill, dirs_exist_ok=True)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        if skill_created: shutil.rmtree(skill, ignore_errors=True)
        raise
    result = {'package_root':str(destination), 'package_installed':True,
              'project_skill':str(skill) if skill else None, 'codex_mcp_registered':False,
              'native_plugin_installed':False}
    if register_codex:
        command = [codex, 'mcp', 'add', 'simscene']
        if isaac_python:
            command += ['--env', 'SIMSCENE_ISAAC_PYTHON=' + isaac_python]
        command += ['--', str(Path(sys.executable).resolve()), str(destination / 'server/launch.py')]
        result['codex_mcp_registered'] = None  # a failed readback is uncertain
        try:
            subprocess.run(command, capture_output=True, text=True, env=env, check=True)
            query = subprocess.run([codex, 'mcp', 'get', 'simscene', '--json'], capture_output=True, text=True, env=env, check=True)
            registered = json.loads(query.stdout)
            transport = registered.get('transport') or {}
            if (registered.get('name') != 'simscene' or transport.get('type') != 'stdio' or
                transport.get('command') != str(Path(sys.executable).resolve()) or
                transport.get('args') != [str(destination / 'server/launch.py')]):
                raise RuntimeError('Codex registration readback did not match the installed launcher')
            if isaac_python and (transport.get('env') or {}).get('SIMSCENE_ISAAC_PYTHON') != isaac_python:
                raise RuntimeError('Codex registration readback did not match the Isaac launcher')
            result['codex_mcp_registered'] = True
        except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as exc:
            result['registration_error'] = str(exc)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', default=str(Path(__file__).resolve().parent), help='portable package root')
    p.add_argument('--destination', required=True, help='new installation directory')
    p.add_argument('--project', help='existing project in which to install the build-scene skill')
    p.add_argument('--register-codex', action='store_true', help='register the installed MCP server with Codex')
    p.add_argument('--isaac-python', help='absolute Isaac Sim python.sh for the registered server')
    args=p.parse_args()
    result=install(args.package,args.destination,args.project,args.register_codex,args.isaac_python)
    print(json.dumps(result,indent=2))
    if args.register_codex and not result['codex_mcp_registered']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
