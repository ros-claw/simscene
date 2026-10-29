import unittest
from simscene.verification.ledger import evaluate

class LedgerTests(unittest.TestCase):
    def test_observed_evidence_and_counts(self):
        observations = [
            {'id':'a','class':'red','state':'correct','contained_in':'red_bin','released':True,'grasp_observed':True,'stable_s':2},
            {'id':'b','class':'red','state':'correct','contained_in':'blue_bin','released':True,'grasp_observed':True,'stable_s':2},
            {'id':'c','class':'red','state':'correct','contained_in':'red_bin','released':True,'stable_s':2},
            {'id':'d','class':'red','state':'pending'}]
        result = evaluate(observations, {'red':'red_bin'}, 1)
        self.assertEqual([result[k] for k in ('generated','correct','wrong_bin','failed','pending')], [4,1,1,1,1])
        self.assertEqual(result['success_rate'], .25)

    def test_duplicate_and_missing_stability_fail(self):
        item = {'id':'a','class':'red','state':'correct','contained_in':'red_bin','released':True,'grasp_observed':True}
        self.assertEqual(evaluate([item], {'red':'red_bin'}, 1)['failed'], 1)
        with self.assertRaises(ValueError): evaluate([item,item], {'red':'red_bin'}, 1)
