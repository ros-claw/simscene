"""Compile editable geometry without printing the entire operations array."""
import argparse
import json
from pathlib import Path
import sys
import _bootstrap
from simscene.mechanism_modules import compile_plan, save_plan
p = argparse.ArgumentParser(); p.add_argument('definition', type=Path); p.add_argument('--output', type=Path, required=True)
a = p.parse_args(); definition = json.loads(a.definition.read_text())
if set(definition) != {'kind', 'prefix', 'parameters'}:
    raise ValueError('definition requires kind,prefix,parameters')
print(json.dumps(save_plan(compile_plan(**definition), a.output), ensure_ascii=False))
