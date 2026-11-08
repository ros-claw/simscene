"""Synthetic CPU provenance counterexamples; no simulation success evidence."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from simscene.jobs import _snapshot_cached_assets
from simscene.run_integrity import verify as inputs
from simscene.evidence_integrity import seal
from simscene.snapshot_integrity import PIN_FIELDS, pin_snapshot, comparison_identity
from simscene.verification import passive_network as p, mechanism as m, mechanism_adapter as adapter
from simscene.verification import case_runner
from test_passive_network import fixture, wrapped_fixture, seal_fixture
from test_mechanism_check import fixture as rope_fixture, detach, seal_fixture as seal_rope


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value))


def cache(root, source='https://example.invalid/synthetic.usda'):
    package = root/'cache'/('d'*64)
    package.mkdir(parents=True)
    (package/'model.usda').write_text('#usda 1.0\n')
    (package/'other.usda').write_text('#usda 1.0\n')
    (package/'texture.bin').write_bytes(b'synthetic texture bytes')
    meta = {'source': source, 'package_sha256': package.name, 'root': str(package/'model.usda'),
            'dependency_status': 'resolved_locally', 'unresolved_dependencies': [], 'license': 'synthetic-test'}
    dump(package/'simscene-lock.json', meta)
    rehash_package(package)
    return package


def rehash_package(package):
    metadata = json.loads((package/'simscene-lock.json').read_text())
    metadata['files'] = [{'path': f.relative_to(package).as_posix(), 'size': f.stat().st_size, 'sha256': sha(f)}
                         for f in sorted(package.rglob('*')) if f.is_file() and f.name != 'simscene-lock.json']
    dump(package/'simscene-lock.json', metadata)


def relock(root, assets=None, repin=False):
    if assets is None:
        assets = json.loads((root/'asset-lock.json').read_text())
    if repin:
        for record in assets.values():
            package = root.joinpath(*Path(record['root_relative_to_run']).parts[:2])
            launcher = json.loads((root/'run-lock.json').read_text())['runtime_python']
            record.update(pin_snapshot(package, launcher, record.get('runtime_provided_dependencies', {})))
    dump(root/'asset-lock.json', assets)
    lock = json.loads((root/'run-lock.json').read_text())
    lock['asset_lock_sha256'] = sha(root/'asset-lock.json')
    lock['spec_sha256'] = sha(root/'spec.json')
    dump(root/'run-lock.json', lock)
    seal(root)


def make_pair(root, nested=False, standalone=False):
    package = cache(root)
    positive, control = root/'positive', root/'control'
    for directory, mode in ((positive, 'positive'), (control, 'broken_rope')):
        directory.mkdir()
        if standalone:
            run, spec, case = rope_fixture()
            if mode != 'positive':
                detach(run, spec, case)
        else:
            run, spec, case, _ = (wrapped_fixture if nested else fixture)(mode)
        spec['objects']['visual'] = {'kind': 'asset', 'asset_path': str(package/'model.usda'),
                                      'asset_physics': 'visual_only', 'rigid_attachment': {'body': 'drawer'},
                                      'position': [0, 0, 0], 'material_variant': 'original'}
        records = _snapshot_cached_assets(spec, directory)
        (seal_rope if standalone else seal_fixture)(directory, run, spec, case, None if mode == 'positive' else positive/'python.sh')
        relock(directory, records)
    return positive, control


class AssetSnapshotComparisonTest(unittest.TestCase):
    def test_only_sealed_equivalent_paths_are_normalized_including_embedded_ce05(self):
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp), nested=nested)
                raw_spec = json.loads((control/'spec.json').read_text())
                raw_ref = json.loads((positive/'spec.json').read_text())
                run = json.loads((control/'result.json').read_text())
                case = json.loads((control/'acceptance-case.json').read_text())
                self.assertFalse(p.evaluate(run, raw_spec, case, 'broken_rope', raw_ref)['passed'])
                before = {f: sha(control/f) for f in ('spec.json', 'result.json', 'asset-lock.json')}
                report = p.verify_run(control, mode='broken_rope', reference_run=positive)
                self.assertTrue(report['passed'], report)
                self.assertTrue(report['paired_asset_snapshots']['mappings']['visual']['relocated'])
                if nested:
                    self.assertTrue(report['mechanism_cases']['wrapped_cable']['report']['passed'])
                self.assertEqual(before, {f: sha(control/f) for f in before})
                self.assertEqual(run, json.loads((control/'result.json').read_text()))
                self.assertEqual(raw_ref, json.loads((positive/'spec.json').read_text()))

    def test_standalone_adapter_preserves_immutable_ce05_and_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            positive, control = make_pair(Path(tmp), standalone=True)
            self.assertFalse(m.verify_run(control, mode='detached_drawer', reference_run=positive)['passed'])
            report = case_runner.evaluate(control, mode='detached_drawer', reference_run=positive)
            self.assertTrue(report['passed'], report)
            self.assertTrue(report['paired_causal_acceptance'])
            self.assertEqual(report['reused_mechanism_sha256'], sha(m.__file__))
            self.assertEqual(sha(m.__file__), 'ce05b85cd11af946901f77249e6d16208434d5764056c5ba704a97beb4c9f4e8')

    def test_standalone_adapter_keeps_pinned_manifest_and_nonpath_guards(self):
        for variant in ('runtime_version', 'changed_material', 'wrong_case'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp), standalone=True)
                if variant == 'runtime_version':
                    lock = json.loads((control/'run-lock.json').read_text())
                    lock['runtime_version'] = 'different-but-validly-recorded'
                    dump(control/'run-lock.json', lock)
                    seal(control)
                elif variant == 'changed_material':
                    spec = json.loads((control/'spec.json').read_text())
                    spec['objects']['visual']['material_variant'] = 'changed'
                    dump(control/'spec.json', spec)
                    relock(control)
                else:
                    case = json.loads((control/'acceptance-case.json').read_text())
                    case['thresholds']['drawer_min_travel_m'] += .001
                    dump(control/'acceptance-case.json', case)
                    lock = json.loads((control/'run-lock.json').read_text())
                    lock['acceptance_case_sha256'] = sha(control/'acceptance-case.json')
                    dump(control/'run-lock.json', lock)
                    seal(control)
                report = adapter.verify_run(control, mode='detached_drawer', reference_run=positive)
                self.assertFalse(report['passed'])
                if variant == 'runtime_version':
                    self.assertEqual(set(report['paired_manifest_fields_match']), set(m.PAIRED_MANIFEST_FIELDS))
                    self.assertFalse(report['paired_runtime_configuration_matches'])
                elif variant == 'wrong_case':
                    self.assertFalse(report['same_frozen_case_as_reference'])
                else:
                    self.assertTrue(report['paired_asset_snapshots']['passed'])
                    self.assertFalse(report['checks']['only_drawer_end_joint_changed'])

    def test_no_assets_preserves_original_checks_and_old_p2_criteria(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            positive, control = root/'positive', root/'control'
            for directory, mode in ((positive, 'positive'), (control, 'broken_rope')):
                directory.mkdir()
                run, spec, case, _ = fixture(mode)
                seal_fixture(directory, run, spec, case, None if mode == 'positive' else positive/'python.sh')
            report = p.verify_run(control, mode='broken_rope', reference_run=positive)
            self.assertTrue(report['passed'])
            self.assertEqual(report['paired_asset_snapshots']['mappings'], {})

    def test_legacy_missing_proof_never_exempts_relocation(self):
        for removed in (PIN_FIELDS, {'snapshot_files'}):
            with self.subTest(removed=removed), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp))
                records = json.loads((control/'asset-lock.json').read_text())
                for key in removed:
                    records['visual'].pop(key)
                relock(control, records)
                report = p.verify_run(control, mode='broken_rope', reference_run=positive)
                self.assertFalse(report['passed'])
                if removed == PIN_FIELDS:
                    self.assertTrue(inputs(control)['passed'])
                    self.assertFalse(report['paired_asset_snapshots']['passed'])
                else:
                    self.assertFalse(inputs(control)['passed'])

    def test_changed_bytes_manifest_or_unlisted_files_fail_pinned_inputs(self):
        for mutation in ('bytes', 'manifest', 'extra', 'missing', 'symlink', 'duplicate', 'traversal'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp))
                records = json.loads((control/'asset-lock.json').read_text())
                package = control/'assets'/('d'*64)
                if mutation == 'bytes':
                    (package/'texture.bin').write_bytes(b'tampered')
                elif mutation == 'manifest':
                    metadata = json.loads((package/'simscene-lock.json').read_text())
                    metadata['license'] = 'changed'
                    dump(package/'simscene-lock.json', metadata)
                elif mutation == 'extra':
                    (package/'unlisted.usda').write_text('#usda 1.0\n')
                elif mutation == 'missing':
                    (package/'texture.bin').unlink()
                elif mutation == 'symlink':
                    (package/'texture.bin').unlink()
                    (package/'texture.bin').symlink_to(Path(tmp)/'cache'/('d'*64)/'texture.bin')
                elif mutation == 'duplicate':
                    records['visual']['snapshot_files'].append(copy.deepcopy(records['visual']['snapshot_files'][0]))
                    relock(control, records)
                elif mutation == 'traversal':
                    records['visual']['snapshot_files'][0]['path'] = '../escape'
                    relock(control, records)
                self.assertFalse(inputs(control)['passed'])
                self.assertFalse(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])

    def test_resealed_different_identity_rejected_despite_valid_input_locks(self):
        for mutation in ('content', 'closure', 'source', 'metadata', 'root', 'archive', 'file_url', 'record_license'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp))
                records = json.loads((control/'asset-lock.json').read_text())
                record = records['visual']
                package = control/'assets'/('d'*64)
                metadata = json.loads((package/'simscene-lock.json').read_text())
                if mutation == 'content':
                    (package/'texture.bin').write_bytes(b'different repaired content, same downloaded archive hash')
                elif mutation == 'closure':
                    (package/'added.usda').write_text('#usda 1.0\n')
                elif mutation == 'source':
                    metadata['source'] = record['source'] = 'https://example.invalid/other-source.usda'
                elif mutation == 'metadata':
                    metadata['license'] = 'changed provenance'
                elif mutation == 'root':
                    record['root_relative_to_run'] = 'assets/'+package.name+'/other.usda'
                    spec = json.loads((control/'spec.json').read_text())
                    spec['objects']['visual']['asset_path'] = str(package/'other.usda')
                    dump(control/'spec.json', spec)
                elif mutation == 'archive':
                    metadata['package_sha256'] = record['package_sha256'] = 'e'*64
                elif mutation == 'record_license':
                    record['license'] = 'changed lock provenance'
                dump(package/'simscene-lock.json', metadata)
                rehash_package(package)
                if mutation == 'file_url':
                    metadata = json.loads((package/'simscene-lock.json').read_text())
                    metadata['files'][0]['url'] = 'https://example.invalid/other-file.usda'
                    dump(package/'simscene-lock.json', metadata)
                relock(control, records, repin=True)
                self.assertTrue(inputs(control)['passed'], inputs(control))
                report = p.verify_run(control, mode='broken_rope', reference_run=positive)
                self.assertFalse(report['passed'])
                self.assertFalse(report['paired_asset_snapshots']['passed'])

    def test_nonpath_scene_fields_remain_exact(self):
        for key, value in [('material_variant', 'changed'), ('position', [1, 0, 0]), ('rigid_attachment', {'body': 'weight'}), ('material', {'friction': 9})]:
            with self.subTest(field=key), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp))
                spec = json.loads((control/'spec.json').read_text())
                spec['objects']['visual'][key] = value
                dump(control/'spec.json', spec)
                relock(control)
                report = p.verify_run(control, mode='broken_rope', reference_run=positive)
                self.assertTrue(report['paired_asset_snapshots']['passed'])
                self.assertFalse(report['checks']['only_frozen_isolated_scene_change'])
                self.assertFalse(report['passed'])

    def test_dependency_resolution_outside_complete_snapshot_is_rejected(self):
        for variant in ('resolved_external', 'unresolved', 'mdl_texture', 'mdl_import'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp))
                package = control/'assets'/('d'*64)
                outside = Path(tmp)/'outside.usda'
                outside.write_text('#usda 1.0\n')
                if variant in ('resolved_external', 'unresolved'):
                    ref = outside if variant == 'resolved_external' else Path(tmp)/'missing.usda'
                    (package/'other.usda').write_text('#usda 1.0\n( subLayers = [@'+str(ref)+'@] )\n')
                elif variant == 'mdl_texture':
                    (package/'material.mdl').write_text('mdl 1.0; string t = "'+str(outside.with_suffix('.png'))+'";')
                else:
                    (package/'material.mdl').write_text('mdl 1.0; import missing::*;')
                rehash_package(package)
                if variant.startswith('mdl_'):
                    with self.assertRaises(ValueError):
                        relock(control, repin=True)
                    # A forged empty MDL closure must also fail on re-read.
                    records = json.loads((control/'asset-lock.json').read_text())
                    records['visual'].update(snapshot_lock_sha256=sha(package/'simscene-lock.json'),
                                              snapshot_files=json.loads((package/'simscene-lock.json').read_text())['files'], snapshot_mdl_runtime_files={})
                    relock(control, records)
                    self.assertFalse(inputs(control)['passed'])
                    continue
                relock(control, repin=True)
                self.assertTrue(inputs(control)['passed'])
                report = p.verify_run(control, mode='broken_rope', reference_run=positive)
                self.assertFalse(report['passed'])
                self.assertFalse(report['paired_asset_snapshots']['passed'])

    def test_selected_root_and_external_assets_do_not_get_untrusted_exemption(self):
        for variant in ('path_mismatch', 'external', 'ancestor_symlink'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp))
                records = json.loads((control/'asset-lock.json').read_text())
                spec = json.loads((control/'spec.json').read_text())
                package = control/'assets'/('d'*64)
                if variant == 'path_mismatch':
                    spec['objects']['visual']['asset_path'] = str(package/'other.usda')
                    dump(control/'spec.json', spec)
                elif variant == 'external':
                    file = Path(spec['objects']['visual']['asset_path'])
                    records['visual'] = {'kind': 'external', 'path': str(file), 'files': [{'path': str(file), 'size': file.stat().st_size, 'sha256': sha(file)}]}
                else:
                    moved = Path(tmp)/'moved-assets'
                    (control/'assets').rename(moved)
                    (control/'assets').symlink_to(moved, target_is_directory=True)
                relock(control, records)
                self.assertFalse(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])

    def test_lock_and_runtime_checks_cannot_be_bypassed_by_valid_assets(self):
        for variant in ('unsealed', 'output_tamper', 'seed', 'worker', 'geometry'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                positive, control = make_pair(Path(tmp))
                if variant == 'unsealed':
                    (control/'evidence-lock.json').unlink()
                    with self.assertRaises(ValueError):
                        p.verify_run(control, mode='broken_rope', reference_run=positive)
                    continue
                if variant == 'output_tamper':
                    (control/'result.json').write_text('{}')
                elif variant in ('seed', 'worker'):
                    lock = json.loads((control/'run-lock.json').read_text())
                    if variant == 'seed':
                        lock['seed'] = 77
                    else:
                        lock['worker_code_sha256']['worker/isaac_run.py'] = '0'*64
                    dump(control/'run-lock.json', lock)
                    seal(control)
                else:
                    run = json.loads((control/'result.json').read_text())
                    run['mechanism_configuration']['geometry_settings'] = {'approximate_cylinders_with_convex_meshes': True}
                    dump(control/'result.json', run)
                    seal(control)
                self.assertFalse(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])

    def test_runtime_mdl_proof_exact_keys_content_and_launcher_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            positive, control = make_pair(Path(tmp))
            mdl = positive/'kit/mdl/core/Base/OmniPBR.mdl'
            mdl.parent.mkdir(parents=True)
            mdl.write_text('synthetic runtime MDL, never executed')
            for directory in (positive, control):
                package = directory/'assets'/('d'*64)
                metadata = json.loads((package/'simscene-lock.json').read_text())
                metadata['unresolved_dependencies'] = ['OmniPBR.mdl']
                dump(package/'simscene-lock.json', metadata)
                records = json.loads((directory/'asset-lock.json').read_text())
                records['visual']['runtime_provided_dependencies'] = {'OmniPBR.mdl': str(mdl)}
                records['visual']['runtime_dependency_sha256'] = {'OmniPBR.mdl': sha(mdl)}
                relock(directory, records, repin=True)
            self.assertTrue(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])
            other = control/'elsewhere/OmniPBR.mdl'
            other.parent.mkdir();other.write_bytes(mdl.read_bytes())
            records = json.loads((control/'asset-lock.json').read_text())
            records['visual']['runtime_provided_dependencies']['OmniPBR.mdl'] = str(other)
            relock(control, records)
            self.assertFalse(inputs(control)['passed'])
            self.assertFalse(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])
            records['visual']['runtime_provided_dependencies']['OmniPBR.mdl'] = str(mdl)
            records['visual']['runtime_dependency_sha256'] = {}
            relock(control, records)
            self.assertFalse(inputs(control)['passed'])

    def test_absolute_and_using_mdl_imports_require_complete_sdk_hash_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            positive, control = make_pair(Path(tmp))
            stdlib = positive/'kit/mdl/core/mdl'
            stdlib.mkdir(parents=True)
            (stdlib/'math.mdl').write_text('mdl 1.7; export using ::math import *;')
            for directory in (positive, control):
                package = directory/'assets'/('d'*64)
                (package/'visual.mdl').write_text('mdl 1.7; import ::math::*; using .::local import f; // https://ignored.invalid/x.png\n')
                (package/'local.mdl').write_text('mdl 1.7; export float f() = 1;')
                rehash_package(package)
                relock(directory, repin=True)
            self.assertTrue(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])
            records = json.loads((control/'asset-lock.json').read_text())
            self.assertEqual(set(records['visual']['snapshot_mdl_runtime_files']), {'kit/mdl/core/mdl/math.mdl'})
            records['visual']['snapshot_mdl_runtime_files'] = {}
            relock(control, records)
            self.assertFalse(inputs(control)['passed'])
            relock(control, repin=True)
            (stdlib/'math.mdl').write_text('mdl 1.7; export using ::math import *; // tampered')
            self.assertFalse(inputs(control)['passed'])
            self.assertFalse(inputs(positive)['passed'])

    def test_unknown_absolute_mdl_module_cannot_hide_in_metadata_or_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            positive, control = make_pair(Path(tmp))
            package = control/'assets'/('d'*64)
            (package/'visual.mdl').write_text('mdl 1.7; import ::unknown::*;')
            rehash_package(package)
            with self.assertRaises(ValueError):
                relock(control, repin=True)

    def test_usd_dependency_scan_does_not_trust_stale_open_layer(self):
        from pxr import Sdf
        with tempfile.TemporaryDirectory() as tmp:
            positive, control = make_pair(Path(tmp))
            held = [Sdf.Layer.FindOrOpen(str(d/'assets'/('d'*64)/'model.usda')) for d in (positive, control)]
            external = Path(tmp)/'external.usda'
            external.write_text('#usda 1.0\n')
            for directory in (positive, control):
                package = directory/'assets'/('d'*64)
                (package/'model.usda').write_text('#usda 1.0\n( subLayers = [@'+str(external)+'@] )\n')
                rehash_package(package)
                relock(directory, repin=True)
            self.assertEqual(len(held), 2)
            self.assertTrue(inputs(control)['passed'])
            self.assertFalse(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])


if __name__ == '__main__':
    unittest.main()
