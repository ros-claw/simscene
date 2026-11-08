"""Build separate portable and Claude plugin trees with isolated Python code."""
import argparse
import json
import shutil
import subprocess
import sys
import re
import hashlib
import tempfile
from pathlib import Path
from importlib import metadata

ROOT=Path(__file__).resolve().parents[1]
def versions(root=ROOT):
    """Map the sole pyproject version to the plugin's development syntax."""
    from packaging.version import Version
    match=re.search(r'^version\s*=\s*"([^"]+)"', (Path(root)/'pyproject.toml').read_text(), re.M)
    if match is None:raise ValueError('pyproject project version is missing')
    python=str(Version(match.group(1)))
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:\.dev\d+)?',python):
        raise ValueError('unsupported Python/plugin version mapping')
    return python,python.replace('.dev','-dev.')

PYTHON_VERSION,PACKAGE_VERSION=versions()
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
    queue=[(Requirement('mcp>=1.0,<2'),{''}),(Requirement('PyYAML>=6,<7'),{''}),(Requirement('Pillow>=10,<13'),{''})];visited={};versions={}
    while queue:
        requirement,parent_extras=queue.pop()
        if requirement.marker and not any(requirement.marker.evaluate({'extra':extra}) for extra in parent_extras):continue
        distribution=metadata.distribution(requirement.name)
        if requirement.name.lower()=='pillow':
            # Shared user site-packages may retain several .dist-info trees.
            # Match the actually loaded PIL module, otherwise the extension
            # can be copied from 12.x while its private libraries come from11.x.
            import PIL
            active=Path(PIL.__file__).resolve()
            matches=[d for d in metadata.distributions() if d.metadata.get('Name','').lower()=='pillow'
                     and d.version==PIL.__version__ and Path(d.locate_file('PIL/__init__.py')).resolve()==active]
            if not matches:raise RuntimeError('active Pillow module has no matching distribution metadata; use a clean build environment')
            distribution=matches[0]
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

VENDOR_CHECK = r"""
import json,sys
from importlib import metadata,resources
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import simscene
assert metadata.version('rosclaw-simscene')==sys.argv[2]
root=resources.files('simscene')
for name in ('catalog/data/sources.yaml','recipes/data/recipes.json','preparation/data/package.json',
             'preparation/data/package-lock.json','preparation/worker.py','worker/isaac_run.py',
             'worker/gpu_queue.py','generation/worker.py','generation/backend_worker.py',
             'generation/templates/guide_plate_v1.py'):
    assert root.joinpath(name).is_file(),name
from simscene.catalog.registry import load_registry
from simscene.recipes.registry import list_recipes
assert load_registry().sources
assert list_recipes()['recipes']
from PIL import Image
assert Image.new('RGB',(2,2)).tobytes()==bytes(12)
print(json.dumps({'version':metadata.version('rosclaw-simscene'),'resource_check':'passed'}))
"""


def validate_vendor(vendor, python=sys.executable):
    subprocess.run([str(python),'-I','-B','-c',VENDOR_CHECK,str(vendor),PYTHON_VERSION],check=True)


