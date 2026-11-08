"""Explicit v43 source/pin fork; synthetic CPU inputs, no house observations."""
import ast,copy,hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from experiments import whole_home_fidelity_v8 as f8,whole_home_fidelity_v9 as f9
from experiments import whole_home_suite_v8 as s8,whole_home_suite_v9 as s9
from experiments import bounded_entry_clock_v5 as k5,bounded_entry_clock_v6 as k6
from experiments import retained_report_integrity_v3 as r3,retained_whole_home_suite_v3 as a3,independent_examiner_custody_v3 as u3
from test_bounded_entry_clock_v4 import fixture
ROOT=Path(__file__).resolve().parents[1]
B=Path(os.environ.get('SIMSCENE_TEST_EVIDENCE_ROOT','/code/rosclaw/simscene/evidence/whole-room-sugar-20261031'))
OLD=Path(os.environ.get('SIMSCENE_TEST_OLD_CHECKOUT','/home/dell/simscene-worktrees/passive-d6-rope'))
PREP=B/'p3-independent-binding/case3-software-preparation-v2'
SW=B/'generic-freeze/v43-software.json';SWOLD=B/'generic-freeze/v42-software.json'
HOST_ARCHIVE=all(p.is_file() for p in (PREP/'generate_authority_fork.py',SW,SWOLD,OLD/'experiments/whole_home_fidelity_v8.py'))
g=None
if HOST_ARCHIVE:
 sp=importlib.util.spec_from_file_location('frozen_version_generator',PREP/'generate_authority_fork.py');g=importlib.util.module_from_spec(sp);sp.loader.exec_module(g)
