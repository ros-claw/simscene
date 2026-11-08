"""The v2 observer changes only its explicit schema and reader identity."""
from pathlib import Path
import unittest

from experiments import box_halfspace_observation as old
from experiments import box_halfspace_observation_v2 as new


class ObserverVersionIdentityTest(unittest.TestCase):
    def test_every_geometry_integrity_and_cli_predicate_is_byte_identical(self):
        expected = Path(old.__file__).read_text().replace(
            "SCHEMA='simscene.box_halfspace_observation.v1'",
            "SCHEMA='simscene.box_halfspace_observation.v2'").replace(
            old.DEPENDENCIES['passive_network'], new.DEPENDENCIES['passive_network'])
        self.assertEqual(Path(new.__file__).read_text(), expected)
        self.assertNotEqual(old.DEPENDENCIES['passive_network'], new.DEPENDENCIES['passive_network'])
        self.assertEqual(new.sha(new.p.__file__),new.DEPENDENCIES['passive_network'])

