"""Static MDL closure under a snapshot and explicit launcher SDK roots."""
import re
from pathlib import Path

from .cache import _sha256
from .mdl_dependencies import TEXTURE


def _require(value, message):
    if not value:
        raise ValueError(message)


def runtime_closure(package, files, launcher=None, runtime=None):
    """Pin every external MDL module/resource reached by supported syntax.

    No ambient MDL search path is trusted. Absolute module names resolve only
    in the launcher's SDK core/mdl, except the two classifier-approved
    OmniPBR/OmniGlass modules in core/Base; relative imports resolve beside the module.
    Unsupported syntax, missing files and paths outside these roots fail.
    Standard-module shim files are pinned too; their compiler implementation
    remains part of the separately recorded runtime, not an acquired asset.
    """
    package = Path(package).resolve()
    members = {package/item['path'] for item in files}
    sdk = Path(launcher).expanduser().resolve().parent if launcher else None
    core = sdk/'kit/mdl/core' if sdk else None
    from .runtime_dependencies import classify
    builtins = classify(['OmniPBR.mdl', 'OmniGlass.mdl'], launcher)['runtime_provided'] if launcher else {}
    runtime = runtime or {}
    _require(isinstance(runtime, dict), 'MDL runtime roots must be a mapping')
    for name, path in runtime.items():
        _require(name in builtins and str(path) == builtins[name], 'MDL runtime root is not the explicit classifier-selected SDK module')
    pending = [p for p in members if p.suffix.lower() == '.mdl'] + [Path(p) for p in runtime.values()]
    visited, result = set(), {}

    def check(path):
        path = Path(path)
        resolved = path.resolve()
        _require(path.is_file() and not path.is_symlink(), 'MDL dependency missing or symlinked: '+str(path))
        if resolved.is_relative_to(package):
            _require(resolved in members, 'MDL dependency not in complete snapshot inventory')
        else:
            _require(core is not None and resolved.is_relative_to(core.resolve()), 'MDL dependency outside explicit SDK core root')
            relative = path.relative_to(sdk)
            _require(not any(sdk.joinpath(*relative.parts[:i]).is_symlink() for i in range(1, len(relative.parts)+1)), 'MDL runtime dependency ancestor is symlinked')
            result[resolved.relative_to(sdk).as_posix()] = {'size': resolved.stat().st_size, 'sha256': _sha256(resolved)}
        return resolved

    def module_path(name, parent):
        _require(re.fullmatch(r'(?:::|\.\.?::)?[A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*', name), 'unsupported MDL module name')
        if name.startswith('::'):
            _require(core is not None, 'absolute MDL import requires an explicit SDK launcher')
            if name in ('::OmniPBR', '::OmniGlass'):
                filename = name[2:]+'.mdl'
                _require(filename in builtins, 'explicit SDK builtin MDL module missing: '+filename)
                return Path(builtins[filename])
            return core/'mdl'/Path(*name[2:].split('::')).with_suffix('.mdl')
        return parent/Path(*name.split('::')).with_suffix('.mdl')

    token = re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*')
    statement = re.compile(r'\busing\s+(\S+)\s+import\s+([^;]+);|\bimport\s+([^;]+);')
    while pending:
        module = check(pending.pop())
        if module in visited or module.suffix.lower() != '.mdl':
            continue
        visited.add(module)
        _require(len(visited) <= 256 and module.stat().st_size <= 8*1024*1024, 'MDL scan budget exceeded')
        source = token.sub(lambda match: match.group(0) if match.group(0).startswith('"') else ' ', module.read_text(errors='strict'))
        # MDL's anno::thumbnail is editor metadata, not a texture resource.
        # SDK modules ship missing UI thumbnails; their literal stays covered
        # by the module byte hash but cannot affect material evaluation.
        resource_source = re.sub(r'(?:::)?anno::thumbnail\s*\(\s*"(?:\\.|[^"\\])*"\s*\)', ' ', source)
        for literal in re.findall(r'"((?:\\.|[^"\\])*)"', resource_source):
            if TEXTURE.search(literal):
                _require('\\' not in literal and ':' not in literal and not literal.startswith('/'), 'MDL contains a nonlocal texture literal')
                pending.append(module.parent/literal)
        syntax = re.sub(r'"(?:\\.|[^"\\])*"', ' ', source)
        for match in statement.finditer(syntax):
            if match.group(1):
                _require(re.fullmatch(r'\s*(?:\*|[A-Za-z_][A-Za-z_0-9]*)(?:\s*,\s*[A-Za-z_][A-Za-z_0-9]*)*\s*', match.group(2)), 'unsupported MDL using declaration')
                names = [match.group(1)]
            else:
                names = []
                for declaration in match.group(3).split(','):
                    declaration = declaration.strip()
                    _require('::' in declaration, 'unsupported MDL import declaration')
                    name, symbol = declaration.rsplit('::', 1)
                    _require(re.fullmatch(r'\*|[A-Za-z_][A-Za-z_0-9]*', symbol), 'unsupported MDL import symbol')
                    names.append(name)
            pending.extend(module_path(name, module.parent) for name in names)
        _require(not re.search(r'\b(import|using)\b', statement.sub(' ', syntax)), 'unsupported MDL dependency syntax')
    return dict(sorted(result.items()))
