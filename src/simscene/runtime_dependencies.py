"""Recognize a small set of explicit Isaac-provided MDL system dependencies."""
from pathlib import Path

def classify(unresolved, isaac_python=None):
    from .settings import get
    python = isaac_python or get('isaac_python')
    root = Path(python).expanduser().resolve().parent if python else None
    system={}; missing=[]
    for item in map(str,unresolved):
        if item in ('OmniPBR.mdl','OmniGlass.mdl') and root:
            candidate = root / 'kit/mdl/core/Base' / item
            if candidate.is_file():
                system[item]=str(candidate)
                continue
        missing.append(item)
    return {'runtime_provided':system, 'unresolved':missing}
