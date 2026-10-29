"""Derive a display state from an actual controller's observed phase."""

def state(sequence,index,error):
    if error:return 'error'
    if not sequence:return 'fixed_target'
    if type(index) is not int or not 0<=index<=len(sequence):return 'unknown'
    if index==len(sequence):return 'complete'
    phase=sequence[index]
    if not isinstance(phase,dict):return 'unknown'
    return 'waiting' if phase.get('type')=='wait_object' else 'active'


COLORS={'error':(1.,.03,.02),'waiting':(1.,.55,.02),'active':(.04,1.,.08),
        'complete':(.1,.3,1.),'fixed_target':(.1,.3,1.),'unknown':(.2,.2,.2)}