def build(destination, use_installed_deps=False):
    requested=Path(destination).expanduser()
    if requested.is_symlink():raise FileExistsError(f'destination is a symlink: {requested}')
    destination=requested.resolve()
    if destination.exists():raise FileExistsError(f'destination already exists: {destination}')
    portable=destination/'portable'/'simscene';claude=destination/'claude'/'simscene';deepseek=destination/'deepseek'/'simscene'
    portable.mkdir(parents=True)
    try:
        vendor=portable/'server'/'vendor';vendor.parent.mkdir()
        # Both paths consume the same locally built wheel. This verifies the
        # setuptools resource contract instead of bypassing it with copytree.
        with tempfile.TemporaryDirectory(prefix='simscene-wheel-') as temporary:
            snapshot=Path(temporary)/'project';snapshot.mkdir()
            for filename in ('pyproject.toml','README.md','LICENSE'):
                shutil.copyfile(ROOT/filename,snapshot/filename)
            shutil.copytree(ROOT/'src',snapshot/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
            wheels=Path(temporary)/'wheels';wheels.mkdir()
            subprocess.run([sys.executable,'-m','pip','wheel','--disable-pip-version-check',
                '--no-deps','--no-build-isolation','--wheel-dir',str(wheels),str(snapshot)],check=True)
            candidates=list(wheels.glob('rosclaw_simscene-*.whl'))
            if len(candidates)!=1:raise RuntimeError('expected exactly one SimScene wheel')
            wheel=candidates[0];wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest()
            if use_installed_deps:
                vendor.mkdir();copy_installed_dependencies(vendor)
            command=[sys.executable,'-m','pip','install','--disable-pip-version-check','--no-compile','--target',str(vendor)]
            if use_installed_deps:command.extend(['--no-deps','--no-index'])
            subprocess.run(command+[str(wheel)],check=True)
            destination.joinpath('wheels').mkdir()
            shutil.copyfile(wheel,destination/'wheels'/wheel.name)
        versions_lock={item.metadata['Name']:item.version for item in metadata.distributions(path=[str(vendor)])}
        write(portable/'server'/'dependency-lock.json',versions_lock)
        write(portable/'server'/'build-info.json',{'python_version':PYTHON_VERSION,'plugin_version':PACKAGE_VERSION,
              'builder_python':sys.version.split()[0],'wheel_sha256':wheel_sha256,
              'dependency_mode':'installed' if use_installed_deps else 'pip',
              'optional_backends':'Isaac/USD, isolated GLB decoder and Sand3D runtimes are configured separately'})
        validate_vendor(vendor)
        (portable/'server'/'launch.py').write_text(LAUNCHER)
        (portable/'README.md').write_text(PACKAGE_README)
        for notice in ('LICENSE','NOTICE','OPEN_SOURCE_NOTICES.md'):
            shutil.copyfile(ROOT/notice,portable/notice)
        shutil.copyfile(ROOT/'plugins'/'install.py',portable/'install.py')
        shutil.copytree(ROOT/'skills',portable/'skills',ignore=shutil.ignore_patterns('__pycache__','*.pyc','.simscene-plugin-root'))
        shutil.copyfile(ROOT/'docs'/'passive-network-verification.md',
                        portable/'skills'/'build-scene'/'references'/'passive-network-verification.md')
        shutil.copyfile(ROOT/'docs'/'structural-loads-verification.md',
                        portable/'skills'/'build-scene'/'references'/'structural-loads-verification.md')
        shutil.copyfile(ROOT/'docs'/'passive-d6-joints.md',
                        portable/'skills'/'build-scene'/'references'/'passive-d6-joints.md')
        write(portable/'plugin.json',{'$schema':'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json','name':'simscene','version':PACKAGE_VERSION,'description':'Discover assets, compose and run experimental simulation scenes.'})
        write(portable/'mcp.json',{'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json','mcpServers':{'simscene':{'type':'stdio','command':'python3','args':['${PLUGIN_ROOT}/server/launch.py'],'cwd':'${PLUGIN_ROOT}'}}})
        claude.mkdir(parents=True)
        shutil.copytree(portable/'server',claude/'server')
        shutil.copytree(portable/'skills',claude/'skills')
        shutil.copyfile(portable/'README.md',claude/'README.md')
        for notice in ('LICENSE','NOTICE','OPEN_SOURCE_NOTICES.md'):
            shutil.copyfile(portable/notice,claude/notice)
        write(claude/'.claude-plugin'/'plugin.json',{'name':'simscene','version':PACKAGE_VERSION,'description':'Discover assets, compose and run experimental simulation scenes.'})
        write(claude/'.mcp.json',{'mcpServers':{'simscene':{'command':'python3','args':['${CLAUDE_PLUGIN_ROOT}/server/launch.py']}}})
        deepseek.mkdir(parents=True)
        shutil.copytree(portable/'server',deepseek/'server')
        shutil.copytree(portable/'skills',deepseek/'skills')
        shutil.copyfile(portable/'README.md',deepseek/'README.md')
        for notice in ('LICENSE','NOTICE','OPEN_SOURCE_NOTICES.md'):
            shutil.copyfile(portable/notice,deepseek/notice)
        try:from .deepseek_patch import write_patch
        except ImportError:from deepseek_patch import write_patch
        write_patch(deepseek,deepseek/'cordis.patch.yml',sys.executable)
        return {'portable':str(portable),'claude':str(claude),'deepseek':str(deepseek),'python':sys.version.split()[0],
                'python_version':PYTHON_VERSION,'plugin_version':PACKAGE_VERSION,'wheel_sha256':wheel_sha256,
                'status':'packages_built_not_registered_or_installed',
                'note':'Build uses binary dependencies for this Python and platform; pxr and Isaac must be configured separately.'}
    except Exception:
        shutil.rmtree(destination,ignore_errors=True)
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--use-installed-deps',action='store_true');args=parser.parse_args()
    print(json.dumps(build(args.output,args.use_installed_deps),indent=2))
