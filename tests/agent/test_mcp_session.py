"""Exercise the real stdio MCP transport against an isolated scene store."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
import hashlib
import shutil
import uuid
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPIntegration(unittest.TestCase):
    def test_open_edit_validate(self):
        async def run(root):
            env = dict(os.environ, SIMSCENE_HOME=root)
            server = StdioServerParameters(command=sys.executable, args=['-m', 'simscene.cli', 'mcp'], env=env)
            async with stdio_client(server) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertIn('scene_apply', [tool.name for tool in tools.tools])
                    by_name = {tool.name: tool for tool in tools.tools}
                    self.assertTrue(by_name['scene_get'].annotations.readOnlyHint)
                    self.assertFalse(by_name['scene_get'].annotations.openWorldHint)
                    self.assertTrue(by_name['asset_search'].annotations.readOnlyHint)
                    self.assertTrue(by_name['asset_search'].annotations.openWorldHint)
                    self.assertTrue(by_name['run_verify'].annotations.readOnlyHint)
                    self.assertFalse(by_name['scene_apply'].annotations and by_name['scene_apply'].annotations.readOnlyHint)
                    opened = await session.call_tool('scene_open', {'scene_id':'mcp_test'})
                    self.assertFalse(opened.isError)
                    edit = await session.call_tool('scene_apply', {'scene_id':'mcp_test', 'base_revision':0, 'request_id':'setup', 'operations':[{'op':'add','id':'cube','object':{'kind':'box','size':[.2,.2,.2]}}]})
                    self.assertFalse(edit.isError)
                    current = await session.call_tool('scene_get', {'scene_id':'mcp_test'})
                    data = current.structuredContent or json.loads(current.content[0].text)
                    self.assertEqual(data['revision'], 1)
                    self.assertIn('cube', data['objects'])
                    for tool in ('scene_plan_stream_case','scene_plan_collision_audit','scene_plan_retime','scene_plan_interleave','scene_plan_synchronize','scene_plan_swap_routes','scene_plan_translate_group'):
                        self.assertTrue(by_name[tool].annotations.readOnlyHint)
                    add_parts=await session.call_tool('scene_apply',{'scene_id':'mcp_test','base_revision':1,'request_id':'parts',
                        'operations':[{'op':'add','id':'part_a','object':{'kind':'box','dynamic':True,'spawn_step':1,'class_label':'blue'}},
                                      {'op':'add','id':'part_b','object':{'kind':'box','dynamic':True,'spawn_step':601,'class_label':'green'}}]})
                    self.assertFalse(add_parts.isError)
                    reorder=await session.call_tool('scene_plan_interleave',{'scene_id':'mcp_test','ids':['part_a','part_b'],'class_order':['green','blue'],'interval_steps':900})
                    self.assertFalse(reorder.isError)
                    ordered=reorder.structuredContent or json.loads(reorder.content[0].text)
                    self.assertEqual(ordered['base_revision'],2)
                    self.assertEqual([item['id'] for item in ordered['schedule']],['part_b','part_a'])
                    proposal=await session.call_tool('scene_plan_retime',{'scene_id':'mcp_test','ids':['part_a','part_b'],'spacing_factor':1.5})
                    self.assertFalse(proposal.isError)
                    planned=proposal.structuredContent or json.loads(proposal.content[0].text)
                    self.assertEqual(planned['base_revision'],2)
                    self.assertEqual(planned['schedule'][1]['spawn_step'],901)
                    applied=await session.call_tool('scene_apply',{'scene_id':'mcp_test','base_revision':2,'request_id':'retime','operations':planned['operations']})
                    self.assertFalse(applied.isError)
                    robot={'kind':'asset','asset_path':'/assets/FrankaRobotics/FrankaPanda/franka.usd',
                           'pose_follower':{'experimental':True,'model_directory':'/tmp/model','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1],'sequence':[]}}
                    added=await session.call_tool('scene_apply',{'scene_id':'mcp_test','base_revision':3,'request_id':'robot',
                        'operations':[{'op':'add','id':'arm','object':robot}]})
                    self.assertFalse(added.isError)
                    audit=await session.call_tool('scene_plan_collision_audit',{'scene_id':'mcp_test','robot_ids':['arm']})
                    self.assertFalse(audit.isError)
                    proposal=audit.structuredContent or json.loads(audit.content[0].text)
                    self.assertEqual(proposal['base_revision'],4)
                    self.assertTrue(proposal['operations'][0]['changes']['pose_follower']['diagnose_overlaps'])
                    self.assertEqual(proposal['collision_policy']['grasp_bodies']['arm'],['panda_leftfinger','panda_rightfinger'])
                    run_id=uuid.uuid4().hex;job_id=uuid.uuid4().hex
                    directory=Path(root)/'runs'/run_id;directory.mkdir(parents=True)
                    shutil.copyfile('evidence/three-arm-stream3.json',directory/'result.json')
                    shutil.copyfile('evidence/three-arm-stream3-spec.json',directory/'spec.json')
                    spec=directory/'spec.json';data=json.loads(spec.read_text());data['objects']={k:v for k,v in data['objects'].items() if v.get('kind')!='asset'};spec.write_text(json.dumps(data))
                    case=directory/'acceptance-case.json'
                    shutil.copyfile('tests/fixtures/three_arm_stream_case.json',case)
                    for name,contents in [('scene.usda','#usda 1.0'),('asset-lock.json','{}'),('runtime-lock.json','{}'),('python.sh','launcher')]:
                        (directory/name).write_text(contents)
                    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
                    lock={'run_id':run_id,'job_id':job_id,'scene_revision':1,'acceptance_case_file':case.name,'acceptance_case_sha256':digest(case),'runtime_python':str(directory/'python.sh'),'runtime_python_sha256':digest(directory/'python.sh')}
                    for name,key in [('spec.json','spec_sha256'),('scene.usda','stage_sha256'),('asset-lock.json','asset_lock_sha256'),('runtime-lock.json','runtime_lock_sha256')]:lock[key]=digest(directory/name)
                    (directory/'run-lock.json').write_text(json.dumps(lock))
                    (directory/'job.json').write_text(json.dumps({'run_id':run_id,'job_id':job_id,'pid':99999999,'identity':None}))
                    checked=await session.call_tool('run_verify',{'job_id':job_id})
                    self.assertFalse(checked.isError)
                    report=checked.structuredContent or json.loads(checked.content[0].text)
                    self.assertTrue(report['passed']);self.assertTrue(report['case_pinned_to_run'])
                    case.write_text('{}')
                    self.assertTrue((await session.call_tool('run_verify',{'job_id':job_id})).isError)
        with tempfile.TemporaryDirectory() as root:
            asyncio.run(run(root))
