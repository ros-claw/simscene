"""Static source reviews never become implicit acquisition/physics admission."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from simscene.catalog.audit import audit_source, build_source_list
from simscene.catalog.registry import Registry, load_registry, validate_source

SHA = 'c7c8293fed3b7ab122ef5d7896521a187e0962d7'


def candidate(**changes):
    return dict({'schema_version': 1, 'repository': 'codepawl/abo-glb', 'revision': SHA,
                 'state': 'candidate', 'default_enabled': False,
                 'access': {'visibility': 'public', 'gated': False, 'credentials_required': False},
                 'license': {'status': 'declared', 'declarations': ['cc-by-4.0']},
                 'formats': ['glb'], 'metadata_layout': {'status': 'recognized_schema_prefix', 'adapter': 'abo',
                                                      'object_index': 'metadata.jsonl', 'complete_index_inspected': False},
                 'acquisition_granularity': 'single_file', 'granularity_evidence': 'inspected schema prefix',
                 'dependencies': {'status': 'unknown'}, 'physics': {'evidence': 'unknown', 'runtime_validation': 'not_run'},
                 'examples': {'locally_executed': 0, 'upstream_reported': None}, 'unique_object_count': None}, **changes)


class CatalogAuditTest(unittest.TestCase):
    def test_known_adapter_configuration_is_candidate_only_and_audit_is_read_only(self):
        source = candidate(); before = deepcopy(source)
        registry_before = load_registry().to_dict()
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')), patch('subprocess.Popen', side_effect=AssertionError('SDK forbidden')):
            audit = audit_source(source)
        self.assertEqual(source, before)
        self.assertEqual(load_registry().to_dict(), registry_before)
        config = validate_source(audit.candidate_configuration)
        self.assertEqual(config.state, 'candidate')
        self.assertFalse(config.default_enabled)
        self.assertEqual(config.metadata_entries[0].revision, SHA)
        self.assertTrue(all(record['runtime_validation'] == 'not_run' for record in config.evidence))
        self.assertEqual(audit.categories['dependencies']['status'], 'unknown')
        self.assertIsNone(audit.categories['unique_object_count'])
        self.assertEqual(audit.categories['existing_examples']['locally_executed_by_this_audit'], 0)

    def test_license_conflict_nc_gating_layout_and_unknown_granularity_are_independent(self):
        source = candidate(repository='org/unsupported',
                           access={'visibility': 'private', 'gated': True, 'credentials_required': True},
                           license={'status': 'declared', 'declarations': ['cc-by-4.0', 'cc-by-nc-4.0']},
                           metadata_layout={'status': 'unsupported_metadata_layout', 'object_index': None},
                           acquisition_granularity=None)
        audit = audit_source(source, {'usage_policy': 'commercial'})
        self.assertIsNone(audit.candidate_configuration)
        self.assertEqual(audit.status, 'unsupported_metadata_layout')
        for reason in ('license_conflicting', 'license_commercial_use_unresolved', 'source_gated_no_automatic_terms_acceptance',
                       'source_access_requires_review', 'unsupported_metadata_layout', 'acquisition_granularity_unknown'):
            self.assertIn(reason, audit.blocking_reasons)
        self.assertEqual(audit.categories['license']['status'], 'conflicting')
        self.assertIsNone(audit.categories['acquisition_granularity']['value'])

    def test_new_registered_metadata_adapters_remain_disabled_static_candidates(self):
        registry = load_registry()
        sources = [source for source in registry.sources if source.adapter in {'hf_manifest', 'usdcraft'}]
        for source in sources:
            with self.subTest(source=source.source_id):
                record = candidate(repository=source.repository, revision=source.metadata_entries[0].revision,
                                   license={'status': 'declared', 'declarations': [source.license_policy['license'].lower()]},
                                   acquisition_granularity=source.acquisition_granularity,
                                   metadata_layout={'status': 'recognized_registered_layout', 'adapter': source.adapter,
                                                    'object_index': source.metadata_entries[0].path})
                result = audit_source(record)
                config = validate_source(result.candidate_configuration)
                self.assertEqual(config.source_id, source.source_id)
                self.assertEqual(config.state, 'candidate')
                self.assertFalse(config.default_enabled)
                self.assertTrue(all(entry['runtime_validation'] == 'not_run' for entry in config.evidence))

    def test_missing_sha_unknown_license_and_upstream_physics_never_become_local_verification(self):
        audit = audit_source(candidate(revision='main', license={'status': 'unknown', 'declarations': []},
                                       physics={'evidence': 'runtime_verified', 'runtime_validation': 'pass', 'origin': 'upstream benchmark'},
                                       examples={'upstream_reported': 5000, 'locally_executed': 999}))
        self.assertIsNone(audit.revision)
        self.assertIsNone(audit.candidate_configuration)
        self.assertIn('immutable_revision_required', audit.blocking_reasons)
        self.assertIn('license_unknown', audit.blocking_reasons)
        self.assertEqual(audit.categories['physics_declarations']['locally_executed'], 'not_run')
        self.assertEqual(audit.categories['physics_declarations']['evidence'], 'declared')
        self.assertFalse(audit.categories['physics_declarations']['locally_verified_by_this_audit'])
        self.assertEqual(audit.categories['existing_examples']['locally_executed_by_this_audit'], 0)
        self.assertIsNone(audit.categories['unique_object_count'])

    def test_known_source_cannot_hide_new_access_or_license_conflicts_in_candidate_config(self):
        for changes in ({'license': {'status': 'declared', 'declarations': ['mit']}},
                        {'license': {'status': 'conflicting', 'declarations': ['cc-by-4.0', 'mit']}},
                        {'access': {'visibility': 'public', 'gated': True, 'credentials_required': True}}):
            with self.subTest(changes=changes):
                result = audit_source(candidate(**changes))
                self.assertIsNone(result.candidate_configuration)
                self.assertTrue(result.blocking_reasons)

    def test_same_filename_or_new_revision_does_not_invent_an_adapter(self):
        other = audit_source(candidate(repository='someone/another-glb'))
        self.assertIsNone(other.candidate_configuration)
        self.assertIn('adapter_not_admitted', other.blocking_reasons)
        changed = audit_source(candidate(revision='b' * 40))
        self.assertIsNone(changed.candidate_configuration)
        self.assertIn('new_revision_requires_metadata_schema_audit', changed.blocking_reasons)
        with self.assertRaises(ValueError):
            audit_source(candidate(repository='org/../private'))

    def test_generated_sources_file_matches_registry_single_truth(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual((root / 'docs/assets/SOURCES.md').read_text(), build_source_list(load_registry()))
        registry = load_registry()
        changed = Registry(tuple(replace(source, checked_at='2099-01-01') for source in registry.sources))
        self.assertNotEqual(build_source_list(changed), build_source_list(registry))
        text = build_source_list(registry)
        for state in ('enabled', 'audited', 'candidate', 'quarantined', 'reference_only'):
            self.assertIn('**' + state + '**', text)
        self.assertIn('B01DN8TB5U', text)
        self.assertIn('unknown; per-asset review required', text)
        self.assertIn('not registered sources or prepared assets', text)

    def test_candidate_version_and_unknown_contract_values_fail_explicitly(self):
        for changes in ({'schema_version': True}, {'default_enabled': True}, {'state': 'enabled'},
                        {'formats': 'glb'}, {'license': {'status': 'runtime_verified', 'declarations': []}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                audit_source(candidate(**changes))
        with self.assertRaises(ValueError):
            audit_source(candidate(), 'commercial')

    def test_explicit_audit_snapshot_is_not_merged_into_production_registry(self):
        registry = load_registry(); before = registry.to_dict()
        audit = audit_source(candidate(repository='someone/another-glb'))
        rendered = build_source_list(registry, [audit])
        self.assertIn('Explicit candidate audit snapshot', rendered)
        self.assertIn('someone/another-glb', rendered)
        self.assertEqual(registry.to_dict(), before)
        self.assertEqual(len(registry.sources), len(before['sources']))


if __name__ == '__main__':
    unittest.main()
