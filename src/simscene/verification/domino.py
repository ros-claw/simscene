"""Check observed domino tip-over and contact, independently of scene spec."""
import math

def evaluate(run,case):
    samples=run.get('samples',[]); contacts=run.get('contact_counts',{})
    def vertical_cos(q):
        if not isinstance(q,list) or len(q)!=4 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in q) or abs(sum(v*v for v in q)-1)>.01:return None
        w,x,y,z=q
        return 1-2*(x*x+y*y)
    outcomes={}
    for name in case['tiles']:
        path='/World/'+name
        values=[vertical_cos(s.get('orientations_wxyz',{}).get(path)) for s in samples]
        values=[v for v in values if v is not None]
        outcomes[name]={'observed':bool(values),'initial_cos':values[0] if values else None,
                        'final_cos':values[-1] if values else None,
                        'tipped':bool(values and values[-1]<=case['final_vertical_cos_max'])}
    links={}
    for first,second in zip(case['tiles'],case['tiles'][1:]):
        key=first+'|/World/'+second+'|'
        links[first+'->'+second]=any(k.startswith(key) and v.get('count',0)>0 for k,v in contacts.items())
    # All tiles except the deliberately tilted trigger must initially be upright.
    checks={'completed_requested_duration':run.get('actual_physics_steps')==run.get('requested_physics_steps') and run.get('actual_physics_steps',0)>0,
            'others_initially_upright':all(outcomes[n]['initial_cos'] is not None and outcomes[n]['initial_cos']>=case['initial_vertical_cos_min'] for n in case['tiles'][1:]),
            'all_tipped':bool(outcomes) and all(o['tipped'] for o in outcomes.values()),
            'adjacent_contacts_observed':bool(links) and all(links.values()),
            'contacts_not_truncated':run.get('contacts_truncated') is False}
    return {'checks':checks,'tiles':outcomes,'adjacent_contacts':links,'passed':all(checks.values()),
            'scope':'one exploratory gravity-driven domino chain; no general robustness or agent-client claim'}
