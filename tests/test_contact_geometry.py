import unittest
from types import SimpleNamespace
from simscene.worker.contact_geometry import minimum_separation

class ContactGeometryTest(unittest.TestCase):
    def test_minimum_of_reported_contact_points_and_incomplete_input(self):
        points=[SimpleNamespace(separation=x) for x in (.02,-.003,-.001)]
        self.assertEqual(minimum_separation(SimpleNamespace(contact_data_offset=1,num_contact_data=2),points),(-.003,False))
        self.assertEqual(minimum_separation(SimpleNamespace(contact_data_offset=1,num_contact_data=0),points),(None,False))
        self.assertEqual(minimum_separation(SimpleNamespace(contact_data_offset=2,num_contact_data=2),points),(None,True))
        points[-1].separation=float('nan')
        self.assertEqual(minimum_separation(SimpleNamespace(contact_data_offset=1,num_contact_data=2),points),(None,True))
