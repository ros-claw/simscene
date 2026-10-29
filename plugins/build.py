"""Build separate portable and Claude plugin trees with isolated Python code."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from importlib import metadata

ROOT=Path(__file__).resolve().parents[1]
LAUNCHER='''"""Start the packaged MCP server without importing the development checkout."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
from simscene.mcp_server import main
main()
'''
PACKAGE_README='''# SimScene

SimScene helps an agent discover online simulation assets, inspect and acquire
selected files, compose editable USD scenes, start Isaac Sim and examine camera
images and measured physical state. The simulation host needs a compatible
Isaac Sim installation and USD Python bindings; robot control and collision
checks remain experimental. Configure `SIMSCENE_ISAAC_PYTHON` for the host and
use the `build-scene` skill to create and observe a scene. Asset licensing and
dependency completeness must be checked for each selected model.
'''
def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n')

def copy_installed_dependencies(vendor):
    """Vendor the active environment's validated dependency closure offline."""
    from packaging.requirements import Requirement
    queue=[(Requirement('mcp>=1.0,<2'),{''}),(Requirement('PyYAML>=6,<7'),{''})];visited={};versions={}
    while queue:
        requirement,parent_extras=queue.pop()
        if requirement.marker and not any(requirement.marker.evaluate({'extra':extra}) for extra in parent_extras):continue
        distribution=metadata.distribution(requirement.name)
        if requirement.specifier and distribution.version not in requirement.specifier:
            raise RuntimeError(f'{requirement} is incompatible with installed {distribution.version}')
        canonical=distribution.metadata['Name'].lower().replace('_','-')
        extras=set(requirement.extras)|{''}
        new=extras-visited.get(canonical,set())
        if not new:continue
        first=canonical not in visited
        visited.setdefault(canonical,set()).update(extras)
        if first:
            versions[distribution.metadata['Name']]=distribution.version
            for file in distribution.files or []:
                if '..' in file.parts or file.is_absolute() or '__pycache__' in file.parts or file.suffix=='.pyc':continue
                source=Path(distribution.locate_file(file))
                if not source.is_file():continue
                target=vendor.joinpath(*file.parts);target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,target)
        for dependency in distribution.requires or []:
            queue.append((Requirement(dependency),new))
    return versions

def build(destination, use_installed_deps=False):
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError(f'destination already exists: {destination}')
    portable=destination/'portable'/'simscene';claude=destination/'claude'/'simscene';deepseek=destination/'deepseek'/'simscene'
    portable.mkdir(parents=True)
    try:
        vendor=portable/'server'/'vendor';vendor.parent.mkdir()
        if use_installed_deps:
            vendor.mkdir()
            versions=copy_installed_dependencies(vendor)
            shutil.copytree(ROOT/'src'/'simscene',vendor/'simscene',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            write(portable/'server'/'dependency-lock.json',versions)
        else:
            subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-compile','--target',str(vendor),str(ROOT)],check=True)
        (portable/'server'/'launch.py').write_text(LAUNCHER)
        (portable/'README.md').write_text(PACKAGE_README)
        shutil.copyfile(ROOT/'LICENSE',portable/'LICENSE')
        shutil.copyfile(ROOT/'plugins'/'install.py',portable/'install.py')
        shutil.copytree(ROOT/'skills',portable/'skills',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        write(portable/'plugin.json',{'$schema':'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json','name':'simscene','version':'0.1.0-dev.0','description':'Discover assets, compose and run experimental simulation scenes.'})
        write(portable/'mcp.json',{'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json','mcpServers':{'simscene':{'type':'stdio','command':'python3','args':['${PLUGIN_ROOT}/server/launch.py'],'cwd':'${PLUGIN_ROOT}'}}})
        claude.mkdir(parents=True)
        shutil.copytree(portable/'server',claude/'server')
        shutil.copytree(portable/'skills',claude/'skills')
        shutil.copyfile(portable/'README.md',claude/'README.md')
        shutil.copyfile(portable/'LICENSE',claude/'LICENSE')
        write(claude/'.claude-plugin'/'plugin.json',{'name':'simscene','version':'0.1.0-dev.0','description':'Discover assets, compose and run experimental simulation scenes.'})
        write(claude/'.mcp.json',{'mcpServers':{'simscene':{'command':'python3','args':['${CLAUDE_PLUGIN_ROOT}/server/launch.py']}}})
        deepseek.mkdir(parents=True)
        shutil.copytree(portable/'server',deepseek/'server')
        shutil.copytree(portable/'skills',deepseek/'skills')
        shutil.copyfile(portable/'README.md',deepseek/'README.md')
        shutil.copyfile(portable/'LICENSE',deepseek/'LICENSE')
        try:from .deepseek_patch import write_patch
        except ImportError:from deepseek_patch import write_patch
        write_patch(deepseek,deepseek/'cordis.patch.yml',sys.executable)
        return {'portable':str(portable),'claude':str(claude),'deepseek':str(deepseek),'python':sys.version.split()[0],
                'status':'packages_built_not_registered_or_installed',
                'note':'Build uses binary dependencies for this Python and platform; pxr and Isaac must be configured separately.'}
    except Exception:
        shutil.rmtree(destination,ignore_errors=True)
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--use-installed-deps',action='store_true');args=parser.parse_args()
    print(json.dumps(build(args.output,args.use_installed_deps),indent=2))