host_archive=unittest.skipUnless(HOST_ARCHIVE,'Actual frozen workstation archives required; portable CPU checks still run')
class V43OrchestrationTests(unittest.TestCase):
 @host_archive
 def test_all72_original_functions_preserve_exact_version_slot_AST_and_generated_bytes(self):
  self.assertEqual(g.sha(PREP/'generate_authority_fork.py'),'64c70e1b972ed80d78f0f8a4a9156a41a19661d9fad4fae32b32e4e385f7ce13')
  expected,hashes,_=g.build_sources(g.sha(SW));actual={key:(ROOT/'experiments'/new).read_text() for key,(_,new,_) in g.MODULES.items()}
  self.assertEqual(actual,expected);self.assertEqual(sum(map(len,g.function_parity(actual).values())),72)
  for key,(_,new,_) in g.MODULES.items():self.assertEqual(g.sha(ROOT/'experiments'/new),hashes[key])
 @host_archive
 def test_complete_module_AST_allows_only_explicit_import_schema_pin_version_slots(self):
  texts,hashes,_=g.build_sources(g.sha(SW))
  for key,(oldname,newname,_) in g.MODULES.items():
   with self.subTest(module=key):
    substitutions={g.MODULES[dep][2]:hashes[dep] for dep in g.MODULES}
    substitutions.update({a:b for a,b in g.SCHEMAS.values()})
    substitutions['04d4cc41021ef72eb704d3660c45b47637f993106654787995d5aa5a8dd10e22']=g.sha(SW)
    substitutions['simscene.independent_examiner_custody_freeze.v2']='simscene.independent_examiner_custody_freeze.v3'
    class Slots(g.FunctionVersionSlots):
     def visit_Constant(self,node):
      if isinstance(node.value,str) and node.value in substitutions:return ast.copy_location(ast.Constant(substitutions[node.value]),node)
      return super().visit_Constant(node)
     def visit_ImportFrom(self,node):
      if node.module:node.module=g.label(node.module)
      for name in node.names:name.name=g.label(name.name)
      return node
     def visit_Import(self,node):
      for name in node.names:name.name=g.label(name.name)
      return node
     def visit_Assign(self,node):
      self.generic_visit(node)
      if key=='F9' and any(isinstance(t,ast.Name) and t.id=='ORCHESTRATION_VERSION' for t in node.targets) and isinstance(node.value,ast.Constant) and node.value.value==8:node.value=ast.Constant(9)
      return node
    old=Slots().visit(ast.parse((OLD/'experiments'/oldname).read_text()))
    self.assertEqual(ast.dump(old,include_attributes=False),ast.dump(ast.parse(texts[key]),include_attributes=False))
 @host_archive
 def test_archived_v43_complete_guard_and_all_new_dependency_guards_pass(self):
  self.assertEqual(g.sha(SW),'5cecd9539706764105a8ee7b59eb535e9e0bb6e0ff3c1b9cb38c3f2723c548fa')
  record=json.loads(SW.read_text());archive=Path(record['checkout_root'])
  if not archive.is_dir():self.skipTest('Original v43 source archive required, independent of the evolving checkout')
  env=dict(os.environ);env['PYTHONPATH']=str(archive/'src')+os.pathsep+str(archive)
  code="import json;from experiments import whole_home_fidelity_v9 as f;print(json.dumps(f.assert_software_freeze("+repr(str(SW))+")))"
  original=subprocess.run([sys.executable,'-c',code],cwd=archive,env=env,capture_output=True,text=True,check=True)
  result=json.loads(original.stdout);self.assertEqual(result['installed_file_count'],1086);self.assertEqual(result['checkout_source_file_count'],112)
  if any(g.sha(ROOT/name)!=digest for name,digest in record['checkout_source_sha256'].items()):
   with self.assertRaisesRegex(ValueError,'frozen checkout source changed'):f9.assert_software_freeze(SW)
  k6.assert_dependencies();r3.assert_dependencies();a3.assert_dependencies()
  self.assertEqual(u3.sha(r3.__file__),u3.PINS['retained_report_integrity']);self.assertEqual(u3.sha(a3.__file__),u3.PINS['retained_whole_home_suite'])
  self.assertIs(s9.f,f9);self.assertIs(k6.f,f9);self.assertIs(r3.f,f9);self.assertIs(r3.suite,s9);self.assertIs(a3.original,s9);self.assertIs(u3.retained,r3)
 @host_archive
 def test_old_and_new_software_versions_strictly_reject_one_another(self):
  with self.assertRaisesRegex(ValueError,'software freeze record changed'):f8.assert_software_freeze(SW)
  with self.assertRaisesRegex(ValueError,'software freeze record changed'):f9.assert_software_freeze(SWOLD)
  with self.assertRaisesRegex(ValueError,'checkout source changed'):f8.assert_software_freeze(SWOLD)
 @host_archive
 def test_old_authority_still_accepts_its_own_untouched_checkout_without_monkeypatch(self):
  if not OLD.is_dir() or not SWOLD.is_file():self.skipTest('Explicit host-owned immutable v42 archive required')
  env=dict(os.environ);env['PYTHONPATH']=str(OLD/'src')+os.pathsep+str(OLD)
  code="import json;from experiments import whole_home_fidelity_v8 as f;print(json.dumps(f.assert_software_freeze("+repr(str(SWOLD))+")))"
  out=subprocess.run([sys.executable,'-c',code],cwd=OLD,env=env,capture_output=True,text=True,check=True)
  self.assertTrue(json.loads(out.stdout)['passed'])
 @host_archive
 def test_old_sources_and_all_frozen_physical_dependencies_unchanged(self):
  for old,_,digest in g.MODULES.values():
   for base in (OLD,ROOT):self.assertEqual(g.sha(base/'experiments'/old),digest)
  for rel,digest in g.UNCHANGED.items():
   for base in (OLD,ROOT):self.assertEqual(g.sha(base/rel),digest)
  self.assertEqual(f9.m.PAIRED_MANIFEST_FIELDS,f8.m.PAIRED_MANIFEST_FIELDS);self.assertEqual(len(f9.m.PAIRED_MANIFEST_FIELDS),13)
 def test_geometry_earliest_escape_and_no_new_mask_credit_identical(self):
  for collapsed in (True,False):
   for inactive in ((),(4,5,6),(59,60)):
    with self.subTest(collapsed=collapsed,inactive=inactive):
     run,spec,case,stock,inner,outer,contract=fixture(collapsed,inactive)
     inner['schema']=k5.h.SCHEMA;outer['schema']=k5.h.SCHEMA
     before=copy.deepcopy((run,spec,case,stock,inner,outer))
     old=k5.evaluate(run,spec,case,stock,inner,outer,{**contract,'schema':k5.SCHEMA})
     new=k6.evaluate(run,spec,case,stock,inner,outer,{**contract,'schema':k6.SCHEMA})
     old['schema']=new['schema']
     if 'stability_authority' in old:old['stability_authority']=old['stability_authority'].replace('stock/v8 report','stock/v9 report')
     self.assertEqual(old,new);self.assertEqual((run,spec,case,stock,inner,outer),before)
 def test_each_original_prefix_floor_and_missing_mask_stays_strict(self):
  run,spec,case,stock,inner,outer,contract=fixture(True)
  for helper in (k5,k6):
   for field,value in [('minimum_chain_duration_s',49),('minimum_net_effective_action_s',44),('minimum_motion_occupancy',.84),('maximum_idle_s',2.1)]:
    with self.subTest(helper=helper.__name__,field=field):
     changed=copy.deepcopy(case);changed['activity']['limits'][field]=value
     with self.assertRaises(ValueError):helper.prepare({**contract,'schema':helper.SCHEMA,'limits':changed['activity']['limits']},inner,outer,spec,changed)
   missing=copy.deepcopy(stock);missing['activity']['per_step_motion_flags'].pop(3)
   with self.assertRaises(ValueError):helper.prefixes(missing,case,58,58,contract['physics_dt_s'])
 def test_new_clock_does_not_relabel_an_old_complete_report(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);p=root/'synthetic-full.json';locks={'run-lock.json':'a'*64,'evidence-lock.json':'b'*64}
   stock={'checker_sha256':f9.KERNEL_SHA256['passive_network'],'passed':True,'mode':'positive','profile':'P3','case_sha256':'c'*64,'activity':{},'terminal':{}}
   report={'passed':True,'mode':'positive','orchestration_version':9,'supplemental_code_sha256':k6.DEPENDENCIES['fidelity'],'run_directory':str(root),'run_lock_sha256':locks['run-lock.json'],'evidence_lock_sha256':locks['evidence-lock.json'],'stock':stock,'suite_metadata':{'evidence_sha256':{}}}
   p.write_text(json.dumps(report));self.assertEqual(k6.reduced_report(p,k6.sha(p),root,locks)['stock'],{key:stock[key] for key in ('passed','mode','profile','case_sha256','activity','terminal')})
   with self.assertRaises(ValueError):k5.reduced_report(p,k5.sha(p),root,locks)
   for field,value in [('orchestration_version',8),('supplemental_code_sha256',f8.sha(f8.__file__))]:
    changed={**report,field:value};p.write_text(json.dumps(changed))
    with self.assertRaises(ValueError):k6.reduced_report(p,k6.sha(p),root,locks)
 def test_retained_reader_and_custody_require_strict9_not_a_version_union(self):
  self.assertEqual(f9.ORCHESTRATION_VERSION,9);self.assertEqual(u3.SCHEMA,'simscene.independent_examiner_invocation.v3')
  self.assertEqual(u3.FREEZE_SCHEMA,'simscene.independent_examiner_custody_freeze.v3')
  for version in (8,10,None):
   with self.subTest(version=version):
    with self.assertRaisesRegex(ValueError,'original f9 report'):r3._original_report_shape({'passed':True,'mode':'positive','orchestration_version':version,'formal_house_accepted':False},{},{},'positive',7800,1/60)
  src=Path(u3.__file__).read_text();self.assertIn("'checker_orchestration_version': 9",src);self.assertIn("retained._digest",src)
 @host_archive
 def test_no_numeric_or_inventory_change_can_hide_under_version_AST_normalization(self):
  sources,_,_=g.build_sources(g.sha(SW))
  for key,a,b in [('K6',"limits['minimum_chain_duration_s'] >= 50","limits['minimum_chain_duration_s'] >= 49"),('A3','len(memoized) == 8','len(memoized) == 7'),('K6',"report.get('orchestration_version') == 9","report.get('orchestration_version') in (8,9)")]:
   with self.subTest(key=key,a=a):
    changed=copy.deepcopy(sources);self.assertIn(a,changed[key]);changed[key]=changed[key].replace(a,b)
    with self.assertRaises(ValueError):g.function_parity(changed)
 @unittest.skipIf(os.environ.get('SIMSCENE_PORTABILITY_CHILD')=='1','Parent process exercises archive-free collection')
 def test_portable_checks_run_without_private_workstation_archives(self):
  with tempfile.TemporaryDirectory() as tmp:
   env=dict(os.environ);env.update(SIMSCENE_TEST_EVIDENCE_ROOT=str(Path(tmp)/'absent-evidence'),SIMSCENE_TEST_OLD_CHECKOUT=str(Path(tmp)/'absent-checkout'),SIMSCENE_PORTABILITY_CHILD='1')
   env['PYTHONPATH']=os.pathsep.join(str(ROOT/p) for p in ('src','.','tests'))
   out=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_v43_orchestration.py'],cwd=ROOT,env=env,capture_output=True,text=True)
   self.assertEqual(out.returncode,0,out.stdout+out.stderr)
   self.assertIn('Ran 12 tests',out.stderr)
   self.assertIn('skipped=8',out.stderr)
if __name__=='__main__':unittest.main()
