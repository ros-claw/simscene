#!/usr/bin/env python3
"""Isolated Codex catalog-task evaluation; importing/dry-run launches nothing.

The host verifies saved business evidence with the supplied installed package.
Workspace-write plus trace auditing is not an operating-system read jail.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import inspect
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import shlex
import subprocess
import sys
import time

MARKER = '${notebook.prepared_manifest_sha256}'
NEW_TOOLS = frozenset({'catalog_search', 'asset_plan', 'asset_prepare'})
ALLOWED_TOOLS = ('environment_probe', 'catalog_search', 'asset_plan', 'asset_prepare',
                 'asset_search', 'asset_inspect', 'asset_acquire', 'asset_inspect_local',
                 'job_status', 'scene_open', 'scene_get', 'scene_apply', 'scene_validate',
                 'scene_measure', 'simulation_start', 'run_observe', 'run_contacts',
                 'scene_observe', 'run_verify', 'run_verify_lock', 'run_verify_evidence')
TASK_FIELDS = ('prompt_file', 'recipe_file', 'asset_lock_file', 'case_template_file')
MAX_TRACE_BYTES = 256 * 1024**2


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def member(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('task file must be a safe relative path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or value == '.':
        raise ValueError('unsafe task file path')
    return path


def hashes(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            raise ValueError('input tree contains a symlink')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def validate_case(template, submitted, prepared_hashes):
    """Only the one explicitly portable identity marker may change."""
    if template.get('prepared_manifest_sha256') != MARKER:
        raise ValueError('case template must contain the portable prepared identity marker')
    value = submitted.get('prepared_manifest_sha256')
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) or value not in prepared_hashes:
        raise ValueError('case identity was not observed from actual preparation')
    expected = deepcopy(template); expected['prepared_manifest_sha256'] = value
    if submitted != expected:
        raise ValueError('case predicates changed beyond prepared_manifest_sha256')
    return value



def recipe_equal(expected, actual, tolerance=1e-6):
    """Recursive physical-value comparison; booleans never equal numeric aliases."""
    if isinstance(expected,bool) or isinstance(actual,bool):
        return type(expected) is bool and type(actual) is bool and expected == actual
    if isinstance(expected,(int,float)) and isinstance(actual,(int,float)):
        return math.isfinite(expected) and math.isfinite(actual) and abs(expected-actual)<=tolerance
    if isinstance(expected,dict) and isinstance(actual,dict):
        return set(expected)==set(actual) and all(recipe_equal(value,actual[key],tolerance) for key,value in expected.items())
    if isinstance(expected,list) and isinstance(actual,list):
        return len(expected)==len(actual) and all(recipe_equal(a,b,tolerance) for a,b in zip(expected,actual))
    return type(expected) is type(actual) and expected==actual


def validate_recipe_contract(recipe, spec, case, manifests):
    """Require physical actors and prepared recipes; only presentation is optional."""
    expected_objects=recipe['objects'];actual_objects=spec['objects']
    def physical(obj):
        return obj.get('dynamic') is True or obj.get('collision') is True or obj.get('kind') in ('joint','compound')
    expected_physical={name for name,obj in expected_objects.items() if physical(obj)}
    actual_physical={name for name,obj in actual_objects.items() if physical(obj) or
                     manifests.get(name,{}).get('profile_id') in ('rigid_prop_v1','static_fixture_v1')}
    if actual_physical!=expected_physical:
        raise ValueError('fixed-layout physical actor set differs from recipe')
    notebooks={name for name,obj in expected_objects.items() if obj.get('asset_role')=='notebook'}
    if len(notebooks)!=4 or notebooks!=set(case['objects']) or not notebooks<=set(manifests):
        raise ValueError('case requires all four actual notebook manifests')
    if 'workbench' not in actual_objects or expected_objects['workbench'].get('asset_role')!='workbench':
        raise ValueError('locked workbench is required')
    def canonical(obj):
        result={key:value for key,value in obj.items() if key not in ('asset_role','asset_path','asset_binding')}
        result.setdefault('position',[0,0,0]);result.setdefault('orientation_wxyz',[1,0,0,0])
        result.setdefault('dynamic',False);result.setdefault('collision',False)
        return result
    for name in expected_physical|{'workbench'}:
        if name not in actual_objects or not recipe_equal(canonical(expected_objects[name]),canonical(actual_objects[name])):
            raise ValueError('fixed-layout physical recipe changed: '+name)
    role=recipe['asset_roles']['notebook']
    for name in notebooks:
        manifest=manifests[name]
        if manifest.get('profile_id')!=role['profile_id'] or not recipe_equal(role['parameters'],manifest.get('parameters')):
            raise ValueError('notebook prepared profile/parameters differ from recipe: '+name)
    return {'physical_actor_ids':sorted(expected_physical),'notebook_ids':sorted(notebooks),
            'numeric_tolerance':1e-6,'optional_scope':'nonphysical visuals, lights and cameras may differ'}



def require_source_coverage(case, source_checks):
    required=set(case['objects'])|{'workbench'}
    if not required<=set(source_checks) or not all(value is True for value in source_checks.values()):
        raise ValueError('all four notebook source identities and locked workbench are required')
    return True


def tool_payload(item):
    result = item.get('result')
    if not isinstance(result, dict):
        return None
    structured = result.get('structured_content', result.get('structuredContent'))
    if isinstance(structured, dict):
        return structured
    for block in result.get('content', []):
        if block.get('type') == 'text':
            try:
                return json.loads(block['text'])
            except (ValueError, KeyError):
                continue
    return None



def audited_shell_text(command, work=None):
    """Mask only inert quoted cat/tee data writes; retain all executable text.

    This intentionally recognizes a narrow syntax rather than interpreting shell
    code. Ambiguous headers, input filenames, pipelines and executable heredocs
    remain fully visible to the heuristic audit.
    """
    text=command
    try:
        argv=shlex.split(command,posix=True)
        if len(argv)==3 and argv[0] in ('/bin/bash','bash','/bin/sh','sh') and argv[1] in ('-lc','-c'):
            text=argv[2]
    except ValueError:
        pass
    if work is None:return text,0
    work=Path(work).resolve()
    # A redefined writer or changed PATH is not a plain cat/tee invocation.
    if re.search(r'(?:^|[;\n])\s*(?:alias\s+(?:cat|tee)\b|(?:function\s+)?(?:cat|tee)\s*\(\)|(?:export\s+)?PATH=)',text):
        return text,0
    quoted=re.compile(r"<<(?P<tabs>-?)\s*(?:'(?P<single>[A-Za-z_][A-Za-z_0-9]*)'|\"(?P<double>[A-Za-z_][A-Za-z_0-9]*)\")(?=$|[\s;&|<>])")
    lines=text.splitlines(keepends=True);result=[];index=0;masked=0
    while index<len(lines):
        header=lines[index];match=quoted.search(header)
        if match is None or header.count('<<')!=1:
            result.append(header);index+=1;continue
        delimiter=match.group('single') or match.group('double')
        lexer=shlex.shlex(header,posix=True,punctuation_chars='<>;&|')
        lexer.whitespace_split=True;lexer.commenters=''
        try:tokens=list(lexer)
        except ValueError:
            result.append(header);index+=1;continue
        split=next((i for i,token in enumerate(tokens) if token and all(c in ';&|' for c in token)),len(tokens))
        # A pipe can feed quoted text into an executable, so it is never masked.
        plain=tokens[:split] if split==len(tokens) or tokens[split] in (';','&&','||') else []
        operator='<<'
        try:
            position=plain.index(operator)
            if plain[position+1]!=(('-' if match.group('tabs') else '')+delimiter):raise ValueError('delimiter mismatch')
            plain=plain[:position]+plain[position+2:]
        except (ValueError,IndexError):plain=[]
        filename=None
        if len(plain)==3 and plain[0] in ('cat','/bin/cat','/usr/bin/cat') and plain[1] in ('>','>>'):
            filename=plain[2]
        elif len(plain)==2 and plain[0] in ('tee','/bin/tee','/usr/bin/tee'):
            filename=plain[1]
        safe=filename and filename!='-' and not filename.startswith('-') and not any(c in filename for c in '$`*?[]{}~\n\r')
        if safe:
            path=Path(filename);path=path if path.is_absolute() else work/path
            safe=path.resolve().is_relative_to(work)
        end=None
        if safe:
            for candidate in range(index+1,len(lines)):
                closing=lines[candidate].rstrip('\r\n')
                if match.group('tabs'):closing=closing.lstrip('\t')
                if closing==delimiter:end=candidate;break
        if end is None:
            result.append(header);index+=1;continue
        result.extend([header,'# quoted data body omitted from heuristic audit\n',lines[end]])
        masked+=1;index=end+1
    return ''.join(result),masked


def command_diagnostic(command, audited):
    return {'command_sha256':hashlib.sha256(command.encode()).hexdigest(),
            'command_excerpt':audited[:240]}


def file_audit_text(command):
    """Ignore literal rg glob options, while retaining executable shell text."""
    if any(char in command for char in '$`;\n\r&|<>'):
        return command
    try:
        tokens=shlex.split(command)
    except ValueError:
        return command
    if not tokens or tokens[0]!='rg':return command
    result=[];index=0
    while index<len(tokens):
        token=tokens[index]
        if token in ('-g','--glob','--iglob') and index+1<len(tokens):
            result.extend([token,'LITERAL_GLOB']);index+=2;continue
        if token.startswith(('--glob=','--iglob=')):
            result.append(token.split('=',1)[0]+'=LITERAL_GLOB')
        else:result.append(token)
        index+=1
    return shlex.join(result)


def analyze_trace(path, work=None):
    """Keep call status histories/errors; never infer success from agent prose."""
    calls = {}; invalid = []; violations = []; turns = []; commands = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        try:
            event = json.loads(line)
        except ValueError:
            invalid.append(number); continue
        if not isinstance(event,dict):
            invalid.append(number);continue
        if event.get('type') in ('turn.completed', 'turn.failed', 'error'):
            turns.append(event)
        item = event.get('item', {})
        if not isinstance(item,dict):
            invalid.append(number);continue
        kind = item.get('type', '')
        if kind == 'mcp_tool_call':
            key = item.get('id', f'line-{number}')
            record = calls.setdefault(key, {'statuses': [], 'source_lines': []})
            record['statuses'].append(item.get('status')); record['source_lines'].append(number)
            record.update({k: item.get(k) for k in ('server', 'tool', 'arguments', 'result', 'error', 'status')})
            if item.get('server') != 'simscene' or item.get('tool') not in ALLOWED_TOOLS:
                violations.append({'line': number, 'reason': 'unapproved MCP tool'})
        elif any(token in kind for token in ('collab', 'web_search', 'agent_spawn')):
            violations.append({'line': number, 'reason': 'child agent or web tool'})
        elif kind == 'command_execution':
            raw_command=item.get('command','')
            command,masked=audited_shell_text(raw_command,work)
            diagnostic=command_diagnostic(raw_command,command)
            commands.append({'line':number,**{k:item.get(k) for k in ('id','type','status','exit_code','error')},
                             **diagnostic,'masked_quoted_data_blocks':masked,
                             'output_sha256':hashlib.sha256(str(item.get('aggregated_output','')).encode()).hexdigest()})
            if re.search(r'(?<![\w/-])(?:curl|wget|pip|npm|codex|isaac[-_]?sim)\s|(?:from|import)\s+simscene\b|subprocess|os\.system', command, re.I):
                violations.append({'line': number, 'reason': 'possible shell MCP bypass', **diagnostic})
            file_command=file_audit_text(command)
            if str(Path(__file__).resolve().parents[1]) in file_command or re.search(r'(?:cat|tee|find|rg|ls|sed|head|tail)\s+[^\n]*(?:\.\./|/\.codex/)', file_command):
                violations.append({'line': number, 'reason': 'possible read outside own task', **diagnostic})
            if work and re.search(r'\b(?:cat|tee|find|rg|ls|sed|head|tail)\s',command):
                # Relative globs such as task/cache/*/lock.json are one path,
                # not an absolute /lock.json tail. Keep absolute glob operands.
                paths=re.findall(r'(?<![\w:./*?\[\]{}~-])/[A-Za-z0-9_.*?~\[\]{}/-]+',file_command)
                if any(p not in ('/bin/bash','/dev/null') and not p.startswith(str(work)+'/') and p!=str(work) for p in paths):
                    violations.append({'line':number,'reason':'external path in shell file command',**diagnostic})
    successful = []
    for item in calls.values():
        result = item.get('result') or {}
        item['successful'] = (item.get('status') == 'completed' and not item.get('error')
                              and isinstance(result, dict) and not result.get('isError', result.get('is_error', False)))
        if item['successful']:
            successful.append(item['tool'])
    sources=set()
    attempts=set()
    for item in calls.values():
        if item['successful'] and item['tool']=='catalog_search':
            arguments=item.get('arguments') or {}
            filters=arguments.get('filters') or {}
            if isinstance(filters,dict):sources.update(filters.get('source_ids') or [])
        if item['successful'] and item['tool']=='simulation_start' and isinstance(tool_payload(item),dict):
            if tool_payload(item).get('job_id'):attempts.add(tool_payload(item)['job_id'])
    return {'calls': list(calls.values()), 'command_events':commands, 'turn_events': turns, 'invalid_lines': invalid,
            'scope_violations': violations, 'explicit_sources_searched':sorted(sources),
            'legacy_compatibility_tools_called':'asset_acquire' in successful,
            'simulation_attempts':len(attempts), 'required_new_tools_called': NEW_TOOLS <= set(successful),
            'simulation_calls': sum(c['successful'] and c['tool'] == 'simulation_start' for c in calls.values()),
            'scope_audit_version':2, 'scope_audit': 'instruction boundaries and trace checks; not an OS-level read confinement proof'}


def command(package, work, output, model, effort, server_env):
    settings = {'approval_policy': 'never', 'features.multi_agent': False, 'web_search': 'disabled',
                'sandbox_workspace_write.network_access': False,
                'mcp_servers.simscene.command': sys.executable,
                'mcp_servers.simscene.args': [str(package / 'server/launch.py')],
                # Forward names, never serialize proxy values into commands/receipts.
                'mcp_servers.simscene.env_vars': ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy'],
                'mcp_servers.simscene.enabled_tools': list(ALLOWED_TOOLS),
                'mcp_servers.simscene.default_tools_approval_mode': 'approve',
                'model_reasoning_effort': effort}
    cmd = ['codex', 'exec', '--ignore-user-config', '--skip-git-repo-check', '--ephemeral', '--json',
           '--sandbox', 'workspace-write', '-C', str(work), '--model', model]
    for key, value in settings.items():
        cmd.extend(['-c', key + '=' + json.dumps(value)])
    # TOML inline tables use '=' rather than JSON's ':' separators.
    cmd.extend(['-c', 'mcp_servers.simscene.env={' + ','.join(k + '=' + json.dumps(v) for k, v in server_env.items()) + '}'])
    return cmd + ['--output-last-message', str(output / 'last-message.txt'), '-']


def prepare(args):
    package = Path(args.package).expanduser().resolve(); task = Path(args.case).expanduser().resolve()
    output = Path(args.output).expanduser().resolve(); checkout = Path(__file__).resolve().parents[1]
    if output.exists() or output.is_relative_to(checkout):
        raise ValueError('output must be a new directory outside the checkout')
    if package.is_relative_to(checkout) or not (package / 'server/launch.py').is_file() or not (package / 'server/vendor/simscene').is_dir():
        raise ValueError('supply an installed portable package outside the checkout')
    definition = read(task)
    files = {task.name: task}
    for field in TASK_FIELDS:
        path = task.parent / member(definition[field])
        if str(member(definition[field])) in files:raise ValueError('task files must be distinct')
        if path.is_symlink() or not path.is_file():
            raise ValueError('task input is missing or symlinked')
        files[str(member(definition[field]))] = path
    template = read(files[definition['case_template_file']])
    if template.get('prepared_manifest_sha256') != MARKER:
        raise ValueError('case template is not portable')
    package_hashes = hashes(package)
    source_config = read(args.v2_config) if args.v2_config else {}
    output.mkdir(parents=True); work = output / 'work'; work.mkdir(); state = output / 'state'; state.mkdir()
    task_root = work / 'task'; task_root.mkdir()
    for name, source in files.items():
        target = task_root / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
    skill_root = work / '.agents/skills'; skill_root.mkdir(parents=True)
    for source in sorted((package / 'skills').iterdir()):
        if source.is_dir():
            shutil.copytree(source, skill_root / source.name)
            (skill_root / source.name / '.simscene-plugin-root').write_text(str(package) + '\n')
    if not (skill_root / 'build-scene/SKILL.md').is_file():
        raise ValueError('installed build-scene skill missing')
    cache = Path(args.cache_root).expanduser().resolve() if args.cache_root else output / 'cache'
    config = dict(source_config)
    for key in ('index_directory','prepared_directory','runtime_manifest','registry_path','converter_tools_prefix'):
        if key in config:config[key]=str(Path(config[key]).expanduser().resolve())
    config.setdefault('index_directory', str(state / 'catalog-v1'))
    config.setdefault('prepared_directory', str(cache.with_name(cache.name+'-prepared-v1') if args.cache_root else output / 'prepared'))
    config.setdefault('runtime_manifest', str(state / 'preparation-runtime.json'))
    write(output / 'v2.json', config)
    server_env = {'SIMSCENE_HOME': str(state), 'SIMSCENE_CACHE': str(cache),
                  'XDG_CONFIG_HOME': str(output / 'config'), 'SIMSCENE_V2_CONFIG': str(output / 'v2.json'),
                  'SIMSCENE_PHYSICS_DEVICE': 'cpu'}
    for key in ('SIMSCENE_ISAAC_PYTHON', 'SIMSCENE_GLTF_TRANSFORM_PREFIX', 'SIMSCENE_GPU'):
        if os.environ.get(key):
            server_env[key] = os.environ[key]
    prompt = f'''Use only the copied installed build-scene skill and task files under {task_root}.
The caller declares source/prepared cache condition {args.cache_condition}; report actual cache_hit and transfer bytes. Provider prompt-cache usage is separate.
This is a fixed-layout catalog integration evaluation, not an efficiency benchmark. Never read the development checkout, other trials, global skills or global configuration. No child agents, publication, source edits, direct SDK execution or shell imports/calls of SimScene. Use only the configured SimScene MCP for all discovery, acquisition, preparation, scene editing, physics, observation and verification. Shell may read own task/skill files and write own submission files only.
Follow task/{task.name} and its prompt. Search BOTH explicit audited sources. Select only the locked assets. Call catalog_search, asset_plan and asset_prepare for the exact notebook recipe. Respect all separate budgets and preserve every failed attempt. Poll the same jobs; do not relaunch uncertain/running jobs. For job_status(wait_seconds>0), choose a NEW absolute receipt_path inside your own work directory as the caller; otherwise use wait_seconds=0. This receipt path is an output you choose, not a path returned by the server. Replay asset_prepare with the same request_id once to check idempotency. NVIDIA workbench uses the disclosed legacy asset_acquire compatibility route; locked native metadata is already provided, so do not require a large remote asset_inspect graph. Use optional asset_inspect_local on the selected table member when needed. Its unresolved licensing does not become a ready catalog plan.
Source/prepared cache hits never constitute a reused physics verdict: execute a fresh physics run. Use the exact scene field orientation_wxyz (not orientation).
Build all four independent notebook instances and the exact editable recipe layout through MCP. Remove asset_role recipe metadata when submitting scene objects; resolve notebook asset_path/asset_binding from actual preparation, and workbench asset_path to its locked selected member. Keep source materials and experimental mass/scaling assumptions. Observation must remain strict per-step with physical contact pairs. Recording is optional; do not claim final video delivery.
BEFORE simulation write {work / 'submission-case.json'} by copying the immutable task case template and replacing ONLY its root prepared_manifest_sha256 marker with the actual prepared manifest hash. Never modify any task template/predicate. Freeze this new case via simulation_start.case_path. Use the recorded seed/steps and CPU physics. At most two simulation attempts; retain all attempts and failures. Run run_verify(case_type='rigid_asset_smoke'), run_verify_lock and run_verify_evidence; inspect body positions, bounds and exact contacts.
Save {work / 'submission.json'} containing selected references, plan/preparation IDs, every attempted simulation job ID, case_path, cache/assistance declarations, actual outcomes/failures/unknowns and initial/final body observations. Do not invent token cost or savings. The host independently verifies persisted evidence. Finish briefly; no permission question.
'''
    (output / 'prompt.txt').write_text(prompt)
    (work / 'AGENTS.md').write_text('Follow the supplied evaluation scope. Read only this work directory; use only copied skills. All SimScene operations must use the configured MCP. Never access other trials or source checkouts.\n')
    if not server_env.get('SIMSCENE_ISAAC_PYTHON') and Path(config['runtime_manifest']).is_file():
        observed_launcher=read(config['runtime_manifest']).get('installation',{}).get('isaac_launcher')
        if observed_launcher:server_env['SIMSCENE_ISAAC_PYTHON']=observed_launcher
    cmd = command(package, work, output, args.model, args.reasoning_effort, server_env)
    meta = {'schema': 'simscene.catalog_agent_eval.v1', 'client': 'codex', 'model': args.model,
            'reasoning_effort': args.reasoning_effort, 'wall_limit_s': args.wall_limit_s,
            'cache_condition': args.cache_condition, 'cache_condition_basis': 'caller declaration; model cache is separately reported usage',
            'cache_root': str(cache), 'cache_root_preexisting': cache.exists(), 'package': str(package),
            'task_definition': task.name, 'task_files': hashes(task_root), 'package_files': package_hashes,
            'copied_skills': hashes(skill_root), 'tool_allowlist': list(ALLOWED_TOOLS), 'mcp_environment': server_env,
            'v2_config_sha256':digest(output/'v2.json'), 'prompt_sha256':digest(output/'prompt.txt'),
            'work_instructions_sha256':digest(work/'AGENTS.md'), 'client_version':None,
            'command': cmd, 'trace_byte_limit': MAX_TRACE_BYTES, 'dry_run': args.dry_run,
            'scope': 'Codex-only fixed-layout physical rebuild; no other clients, efficiency or generalization claim'}
    write(output / 'evaluation-config.json', meta)
    return output, meta


# Executed only by the host after the client exits, with installed code first.
VERIFY_SCRIPT = ('import math\n'+inspect.getsource(recipe_equal)+'\n'+inspect.getsource(validate_recipe_contract)+'\n'+inspect.getsource(require_source_coverage)+'\n') + r'''
import sys,json
from pathlib import Path
package,state,case_path,asset_lock,recipe_path=sys.argv[1:]
sys.path.insert(0,str(Path(package)/'server/vendor'))
from simscene.verification.case_runner import evaluate
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_evidence
from simscene.cache import AssetCache
from simscene.preparation.profiles import validate_parameters
recipe=json.loads(Path(recipe_path).read_text());case=json.loads(Path(case_path).read_text())
role=recipe['asset_roles']['notebook'];role['parameters']=validate_parameters(role['profile_id'],role['parameters'])
state=Path(state);locked=json.loads(Path(asset_lock).read_text())['assets'];out=[]
for root in sorted((state/'runs').glob('*')):
 if not root.is_dir():continue
 item={'run_id':root.name}
 try:
  lock=json.loads((root/'run-lock.json').read_text());item['job_id']=lock['job_id']
  exit_record=json.loads((root/'process-exit.json').read_text());item['process_exit']=exit_record
  item['input_integrity']=verify_inputs(root);item['evidence_integrity']=verify_evidence(root)
  item['physical_verification']=evaluate(root,case_path=case_path,case_type='rigid_asset_smoke')
  spec=json.loads((root/'spec.json').read_text());assets=json.loads((root/'asset-lock.json').read_text());source_checks={};manifests={}
  for name,obj in spec['objects'].items():
   if obj.get('kind')!='asset':continue
   if obj.get('asset_binding'):
    manifest=json.loads(Path(obj['asset_binding']['manifest_path']).read_text())
    manifest['parameters']=validate_parameters(manifest['profile_id'],manifest['parameters']);manifests[name]=manifest
    acquired=json.loads((Path(obj['asset_binding']['manifest_path']).parent/'source/acquired.json').read_text())
    source_checks[name]=AssetCache.content_identity(acquired['files'])==locked['notebook']['content_sha256']
   elif name=='workbench':
    record=assets[name];selected=locked['workbench']['selected_member'];parts=Path(record['root_relative_to_run']).parts
    expected=root/parts[0]/parts[1]/selected['path']
    source_checks[name]=(AssetCache.content_identity(record['snapshot_files'])==locked['workbench']['content_sha256']
      and Path(obj['asset_path']).resolve()==expected.resolve())
   else:source_checks[name]=False
  item['source_content_checks']=source_checks
  item['required_source_objects_present']=require_source_coverage(case,source_checks)
  item['recipe_contract']=validate_recipe_contract(recipe,spec,case,manifests)
  item['passed']=(exit_record.get('exit_code')==0 and item['input_integrity']['passed'] and item['evidence_integrity']['passed']
    and item['evidence_integrity'].get('partial') is False and item['physical_verification']['passed'] and item['required_source_objects_present'] and all(source_checks.values()))
 except Exception as error:item.update(passed=False,error=str(error))
 out.append(item)
print(json.dumps({'runs':out}))
'''


def evaluate_output(output, completion, verifier=None, *, result_filename='evaluation-result.json'):
    output = Path(output); meta = read(output / 'evaluation-config.json'); work = output / 'work'
    if not isinstance(result_filename,str) or Path(result_filename).name!=result_filename or result_filename in ('.','..') or '\\' in result_filename:
        raise ValueError('result_filename must be a single new filename')
    result_path=output/result_filename
    if result_path.exists():raise ValueError('evaluation result already exists; choose a new result_filename for reassessment')
    original=output/'evaluation-result.json'
    reassessment=None
    if result_filename!='evaluation-result.json' and original.is_file():
        reassessment={'original_result_file':original.name,'original_result_sha256':digest(original),
                      'reason':'explicit reassessment of preserved trace and business evidence; no model or physics rerun',
                      'evaluated_unix_ns':time.time_ns()}
    evaluator_sha256=digest(Path(__file__).resolve())
    trace_sha256=digest(output/'events.jsonl')
    trace = analyze_trace(output / 'events.jsonl',work)
    try:
        from experiments.pilot_usage import collect
    except ModuleNotFoundError:
        from pilot_usage import collect
    try:
        usage = collect(output / 'events.jsonl')
    except (ValueError, KeyError, TypeError) as error:
        usage = {'usage_availability': 'unknown', 'aggregate_reported_usage': None, 'error': str(error)}
    errors = []
    if hashes(work / 'task') != meta['task_files'] or hashes(Path(meta['package'])) != meta['package_files']:
        errors.append('frozen task/package inputs changed')
    if any(digest(output/name)!=meta[key] for name,key in [('v2.json','v2_config_sha256'),('prompt.txt','prompt_sha256'),('work/AGENTS.md','work_instructions_sha256')]):
        errors.append('evaluation configuration or instructions changed')
    if hashes(work / '.agents/skills') != meta['copied_skills']:
        errors.append('copied installed skills changed')
    if (not trace['required_new_tools_called'] or trace['invalid_lines'] or trace['scope_violations']
            or not trace['legacy_compatibility_tools_called'] or not {'abo-glb','nvidia-usd-search'}<=set(trace['explicit_sources_searched'])):
        errors.append('required trace/scope checks failed')
    if not 1 <= trace['simulation_attempts'] <= 2:
        errors.append('expected one or two traced simulation attempts')
    preparations=[];prepared_hashes=set()
    for path in sorted((output/'state/preparation_jobs').glob('prep-*/job.json')):
        try:
            record=read(path);preparations.append(record)
        except (OSError,ValueError) as error:
            errors.append('unreadable preparation record: '+str(error))
    prepared_jobs={tool_payload(c).get('job_id') for c in trace['calls'] if c['successful'] and c['tool']=='asset_prepare' and isinstance(tool_payload(c),dict)}
    for record in preparations:
        if record.get('job_id') in prepared_jobs and record.get('state')=='completed':
            value=record.get('result',{}).get('manifest_sha256')
            if value:prepared_hashes.add(value)
    observed_prepared_hashes=set()
    for call in trace['calls']:
        payload = tool_payload(call)
        if call['successful'] and call['tool'] == 'job_status' and isinstance(payload, dict):
            result = payload.get('result', {})
            if payload.get('state') == 'completed' and isinstance(result, dict) and result.get('manifest_sha256'):
                observed_prepared_hashes.add(result['manifest_sha256'])
    prepared_hashes &= observed_prepared_hashes
    task = read(work / 'task' / member(meta['task_definition']))
    for field in TASK_FIELDS:member(task[field])
    try:
        case_path = work / 'submission-case.json'
        validate_case(read(work / 'task' / task['case_template_file']), read(case_path), prepared_hashes)
        submission = read(work / 'submission.json')
        if not isinstance(submission.get('attempted_simulation_job_ids'), list) or not submission['attempted_simulation_job_ids']:
            raise ValueError('submission requires every attempted simulation job ID')
        if verifier is None:
            process = subprocess.run([sys.executable, '-c', VERIFY_SCRIPT, meta['package'], str(output / 'state'),
                                      str(case_path), str(work / 'task' / task['asset_lock_file']),str(work/'task'/task['recipe_file'])],
                                     capture_output=True, text=True, timeout=120,
                                     env=dict(os.environ, **meta['mcp_environment']))
            if process.returncode:
                raise ValueError('installed verifier failed: ' + process.stderr[-2000:])
            verified = json.loads(process.stdout)
        else:
            verified = verifier(output, case_path)
        if any(not run.get('job_id') for run in verified['runs']):errors.append('unidentified persisted run attempt')
        actual_ids = {run.get('job_id') for run in verified['runs'] if run.get('job_id')}
        traced_ids = {tool_payload(c).get('job_id') for c in trace['calls'] if c['successful'] and c['tool'] == 'simulation_start' and isinstance(tool_payload(c), dict)}
        if actual_ids != set(submission['attempted_simulation_job_ids']) or actual_ids != traced_ids:
            errors.append('submitted/traced/persisted attempt IDs differ')
        if not actual_ids or len(actual_ids) > 2 or not any(run.get('passed') is True for run in verified['runs']):
            errors.append('no independently verified passing run within attempt budget')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        errors.append(str(error)); verified = {'runs': []}
    passed = (not errors and completion.get('exit_code') == 0 and not completion.get('timed_out')
              and not completion.get('trace_budget_exceeded'))
    receipts=[]
    for folder in sorted((output/'state/runs').glob('*')):
        if not folder.is_dir():continue
        receipt={'run_id':folder.name,'process_exit':None,'status':'unknown_without_exit_record'}
        for name in ('job.json','run-lock.json','process-exit.json'):
            try:
                record=read(folder/name)
                if name=='process-exit.json':receipt.update(process_exit=record,status='exit_recorded')
                else:receipt['job_id']=record.get('job_id',receipt.get('job_id'))
            except (OSError,ValueError,TypeError) as error:receipt.setdefault('read_errors',{})[name]=str(error)
        receipts.append(receipt)
    result = {'schema': 'simscene.catalog_agent_eval_result.v1', 'passed': passed,
              'evaluator_sha256':evaluator_sha256,'trace_sha256':trace_sha256,'reassessment':reassessment,
              'completion': completion, 'model': meta['model'], 'reasoning_effort': meta['reasoning_effort'],
              'cache_condition': meta['cache_condition'], 'trace': trace, 'usage': usage,
              'business_verification': verified, 'persisted_run_receipts':receipts, 'preparation_records':preparations, 'errors': errors, 'claims': meta['scope']}
    with result_path.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    return result


def run(output, meta):
    output=Path(output);started=time.monotonic();process=None
    completion={'exit_code':None,'timed_out':False,'trace_budget_exceeded':False}
    environment=dict(os.environ,**meta['mcp_environment']);environment.pop('PYTHONPATH',None)
    meta['started_unix_ns']=time.time_ns()
    with (output/'events.jsonl').open('x') as stdout,(output/'stderr.log').open('x') as stderr:
        try:
            meta['client_version']=subprocess.run(['codex','--version'],capture_output=True,text=True,timeout=10,check=True).stdout.strip()
            write(output/'evaluation-config.json',meta)
            process=subprocess.Popen(meta['command'],stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,
                text=True,cwd=output/'work',env=environment,start_new_session=True)
            process.stdin.write((output/'prompt.txt').read_text());process.stdin.close()
            while process.poll() is None:
                completion['timed_out']=time.monotonic()-started>meta['wall_limit_s']
                completion['trace_budget_exceeded']=(output/'events.jsonl').stat().st_size>MAX_TRACE_BYTES
                if completion['timed_out'] or completion['trace_budget_exceeded']:break
                time.sleep(.2)
        except (OSError,subprocess.SubprocessError) as error:
            completion['launch_error']=str(error)
        finally:
            if process is not None:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                completion['exit_code']=process.wait()
    completion.update(wall_s=time.monotonic()-started,usage_source='actual CLI JSONL; missing counters remain unknown')
    write(output/'completion.json',completion)
    return evaluate_output(output,completion)


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--client', choices=['codex'], default='codex')
    for name in ('package', 'case', 'output', 'model'):
        value.add_argument('--' + name, required=True)
    value.add_argument('--reasoning-effort', choices=['low', 'medium', 'high', 'xhigh'], default='medium')
    value.add_argument('--wall-limit-s', type=int, default=900)
    value.add_argument('--cache-root'); value.add_argument('--v2-config')
    value.add_argument('--cache-condition', choices=['cold', 'warm', 'unknown'], default='unknown')
    value.add_argument('--dry-run', action='store_true')
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    if not 1 <= args.wall_limit_s <= 7200:
        raise ValueError('wall-limit-s must be between 1 and 7200')
    output, meta = prepare(args)
    if args.dry_run:
        print(json.dumps({'output': str(output), 'status': 'prepared_not_executed'})); return 0
    result = run(output, meta)
    print(json.dumps({'output': str(output), 'passed': result['passed']}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
