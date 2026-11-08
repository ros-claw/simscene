"""Detached bounded generation supervisor; no model-owned polling or Future."""
import json
from pathlib import Path
import sys
from ..preparation.jobs import write


def execute(root):
    root=Path(root).resolve()
    record=json.loads((root/'job.json').read_text())
    def phase(state,**fields):
        record.update(state=state,**fields);write(root/'job.json',record)
    try:
        if (root/'cancel-request.json').exists():
            phase('cancelled');return
        task=json.loads((root/'task.json').read_text());config=json.loads((root/'config.json').read_text())
        phase('generating')
        from .sand3d import generate_asset
        result=generate_asset(task['recipe_id'],task['parameters'],task['runtime'],output_directory=root/'output',config=config)
        if (root/'cancel-request.json').exists():
            phase('cancelled',result_retained=True);return
        write(root/'result.json',result)
        phase('completed',result=result)
    except Exception as error:
        phase('failed',error=str(error),error_type=type(error).__name__)


if __name__=='__main__':
    execute(sys.argv[1])
