"""Durable, serial Codex pilot owner; physical grading is a separate program."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from pilot_usage import collect


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_new(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())


def progress(path, value):
    tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n'); os.replace(tmp, path)


def events(path):
    values = []
    try:
        for line in path.read_text().splitlines():
            try: values.append(json.loads(line))
            except ValueError: continue
    except (OSError, UnicodeError):
        pass
    return values


def session_file(thread_id):
    if not thread_id:
        return None
    matches = list(Path('/home/dell/.codex/sessions').glob('*/*/*/*'+thread_id+'*.jsonl'))
    return matches[0] if len(matches) == 1 else None


def main():
    p = argparse.ArgumentParser(); p.add_argument('--protocol', type=Path, required=True); p.add_argument('--protocol-sha256', required=True)
    a = p.parse_args(); assert sha(a.protocol) == a.protocol_sha256
    protocol = json.loads(a.protocol.read_text()); root = Path(protocol['output_root'])
    for filename, digest in protocol['frozen_files_sha256'].items():
        assert sha(filename) == digest, 'frozen pilot input changed'
    save_new(root/'pilot-owner-start.json', {'utc': now(), 'pid': os.getpid(), 'protocol_sha256': a.protocol_sha256,
             'scope': 'Serial same-model builders only. No automatic physical pass or evaluator changes.'})
    gate = Path(protocol['media_GPU_completion_gate'])
    while not gate.is_file():
        progress(root/'CURRENT.json', {'phase': 'waiting_for_media_GPU_completion', 'utc': now()}); time.sleep(5)
    results = []
    for trial in protocol['trials']:
        directory = Path(trial['directory'])
        assert not (directory/'actual-start.json').exists(), 'never duplicate a reserved trial'
        state = directory/'state'; state.mkdir(exist_ok=False)
        cmd = ['codex', 'exec', '--ignore-user-config', '--skip-git-repo-check', '-s', 'danger-full-access',
               '-c', 'approval_policy="never"', '--model', protocol['model'], '-c', 'model_reasoning_effort='+json.dumps(protocol['reasoning_effort']),
               '-c', 'features.multi_agent=false', '-c', 'web_search="disabled"',
               '-c', 'mcp_servers.simscene.command="/usr/bin/python3.10"',
               '-c', 'mcp_servers.simscene.args='+json.dumps([protocol['MCP_launcher']]),
               '-c', 'mcp_servers.simscene.env.SIMSCENE_HOME='+json.dumps(str(state)),
               '-c', 'mcp_servers.simscene.env.SIMSCENE_ISAAC_PYTHON='+json.dumps(protocol['isaac_python']),
               '-c', 'mcp_servers.simscene.env.SIMSCENE_GPU="0"',
               '-c', 'mcp_servers.simscene.env.CUDA_VISIBLE_DEVICES="0"',
               '-c', 'mcp_servers.simscene.env.SIMSCENE_CACHE_DIRECTORY='+json.dumps(str(state/'assets')),
               '--json', '-C', str(directory), '--output-last-message', str(directory/'final-message.txt'), '-']
        prompt = f'''Use the installed build-scene skill to carry out the task in task/prompt.md and task/{trial['case_filename']}.
Work autonomously to submit the requested real passive experiment and its causal control. This trial has no human coaching.
Working directory: {directory}. You may read this trial's toolkit, skills, common-docs, own task files and own state. Do not read other trials, earlier answers, /code/rosclaw/simscene/evidence, pilot-private-design, examiner, or the live development repository.
Run physics only with the configured simscene MCP simulation_start. It is the same frozen v43 for every trial. Host-side scripts may create/edit ordinary scene operations or read your own observations; never edit a worker, live stage, physics engine or active controller.
Use case_path with the exact task/{trial['case_filename']} bytes for every simulation. Do not use inline case serialization, edit the contract or remove failed attempts. This is a common interface constraint for all trials.
Use the target duration in the public task. Limit yourself to one initial positive plus at most one repaired positive, then one negative after a positive meets your measured goal. Keep all attempts, job IDs, spec paths, native preview and your own read-only checks.
Use low-cost single-camera capture; no full showcase film, online assets, other models or subagents. Same-model budget: {protocol['wall_limit_s']} wall seconds and {protocol['token_limit']} reported input+output tokens. Cached input is included in that input count. Do not ask for clarification or exceed the attempt limit.
Keep tool outputs focused. Reconnect to the same job if needed; a queued/stalled job is not a reason for another start. Worker EXIT0 is separate from the physical result.
Read submission.template.json and write submission.json with every attempt, selected positive/negative directories and all requested provenance, even if you cannot finish. Use anonymous_run_id {trial['anonymous_id']} and task_id {trial['task_id']}; candidate_freeze_manifest_sha256 {protocol['candidate_freeze_sha256']}. Leave provider usage unknown in your submission; the operator captures actual logs. State any assistance, ambiguity, failure or unsupported condition honestly.
Do not publish anything or change the default configuration. Finish by reporting your submission file and actual result.\n'''
        (directory/'actual-prompt.txt').write_text(prompt)
        started = now(); clock = time.monotonic(); stop_reason = None; thread = None; raw_session = None; observed_total = None
        save_new(directory/'actual-start.json', {'utc': started, 'command': cmd, 'prompt_sha256': sha(directory/'actual-prompt.txt'),
                 'protocol_sha256': a.protocol_sha256, 'case_sha256': trial['case_sha256'], 'native_starts_before': 0})
        event_path = directory/'events.jsonl'
        with event_path.open('x') as out, (directory/'stderr.log').open('x') as err:
            child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, start_new_session=True, cwd=directory)
            save_new(directory/'actual-process.json', {'pid': child.pid, 'utc': now()})
            child.stdin.write(prompt.encode()); child.stdin.close()
            try:
                while child.poll() is None:
                    rows = events(event_path)
                    thread = next((r['thread_id'] for r in rows if r.get('type') == 'thread.started'), thread)
                    raw_session = session_file(thread)
                    if raw_session:
                        token_rows = [r for r in events(raw_session) if r.get('type') == 'event_msg' and r.get('payload', {}).get('type') == 'token_count']
                        if token_rows:
                            usage = (token_rows[-1]['payload'].get('info') or {}).get('total_token_usage')
                            if usage is not None: observed_total = usage['input_tokens']+usage['output_tokens']
                    elapsed = time.monotonic()-clock
                    if elapsed > protocol['wall_limit_s']:stop_reason = 'wall_budget_exceeded'
                    if observed_total is not None and observed_total > protocol['token_limit']:stop_reason = 'token_budget_exceeded'
                    progress(root/'CURRENT.json', {'phase': 'builder_running', 'anonymous_id': trial['anonymous_id'], 'task': trial['task_id'],
                             'utc': now(), 'elapsed_s': elapsed, 'reported_tokens_observed': observed_total})
                    if stop_reason:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:child.wait(timeout=20)
                        except subprocess.TimeoutExpired:os.killpg(child.pid, signal.SIGKILL)
                        break
                    time.sleep(2)
            finally:
                code = child.wait()
        thread = next((r['thread_id'] for r in events(event_path) if r.get('type') == 'thread.started'), thread)
        raw_session = session_file(thread)
        copied = None
        if raw_session:
            copied = directory/'raw-session.jsonl'; shutil.copy2(raw_session, copied)
        usage = collect(event_path, copied)
        save_new(directory/'actual-usage.json', usage)
        runs = []
        for lock_path in sorted((state/'runs').glob('*/run-lock.json')):
            lock = json.loads(lock_path.read_text()); runs.append({'run_id': lock_path.parent.name, 'job_id': lock.get('job_id'),
                 'run_directory': str(lock_path.parent), 'source_case_sha256': lock.get('acceptance_case_sha256')})
        result = {'anonymous_id': trial['anonymous_id'], 'task_id': trial['task_id'], 'arm': trial['arm'],
                  'started_at_utc': started, 'ended_at_utc': now(), 'wall_s': time.monotonic()-clock,
                  'actual_cli_exit_code': code, 'stop_reason': stop_reason, 'thread_id': thread,
                  'usage_availability': usage['usage_availability'], 'reported_usage': usage['aggregate_reported_usage'] or usage['request_event_sum'],
                  'raw_session_source': str(raw_session) if raw_session else None,
                  'submission_exists': (directory/'submission.json').is_file(), 'all_discovered_runs': runs,
                  'public_case_unchanged': sha(directory/'task'/trial['case_filename']) == trial['case_sha256'],
                  'physics_score': 'pending independent grading', 'human_task_coaching': False}
        save_new(directory/'actual-trial-owner-receipt.json', result); results.append(result)
    save_new(root/'ALL_TRIALS_COMPLETE.json', {'utc': now(), 'protocol_sha256': a.protocol_sha256, 'trials': results,
             'scope': 'All four allocated builders ended. This is not physical or overall task acceptance.'})
    progress(root/'CURRENT.json', {'phase': 'all_builders_ended_pending_independent_grading', 'utc': now()})


if __name__ == '__main__':
    main()
