"""The drawer control must differ only in its lower drive and fail closed."""
import copy
import json
from pathlib import Path
import pytest

from simscene.verification import drawer_payload_pair as pair


def scene(commands):
    return {'scene_id':'positive', 'revision':1, 'world':{'units':'m'},
            'objects':{'cabinet':{'kind':'asset','mechanism':{'commands':commands}},
                       'box':{'kind':'asset','dynamic':True,'position':[0,0,.2]}}}


def test_control_must_remove_all_and_only_lower_drive_commands():
    commands=[{'joint_id':'joint0','target_position':0.}, {'joint_id':'joint1','target_position':0.},
              {'joint_id':'joint1','target_position':.35}, {'joint_id':'joint0','target_position':.25}]
    positive=scene(commands)
    control=scene([c for c in commands if c['joint_id']!='joint0'])
    control['scene_id']='negative'
    assert pair.only_lower_drive_removed(positive,control,commands,'/run/a','/run/b')
    altered=copy.deepcopy(control);altered['objects']['box']['position'][0]=1
    assert not pair.only_lower_drive_removed(positive,altered,commands,'/run/a','/run/b')
    altered=copy.deepcopy(control);altered['objects']['cabinet']['mechanism']['commands'].pop()
    assert not pair.only_lower_drive_removed(positive,altered,commands,'/run/a','/run/b')


def test_payload_corners_are_checked_in_rotated_drawer_coordinates():
    # A two-metre-wide payload rotated by 90 degrees is two metres long in Y.
    half=2**-.5
    corners=pair.payload_corners_local([0,0,0],[half,0,0,half],
        [0,0,0],[1,0,0,0],{'min':[-1,-.1,-.1],'max':[1,.1,.1]})
    assert max(abs(point[1]) for point in corners)>0.99
    assert not pair.corners_within(corners,{'min':[-.2,-.5,-.2],'max':[.2,.5,.2]})
    assert pair.corners_within(corners,{'min':[-.2,-1.1,-.2],'max':[.2,1.1,.2]})


def test_missing_runs_never_pass(tmp_path):
    result=pair.verify_pair(tmp_path/'positive',tmp_path/'negative')
    assert result['passed'] is False
    assert result['errors']


def test_public_example_has_only_the_documented_intervention_and_no_local_paths():
    root=Path(__file__).resolve().parents[1]/'examples/integration_workspace'
    positive=json.loads((root/'recipe.json').read_text())
    control=json.loads((root/'recipe-control.json').read_text())
    for value in (positive,control,json.loads((root/'assets.lock.json').read_text())):
        assert '/data/' not in json.dumps(value) and '/home/' not in json.dumps(value)
    def spec(recipe):
        return {'objects':{op['id']:op['object'] for op in recipe['operations'] if op['op']=='add'}}
    ps,cs=spec(positive),spec(control)
    commands=ps['objects']['cabinet']['mechanism']['commands']
    assert pair.only_lower_drive_removed(ps,cs,commands,'/run/positive','/run/control')


def test_incomplete_trajectory_cannot_be_accepted():
    case={'steps':600,'seed':42,'physics_device':'cpu','physics_dt_s':1/60}
    partial={'actual_physics_steps':600,'requested_physics_steps':600,'partial':False,
             'samples_truncated':False,'observation_interval_steps':1,
             'initial_observation':{},'samples':[]}
    with pytest.raises(ValueError,match='complete per-step'):
        pair._metrics(partial,case,True)


def test_static_contact_cannot_prove_contact_during_drawer_motion():
    frames=[{'native_joint_positions':{'/joint':q},'contact_pairs':[{'actor_paths':['/box','/drawer'],'count':1}]}
            for q in (0.,0.,.01)]
    assert pair.moving_contact_steps(frames,'/box','/drawer','/joint',[1,1]) == []
    assert pair.moving_contact_steps(frames,'/box','/drawer','/joint',[1,2]) == [2]


def test_hold_window_cannot_be_outside_its_driven_phase():
    def command(joint,step,target):
        return {'joint_id':joint,'trigger':{'type':'at_step','physics_step':step},'target_position':target,
                'position_unit':'m','stiffness':2000.,'damping':100.,'max_effort':400.}
    case={'schema':'simscene.drawer_payload_pair.v1','steps':600,'seed':42,'physics_device':'cpu',
          'physics_dt_s':1/60,'windows':{'reference_step':209,'upper_hold':[130,149],
            'lower_hold':[270,359],'lower_motion':[210,359],'final':[540,600]},
          'thresholds':{'target_error_m':.01,'control_displacement_m':.005,'relative_drift_m':.02,
            'final_joint_error_m':.01,'table_drift_m':.002,'tilt_deg':10.,'joint_reconstruction_error_m':.001,
            'min_drawer_travel_m':.2,'min_payload_fraction':.8},
          'payload_collider_bounds_local':{'min':[-.1,-.1,0.],'max':[.1,.1,.1]},
          'support_bounds_local':{'min':[-.4,0.,-.2],'max':[.4,.4,.2]},
          'allowed_bottom_z_local':[-.155,-.14],
          'positive_commands':[command('joint0',0,0.),command('joint1',0,0.),command('joint1',60,.35),
            command('joint1',150,0.),command('joint0',210,.25),command('joint0',360,0.)],
          'bindings':{k:{'manifest_sha256':'a'*64,'source_ref':{'source_id':k}} for k in ('cabinet','box','book_a','book_b')}}
    pair._validate_case(case)
    case['windows']['upper_hold']=[160,170]
    with pytest.raises(ValueError,match='window'):
        pair._validate_case(case)
