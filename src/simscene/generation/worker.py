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
        import simscene
        if Path(simscene.__file__).resolve().parent != (root/'runtime'/'simscene').resolve():
            raise ValueError('generation supervisor was not loaded from the frozen job snapshot')
        if (root/'cancel-request.json').exists():
            phase('cancelled');return
        task=json.loads((root/'task.json').read_text());config=json.loads((root/'config.json').read_text())
        if task.get('expected_generation_intent') is not None:
            from .jobs import _check_expected_intent
            _check_expected_intent(task['expected_generation_intent'],task['recipe_id'],task['parameters'],
                                   task['runtime'],root/'runtime'/'simscene')
        phase('generating')
        if task['recipe_id'] == 'usdcraft_sdk_guide_plate_v1':
            from .usdcraft_sdk import generate_asset
        else:
            from .sand3d import generate_asset
        result=generate_asset(task['recipe_id'],task['parameters'],task['runtime'],output_directory=root/'output',config=config)
        if (root/'cancel-request.json').exists():
            phase('cancelled',result_retained=True);return
        write(root/'result.json',result)
        phase('completed',result=result)
    except Exception as error:
        from .usdcraft_sdk import GenerationCancelled
        if isinstance(error, GenerationCancelled):
            phase('cancelled', result_retained=False)
        else:
            phase('failed',error=str(error),error_type=type(error).__name__)


if __name__=='__main__':
    execute(sys.argv[1])
