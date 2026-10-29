import unittest
from simscene.verification.settling import stable
class SettlingTest(unittest.TestCase):
    def test_checks_translation_and_rotation_speeds(self):
        def sample(t,p,q):return {'simulation_time_s':t,'positions':{'/part':p},'orientations_wxyz':{'/part':q}}
        steady=[sample(i/10,[.001 if i else 0,0,0],[1,0,0,0]) for i in range(11)]
        self.assertTrue(stable(steady,'/part',1,1,.05,.5))
        steady[-1]['orientations_wxyz']['/part']=[.707,0,.707,0]
        self.assertFalse(stable(steady,'/part',1,1,.05,.5))
        steady[-1]['orientations_wxyz']['/part']=[1,0,0,0];steady[-1]['positions']['/part']=[1,0,0]
        self.assertFalse(stable(steady,'/part',1,1,.05,.5))
    def test_incomplete_data_cannot_establish_stability(self):
        self.assertFalse(stable([], '/part',1,1,.05,.5))
        frames=[{'simulation_time_s':i/10,'positions':{'/part':[0,0,0]},'orientations_wxyz':{'/part':[1,0,0,0]}} for i in range(11)]
        frames[5]['orientations_wxyz'].clear()
        self.assertFalse(stable(frames,'/part',1,1,.05,.5))
