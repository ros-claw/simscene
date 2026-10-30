"""Verify repeatability, intervention controls and a declared layout edit.

Manifest paths are ordinary data, not scene-name branches. This evaluator does
not construct scenes or infer an acceptance case from successful outcomes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.passive_chain_check import evaluate
from simscene.run_integrity import verify as inputs
from simscene.evidence_integrity import verify as outputs


def physical_objects(spec):
    result={}
    for name,obj in spec['objects'].items():
        if obj['kind'] in ('camera','light','counter'):continue
        value={k:v for k,v in obj.items() if k not in ('material','color','indicator','asset_lights','intensity','light')}
        if obj['kind']=='asset':
            identity=spec.get('_checker_asset_identities',{}).get(name)
            if not identity:raise ValueError('asset identity missing from verified lock: '+name)
            value['asset_path']=identity
        result[name]=value
    return result


def verify_entry(entry):
    root=Path(entry['run']).resolve();case_path=Path(entry['case']).resolve()
    run=json.loads((root/'result.json').read_text());spec=json.loads((root/'spec.json').read_text());case=json.loads(case_path.read_text());lock=json.loads((root/'run-lock.json').read_text())
    asset_lock=json.loads((root/'asset-lock.json').read_text())
    spec['_checker_asset_identities']={name:{k:v for k,v in value.items() if k not in ('runtime_provided_dependencies',)} for name,value in asset_lock.items()}
    report=evaluate(run,spec,case,entry.get('mode','positive'),entry.get('removed_id'))
    integrity={'inputs':inputs(root),'outputs':outputs(root)}
    pinned=lock.get('acceptance_case_sha256')==hashlib.sha256(case_path.read_bytes()).hexdigest()
    report.update({'run_id':root.name,'case_pinned_to_run':pinned,'integrity':integrity})
    report['passed']=bool(report['passed'] and pinned and all(x['passed'] for x in integrity.values()) and not integrity['outputs']['partial'])
    return report,spec,case,lock


def evaluate_suite(manifest):
    positives=manifest['positive_runs'];negatives=manifest['negative_runs'];edit=manifest['edit']
    checks={'three_repetitions':len(positives)>=3,'paired_negative_modes':{n['mode'] for n in negatives}=={'no_trigger','broken_link'}}
    records=[verify_entry(e) for e in positives];controls=[verify_entry(e) for e in negatives];edited=verify_entry(edit)
    reports={'positive':[x[0] for x in records],'negative':[x[0] for x in controls],'edit':edited[0]}
    checks['all_physical_checks']=all(r['passed'] for group in (reports['positive'],reports['negative'],[reports['edit']]) for r in group)
    base=physical_objects(records[0][1]);case=records[0][2]
    checks['same_repeat_configuration']=all(physical_objects(s)==base and c==case for _,s,c,l in records)
    ids=[l['run_id'] for _,s,c,l in records+controls+[edited]]
    checks['same_frozen_worker']=all(l.get('worker_code_sha256')==records[0][3].get('worker_code_sha256') and l.get('runtime_version')==records[0][3].get('runtime_version') for _,s,c,l in records+controls+[edited])
    checks['distinct_fresh_runs']=len(set(ids))==len(ids) and all(not l.get('resume_from') for _,s,c,l in records+controls+[edited])
    checks['controls_change_only_one_body']=all(physical_objects(s)=={k:v for k,v in base.items() if k != (case['trigger_id'] if e['mode']=='no_trigger' else e['removed_id'])} and c==case for e,(_,s,c,l) in zip(negatives,controls))
    edited_objects=physical_objects(edited[1]);mid=edit['middle_support_id'];receiver=edit['receiver_id']
    def changed_by(name,delta):
        a=base.get(name,{}).get('position');b=edited_objects.get(name,{}).get('position')
        return isinstance(a,list) and isinstance(b,list) and all(abs(b[i]-a[i]-delta[i])<1e-6 for i in range(3))
    checks['requested_edit_measured']=bool(changed_by(mid,[0,0,.15]) and changed_by(receiver,[.20,0,0]))
    checks['same_contact_network_after_edit']=edited[2]['bodies']==case['bodies'] and edited[2]['edges']==case['edges'] and edited[2]['trigger_id']==case['trigger_id']
    checks['receiver_acceptance_region_translated']=all(abs(edited[2]['receiver'][key][i]-case['receiver'][key][i]-(.20 if i==0 else 0))<1e-6 for key in ('min','max') for i in range(3))
    checks['no_added_actuation_after_edit']=edited[0]['checks']['no_active_drives']
    return {'passed':all(checks.values()),'checks':checks,'runs':reports,'scope':'Three fresh initializations of one designed configuration, paired single-body removal controls, and the declared support/receiver edit; not randomized-layout generalization or cross-machine verification.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest');p.add_argument('--output',required=True);a=p.parse_args()
    result=evaluate_suite(json.loads(Path(a.manifest).read_text()));Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps({'passed':result['passed'],'checks':result['checks']}));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
