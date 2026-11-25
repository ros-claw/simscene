"""Run a bounded real-Codex first delivery with host-owned job waiting."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from pilot_usage import collect, normalize, rows


class Budget:
    """Reserve observable client turns before launching them."""

    def __init__(self, total, per_turn):
        if not 0 < per_turn <= total:
            raise ValueError('positive turn allowance within the total is required')
        self.total = total
        self.per_turn = per_turn
        self.spent = 0
        self.in_flight = None
        self.ledger = []

    def admit(self, phase, *, later_turns):
        if self.in_flight is not None or self.spent + self.per_turn*(1+later_turns) > self.total:
            raise ValueError('model turn would exceed the remaining allowance')
        self.in_flight = phase
        self.ledger.append({'event': 'admitted', 'phase': phase, 'unix_ns': time.time_ns(),
                            'spent_tokens': self.spent, 'reserved_tokens': self.per_turn,
                            'later_turns_reserved': later_turns*self.per_turn})

    def settle(self, phase, usage):
        if self.in_flight != phase or usage is None:
            raise ValueError('the admitted turn must provide actual usage')
        usage = normalize(usage)
        self.in_flight = None
        self.spent += usage['total_tokens']
        self.ledger.append({'event': 'settled', 'phase': phase, 'unix_ns': time.time_ns(),
                            'usage': usage, 'spent_tokens': self.spent})
        if usage['total_tokens'] > self.per_turn or self.spent > self.total:
            raise ValueError('a completed turn exceeded its token allowance')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError('delivery deadline reached')
    return seconds


def object_schema(**fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def require_fixed_turn(events, invalid_lines, phase):
    if invalid_lines or any(not isinstance(event, dict) for _, event in events):
        raise ValueError(f'{phase} contains an invalid CLI event')
    if sum(event.get('type') == 'turn.completed' for _, event in events) != 1:
        raise ValueError(f'{phase} did not produce one complete model turn')
    for _, event in events:
        if event.get('type') in ('item.started', 'item.updated', 'item.completed'):
            item = event.get('item')
            if not isinstance(item, dict) or item.get('type') not in ('reasoning', 'agent_message'):
                raise ValueError(f'{phase} used a tool outside the fixed model turn')


def publish_submission(root, result, deadline):
    staged = root/'submission.pending.json'
    final = root/'submission.json'
    write(staged, result)
    with staged.open('rb') as stream:
        os.fsync(stream.fileno())
    try:
        remaining(deadline)
        os.replace(staged, final)
        remaining(deadline)
    except TimeoutError:
        final.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
        write(root/'submission-late.json', {**result, 'status': 'late'})
        raise


def model_turn(root, phase, prompt, schema, model, budget, deadline, *, later_turns, images=()):
    budget.admit(phase, later_turns=later_turns)
    schema_path = root/f'{phase}.schema.json'
    final = root/f'{phase}.json'
    write(schema_path, schema)
    (root/f'{phase}.txt').write_text(prompt)
    command = [
        'codex', 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
        '--disable', 'shell_tool', '--disable', 'apps', '--disable', 'multi_agent',
        '--disable', 'multi_agent_v2', '-c', 'web_search="disabled"', '--sandbox', 'read-only',
        '--model', model, '--json', '--output-schema', str(schema_path), '-o', str(final),
    ]
    for image in images:
        command.extend(('--image', str(image)))
    events = root/f'{phase}.jsonl'
    with events.open('xb') as out, (root/f'{phase}.stderr').open('xb') as err:
        process = subprocess.run(command+['-'], input=prompt.encode(), cwd=root, stdout=out, stderr=err,
                                 timeout=min(120, remaining(deadline)))
    parsed, invalid = rows(events)
    require_fixed_turn(parsed, invalid, phase)
    report = collect(events)
    write(root/f'{phase}-usage.json', report)
    budget.settle(phase, report['aggregate_reported_usage'])
    if process.returncode or not final.is_file():
        raise ValueError(f'{phase} failed; see its retained CLI output')
    remaining(deadline)
    return read(final)


def media_strips(video, root, deadline):
    """Attach ordered thumbnails of the actual action and settled result."""
    from PIL import Image, ImageDraw

    w, h = 384, 216
    raw = subprocess.check_output([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-threads', '2', '-i', str(video),
        '-vf', f'scale={w}:{h},format=rgb24', '-f', 'rawvideo', '-',
    ], timeout=remaining(deadline))
    frame_bytes = w*h*3
    if len(raw) != 120*frame_bytes:
        raise ValueError('expected the complete 120-frame delivery')
    strips = []
    for name, indices in (('fall', [0, 2, 4, 5, 6, 7, 8, 10, 14]), ('settled', [60, 74, 89, 104, 119])):
        sheet = Image.new('RGB', (3*w, ((len(indices)+2)//3)*(h+20)), '#151d24')
        ink = ImageDraw.Draw(sheet)
        for slot, index in enumerate(indices):
            body = raw[index*frame_bytes:(index+1)*frame_bytes]
            x, y = (slot%3)*w, (slot//3)*(h+20)
            sheet.paste(Image.frombytes('RGB', (w, h), body), (x, y+20))
            ink.text((x+9, y+3), f'frame {index:03d}  {index/30:.2f}s', fill='white')
        path = root/f'{name}.jpg'
        sheet.save(path, quality=90)
        strips.append(path)
    return strips


def engine(plugin, root, arguments, deadline, log):
    env = dict(os.environ, PYTHONPATH=str(plugin/'server/vendor'))
    with (root/log).open('xb') as stream:
        subprocess.run([sys.executable, str(plugin/'experiments/run_first_delivery.py'), *arguments],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, env=env,
                       timeout=remaining(deadline))


def qualify(args, root, budget, deadline):
    plugin, wheel = Path(args.plugin).resolve(), Path(args.wheel).resolve()
    package = read(plugin/'server/build-info.json')
    if package['source_clean'] is not True or package['wheel_sha256'] != sha(wheel):
        raise ValueError('qualification requires an installed package matching a clean-source wheel')
    recipes = read(plugin/'server/vendor/simscene/recipes/data/fixed-examples.json')['examples']
    candidates = {item['id']: item['description'] for item in recipes}
    chosen = read(plugin/'examples/first_delivery/assets.lock.json')['assets']['box']['source_ref']
    text = {'type': 'string'}
    plan = model_turn(
        root, 'discover',
        'Select the fixed installed SimScene example that uses one scanned external object, '
        'an editable worktop and a short verified gravity-drop video. Choose from this actual installed recipe list. '
        'Return the recipe ID and a short reason. Recipes: '+json.dumps(candidates),
        object_schema(recipe_id={'type': 'string', 'enum': list(candidates)}, reason=text),
        args.model, budget, deadline, later_turns=1,
    )
    if plan.get('recipe_id') != 'first_delivery':
        raise ValueError('the client did not select the fixed novice recipe')
    delivery = root/'delivery'
    engine(plugin, root, ['--wheel', str(wheel), '--output', str(delivery)], deadline, 'engine.log')
    receipt = read(delivery/'delivery.json')
    if receipt['status'] != 'needs_visual_review' or receipt['physical_status'] != 'passed' or receipt['media_status'] != 'passed':
        raise ValueError('verified physical and media delivery is required before the review turn')
    video = Path(receipt['video'])
    if sha(video) != receipt['video_sha256']:
        raise ValueError('the video differs from the checked delivery')
    images = media_strips(video, root, deadline)
    review_answer = model_turn(
        root, 'review',
        'Independently inspect the two attached images from one actual 4-second SimScene video. Read the nine ordered early frames '
        '(0 to 0.47 s) and the five ordered late frames (2 to 3.97 s). '
        'Describe the visible object and support, how their relative positions change, and whether the final placement is stable. '
        'If you cannot read either image or the claimed action is obscured, return change_needed. '
        'Use specific visible cues in each observation; do not infer physics sensor results from pixels.',
        object_schema(decision={'type': 'string', 'enum': ['accept', 'change_needed']},
                      fall_observation=text, settled_observation=text),
        args.model, budget, deadline, later_turns=0, images=images,
    )
    review = {
        'reviewer': f'Independent Codex {args.model}', 'decision': review_answer['decision'],
        'video_sha256': receipt['video_sha256'], 'mode': 'ordered attached source-frame strips',
        'reviewed_windows': [
            {'start_s': 0, 'end_s': .5, 'observation': review_answer['fall_observation']},
            {'start_s': 2, 'end_s': 4, 'observation': review_answer['settled_observation']},
        ],
        'attachments': [{'path': str(image), 'sha256': sha(image)} for image in images],
    }
    review_path = root/'attributed-review.json'
    write(review_path, review)
    engine(plugin, root, ['--output', str(delivery), '--review', str(review_path)], deadline, 'review-record.log')
    verified = read(delivery/'reviewed-delivery.json')
    if verified['status'] != 'ready_for_submission':
        raise ValueError('the independent client did not accept the visible result')
    remaining(deadline)
    result = {'schema': 'simscene.first_delivery_qualification.v1', 'status': 'submitted',
              'source_commit': package['source_commit'], 'wheel_sha256': package['wheel_sha256'],
              'selection': chosen, 'model': args.model, 'model_observed_tokens': budget.spent,
              'reviewed_receipt': str(delivery/'reviewed-delivery.json'),
              'reviewed_receipt_sha256': sha(delivery/'reviewed-delivery.json'),
              'video_sha256': receipt['video_sha256'], 'submitted_unix_ns': time.time_ns(),
              'scope': 'Two fresh Codex turns with host-run installed MCP engineering between them. Independent attached-frame review.'}
    publish_submission(root, result, deadline)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', required=True)
    parser.add_argument('--wheel', required=True)
    parser.add_argument('--output', required=True, help='new directory for exactly one attempt')
    parser.add_argument('--model', required=True)
    parser.add_argument('--wall-seconds', type=float, default=900)
    parser.add_argument('--total-tokens', type=int, default=150000)
    parser.add_argument('--turn-allowance', type=int, default=60000)
    args = parser.parse_args()
    if not 0 < args.wall_seconds <= 3600:
        parser.error('wall-seconds must be positive and at most 3600')
    budget = Budget(args.total_tokens, args.turn_allowance)
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    write(root/'contract.json', {'model': args.model, 'wall_seconds': args.wall_seconds,
                                'token_limit': args.total_tokens, 'turn_allowance': args.turn_allowance,
                                'start_unix_ns': time.time_ns(),
                                'usage_scope': 'Admission applies before each host-controlled Codex turn. Internal provider requests and unreported in-flight usage are outside this gate.'})
    try:
        result = qualify(args, root, budget, start+args.wall_seconds)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {'status': 'incomplete', 'error': str(error), 'directory': str(root)}
    result['wall_s'] = time.monotonic()-start
    result['model_observed_tokens'] = budget.spent
    result['pending_usage_turn'] = budget.in_flight
    write(root/'summary.json', result)
    write(root/'budget-ledger.json', budget.ledger)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['status'] == 'submitted' else 2


if __name__ == '__main__':
    raise SystemExit(main())
