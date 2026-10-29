"""Cross-check the append-only pre-removal ledger against a run result."""
import json
from pathlib import Path

def verify(directory,run):
    archived=run.get('archived_objects')
    if not isinstance(archived,dict):return False
    path=Path(directory)/'archive-ledger.jsonl'
    if not path.exists():return not archived
    try:
        seen={}
        with path.open(encoding='utf8') as file:
            for line in file:
                item=json.loads(line);name=item.get('part_id')
                if not isinstance(name,str) or name in seen:return False
                seen[name]=item
        return seen==archived
    except (OSError,ValueError,TypeError,AttributeError):return False
