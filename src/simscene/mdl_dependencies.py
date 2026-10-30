"""Conservative static discovery of relative MDL modules and texture literals.

USD dependency APIs do not inspect MDL import statements or texture defaults.
This scanner does not execute source code or resolve arbitrary module roots.
"""
import re
from pathlib import Path

TEXTURE=re.compile(r'\.(?:png|jpe?g|exr|hdr|dds|bmp|tga|tiff?)$',re.I)

def references(path):
    path=Path(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('MDL source exceeds scan budget')
    source=path.read_text(errors='replace')
    # Keep string literals while removing comments so documentation examples
    # do not become attempted network requests.
    token=re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*')
    source=token.sub(lambda m:m.group(0) if m.group(0).startswith('"') else ' ',source)
    found=[]
    for match in re.finditer(r'\bimport\s+((?:\.\.?::)?[A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*)::\*\s*;',source):
        module=match.group(1);parts=module.split('::')
        found.append(path.parent/Path(*parts).with_suffix('.mdl'))
    for match in re.finditer(r'"((?:\\.|[^"\\])*)"',source):
        value=match.group(1)
        if TEXTURE.search(value):
            if '\\' in value or ':' in value or value.startswith('/'):continue
            found.append(path.parent/value)
    return sorted(set(p.resolve() for p in found))
