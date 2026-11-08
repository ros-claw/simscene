"""Agent entry point; importing and listing tools does not launch Isaac Sim."""
import asyncio
import functools
import os
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from .assets import USDSearch
from .cache import AssetCache

server = FastMCP('simscene')

def threaded_tool(*decorator_args, **decorator_kwargs):
    """Keep synchronous disk, network and launch work off the MCP event loop.

    Register an async wrapper while preserving the original callable for SDK
    and unit-test use. FastMCP otherwise invokes sync functions on its event
    loop, making unrelated status calls wait behind a slow snapshot or search.
    """
    def register(function):
        @functools.wraps(function)
        async def dispatch(*args, **kwargs):
            return await asyncio.to_thread(function, *args, **kwargs)
        server.tool(*decorator_args, **decorator_kwargs)(dispatch)
        return function
    return register

_read_local = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_read_network = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

@threaded_tool(annotations=_read_network)
def catalog_search(query: str, filters: dict | None = None, limit: int = 8, cursor: str | None = None) -> dict:
    """Search reviewed sources with bounded metadata only. Read known source IDs from simscene://catalog/sources or simscene catalog sources; copy those IDs into filters.source_ids for explicit selection. Detailed records are linked, not inlined."""
    from .catalog.service import search
    return search(query,filters,limit,cursor)


@threaded_tool(annotations=_read_network)
def catalog_discover(query: str, budget: dict | None = None, cursor: str | None = None) -> dict:
    """Discover bounded HF repository candidates, not enabled libraries. No models, conversion or simulation; review access/license/layout facts before registering a source."""
    from .catalog.service import discover
    return discover(query,budget,cursor)


@threaded_tool(annotations=_read_local)
def scene_compile_recipe(scene_id: str, recipe_id: str, parameters: dict, bindings: dict) -> dict:
    """Compile a versioned recipe into ordinary scene_apply operations at the current base_revision. Supply role bindings with asset_path and pinned asset_binding. This does not edit or run the scene and gives no physical pass; apply the full batch atomically, then freeze and verify a new trial."""
    from .recipes.compile import compile_recipe
    from .scene import SceneStore
    return compile_recipe(recipe_id,parameters,bindings,SceneStore().get(scene_id))


@threaded_tool()
def asset_generate(recipe_id: str, parameters: dict, request_id: str | None = None) -> dict:
    """Start a durable job for an explicitly configured independent Sand3D runtime and a shipped fixed template (guide_plate_v1 or open_receiver_v1). Accepts structured dimensions only, never external programs. Completion returns a generated AssetRef for ordinary asset_plan/asset_prepare; generation alone gives no physical pass."""
    from .generation.jobs import start
    return start(recipe_id,parameters,request_id)

@threaded_tool()
def asset_plan(asset_ref: dict, profile_id: str = 'visual_prop_v1', parameters: dict | None = None, budget_bytes: int | None = None) -> dict:
    """Freeze a selected revision, role, toolchain and transfer budget without downloading models or starting physics. Unknown constraints block preparation."""
    from .acquisition.plans import make_plan
    return make_plan(asset_ref,profile_id,parameters,budgets={'download_bytes':budget_bytes} if budget_bytes is not None else None)

@threaded_tool()
def asset_prepare(plan_id: str, request_id: str | None = None) -> dict:
    """Start a persistent acquisition/preparation job; poll job_status. Preparation alone does not establish runtime physics success. Reuse request_id to reconnect."""
    from .preparation.jobs import start
    return start(plan_id,request_id)

@server.resource('simscene://catalog/sources')
def catalog_sources_resource() -> str:
    """Reviewed source states and provenance; metadata availability is not integration acceptance."""
    import json
    from .catalog.service import sources
    return json.dumps(sources(),ensure_ascii=False)

@threaded_tool(annotations=_read_local)
def environment_probe() -> dict:
    """Inspect configured runtime and GPU without starting Isaac Sim."""
    from .environment import probe
    return probe()

@threaded_tool()
def environment_configure(isaac_python: str | None = None, data_directory: str | None = None, cache_directory: str | None = None, cache_bytes: int | None = None, usd_search_url: str | None = None) -> dict:
    """Save non-secret local defaults; environment variables take precedence."""
    from .settings import update
    values={'isaac_python':isaac_python,'data_directory':data_directory,'cache_directory':cache_directory,'cache_bytes':cache_bytes,'usd_search_url':usd_search_url}
    return update({key:value for key,value in values.items() if value is not None})

@threaded_tool(annotations=_read_network)
def asset_search(query: str = "", limit: int = 20, filters: dict | None = None, image_data_url: str | None = None) -> dict:
    """Find candidate assets online without downloading 3D assets."""
    return USDSearch().search(query, limit, filters, image_data_url)

@threaded_tool(annotations=_read_network)
def huggingface_search_datasets(query: str, limit: int = 20) -> dict:
    """Discover Hugging Face dataset repositories by name."""
    from .huggingface_assets import search_datasets
    return search_datasets(query, limit)

@threaded_tool(annotations=_read_network)
def huggingface_list_assets(repo_id: str, revision: str, limit: int = 100, cursor: str | None = None, path: str = "") -> dict:
    """List USD files from one page of a dataset at a supplied revision."""
    from .huggingface_assets import list_files
    return list_files(repo_id, revision, limit, cursor, path)

@threaded_tool()
def huggingface_acquire_asset(repo_id: str, revision: str, path: str) -> dict:
    """Download one selected dataset USD and resolvable dependencies at a pinned commit; poll job_status."""
    from .jobs import huggingface_acquire_start
    return huggingface_acquire_start(repo_id, revision, path)

@threaded_tool(annotations=_read_network)
def asset_thumbnail(asset_url: str = "", offset: int = 0, image_key: str | None = None) -> Image:
    """Return a preview by search hit thumbnail_image_key or asset URL."""
    if offset < 0 or offset > 50:
        raise ValueError('offset must be between 0 and 50')
    data = USDSearch().thumbnail(asset_url, offset, image_key)
    if data.startswith(b'\x89PNG\r\n\x1a\n'):fmt='png'
    elif data.startswith(b'\xff\xd8\xff'):fmt='jpeg'
    elif data.startswith((b'GIF87a',b'GIF89a')):fmt='gif'
    else:raise ValueError('search service returned an unsupported image format')
    return Image(data=data, format=fmt)

@threaded_tool(annotations=_read_network)
def asset_inspect(asset_url: str) -> dict:
    """Retrieve indexed metadata, dependency graph and download estimate."""
    return USDSearch().inspect(asset_url)

@threaded_tool(annotations=_read_network)
def asset_inspect_local(asset_path: str) -> dict:
    """Inspect a USD file on the simulation host. Physics behavior is not verified."""
    from .asset_inspect import inspect_local
    return inspect_local(asset_path)

@threaded_tool()
def asset_acquire(asset_url: str, refresh: bool = False) -> dict:
    """Start downloading a selected asset and dependencies. Poll job_status until completed; its result.root is the local USD path for scene_apply. Check dependency_status and unresolved_dependencies before use."""
    from .jobs import acquire_start
    return acquire_start(asset_url, refresh)

@threaded_tool(annotations=_read_local)
def robot_solve_ik(urdf_path: str, base_link: str, tool_link: str, joint_names: list[str], target_position: list[float], target_orientation_wxyz: list[float] | None = None, seed: list[float] | None = None) -> dict:
    """Find a URDF IK candidate in the base frame; does not check collisions."""
    from .robotics.ik import solve_ik
    return solve_ik(urdf_path, base_link, tool_link, joint_names, target_position, target_orientation_wxyz, seed)

@threaded_tool()
def robot_prepare_profile(model: str, asset_path: str) -> dict:
    """Prepare experimental controller files for one acquired USD on the simulation host. Models: kawasaki_rs007l_rg2, franka_panda, ur10_short_suction. Poll job_status; validate compatibility and physical behavior before use."""
    from .jobs import robot_profile_start
    return robot_profile_start(model, asset_path)

@threaded_tool(annotations=_read_local)
def robot_suggest_configuration(model_directory: str, base_position: list[float], orientation_wxyz: list[float]) -> dict:
    """Suggest an experimental starting controller configuration for a generated profile and world base pose; validate actual reachability, collisions and behavior in Isaac."""
    from .robotics.profiles import suggest
    return suggest(model_directory, base_position, orientation_wxyz)

@threaded_tool(annotations=_read_local)
def robot_plan_pick_cycle(model_directory: str, drop_position: list[float] | str, item: str = '$item', return_position: list[float] | None = None, workspace_min: list[float] | None = None, workspace_max: list[float] | None = None) -> dict:
    """Propose experimental robot-specific phases for an approximately 4 cm cube; use $slot and $item to expand with scene_plan_stream. Validate all paths and physical results."""
    from .robotics.profiles import pick_cycle
    return pick_cycle(model_directory,drop_position,item,return_position,workspace_min,workspace_max)

@threaded_tool()
def scene_open(scene_id: str) -> dict:
    """Create or reopen a scene specification."""
    from .scene import SceneStore
    return SceneStore().open(scene_id)

@threaded_tool(annotations=_read_local)
def scene_get(scene_id: str) -> dict:
    """Get the current scene specification."""
    from .scene import SceneStore
    return SceneStore().get(scene_id)

@threaded_tool()
def scene_apply(scene_id: str, base_revision: int, request_id: str, operations: list[dict]) -> dict:
    """Atomically edit a revision. For a prepared asset, use asset_path=result.root and asset_binding={"manifest_path":result.manifest_path,"manifest_sha256":result.manifest_sha256} with exactly these two binding keys from the preparation result. A rigid_prop_v1 asset requires dynamic=true. Set rotation with normalized orientation_wxyz=[w,x,y,z]. Supported kinds: box, sphere, cylinder, capsule, compound, joint, asset, camera, light, counter; make ground from a static box. A light can use light={"type":"dome"}, {"type":"sphere","radius_m":0.2}, or {"type":"rect","width_m":2,"height_m":1}; default is distant. Configure intensity, optional light color/exposure and transform. A counter uses counter={"source":"spawned"} or {"source":"verified_archives","class_label":"red"}; verified counts require case-checked archiving. A non-colliding static box can use indicator={"robot_id":"arm"} to show the observed controller phase. A pose_follower can opt into reactive obstacle planning with avoid_obstacles listing static collision-enabled primitive IDs and obstacle_margin_m; this is not collision safety certification. A USD asset requires the local simulation-host asset_path returned by acquisition, not its online URL. Example: {"op":"add","id":"box1","object":{"kind":"box","size":[0.2,0.2,0.2],"position":[0,0,0.1]}}. IDs belong on the operation; object uses kind. Update uses {"op":"update","id":"box1","changes":{...}}. Also supports remove, place_on, arrange_line, arrange_grid, align and look_at. compound uses 1..128 local primitive parts under one unscaled rigid body; part visible=false hides its rendered proxy while retaining collision. An acquired asset with asset_physics=visual_only and asset_lights=disabled can set rigid_attachment={body:compound_ID}; its position/orientation then define a local pose under that dynamic compound. It follows USD hierarchy, with no runtime pose commands. Measure the original mesh and disclose its collision proxy approximation. joint={type:revolute|prismatic|spherical|fixed|d6,body0:null|ID,body1:ID,axis:X|Y|Z,local_pos0:[...],local_pos1:[...],lower_limit:...,upper_limit:...}; angular limits are degrees, linear limits metres. D6 instead requires dof_limits with all6 transX/transY/transZ/rotX/rotY/rotZ values: free, locked, or [low,high] with low<high; no axis/lower_limit fields. Joint X is twist; local_rot0_wxyz/local_rot1_wxyz define frames. D6 swing bounds form a pyramid, not a cone; use measured relative frame quaternion rather than global Euler components. Primitive kind=joint remains passive, with no drive targets. A prepared articulated_prop_v1 asset can use mechanism={"commands":[{"joint_id":"main","trigger":{"type":"at_step","physics_step":0},"target_position":0.5,"position_unit":"rad","stiffness":400,"damping":12,"max_effort":22}]}; use manifest joint IDs and limits, rad for hinges or m for sliders. Commands declare a schedule; actual joint response is observed separately. Initial body poses define initial state. Nonuniform legacy primitives need a baked compound frame when jointed. set_observation with observation={sample_interval_steps:1,strict_start:true,record_contact_pairs:true} requests every actual physics step, a measured reset zero after SDK warmup, and actual per-step contact records; no body setters run during the task. Imported supports need support_surfaces={name:{min_xy:[x,y],max_xy:[x,y],z_m:z,exclude:[]}} in normalized local metres; place_on uses support_surface and offset_xy with optional avoid_ids/keepout_bounds/clearance_m. arrange_grid uses ids,support,support_surface,columns,gap_m; align uses ids,axis,edge,value_m. set_presentation accepts presentation.profile=technical_showcase_1080p and capture/output/budget/diagnostics; camera settings live under camera={resolution:[width,height],focal_length_mm:35,horizontal_aperture_mm:36,...}. Native 30fps records every two physics steps. For a static box surface use {"op":"bind_conveyor","id":"belt","speed_m_s":0.1,"direction":[1,0,0]}; imported assets cannot be conveyor surfaces directly. A camera can use camera_orbit={"center":[0,0,0.5],"radius_m":2,"height_m":1,"duration_s":8} for a circular view."""
    from .scene import SceneStore
    return SceneStore().apply(scene_id, base_revision, request_id, operations)

@threaded_tool(annotations=_read_local)
def scene_measure(scene_id: str, ids: list[str], include_overlap_candidates: bool = False) -> dict:
    """Measure authored world render bounds and bottom anchors, including imported units/axes/variants and rigid visual attachments. Optional include_overlap_candidates returns AABB intersections among selected objects to review initial layout interference; empty compound space and deliberate contact can be false positives. It does not certify physical clearance. Imported outer bbox is not a support surface."""
    from .scene import SceneStore
    from .placement import measure
    return measure(SceneStore().get(scene_id),ids,include_overlap_candidates)

@threaded_tool(annotations=_read_local)
def scene_plan_rope(scene_id: str, prefix: str, points: list[list[float]], radius_m: float = .005, max_segment_m: float = .025, linear_density_kg_m: float = .06, attachments: dict | None = None, physics: dict | None = None, self_collision: bool = True) -> dict:
    """Propose real colliding capsule links connected by passive spherical joints. points are a metric world polyline, including deliberate slack. Optional start/end attachments each use body and local_position_m. Apply returned ordinary operations after review. This is not a distance-only or animated rope; routing over a free pulley and actual tension transfer need physical trials and broken-end controls."""
    from .scene import SceneStore,validate,SceneError
    from .mechanisms import segmented_rope
    import copy
    scene=SceneStore().get(scene_id)
    plan=segmented_rope(prefix,points,radius_m,max_segment_m,linear_density_kg_m,attachments,physics,self_collision)
    probe=copy.deepcopy(scene)
    for op in plan['operations']:
        if op['id'] in probe['objects']:raise SceneError('rope object ID already exists: '+op['id'])
        probe['objects'][op['id']]=op['object']
    errors=validate(probe)
    if errors:raise SceneError(str(errors))
    return {**plan,'base_revision':scene['revision']}

@threaded_tool(annotations=_read_local)
def scene_plan_presentation(scene_id: str, subject_ids: list[str], regions: list[dict] | None = None, profile: str = 'technical_showcase_1080p', duration_s: float = 75, max_cameras: int = 2, azimuth_deg: float = -65) -> dict:
    """Propose measured overview/detail cameras and a capture profile. regions use id,min,max, optional action/subject_ids. Review occlusion, lighting and existing camera budget; apply operations and preview before native recording."""
    from .scene import SceneStore
    from .presentation import plan
    return plan(SceneStore().get(scene_id),subject_ids,regions,profile,duration_s,max_cameras,azimuth_deg)

@threaded_tool(annotations=_read_local)
def run_presentation_events(job_id: str) -> dict:
    """Read semantic phase/spawn events from the completed run's frozen spec. No event implies physical success; inspect run_verify separately."""
    from .jobs import _job,status
    from .presentation import events
    if status(job_id)['state']!='completed':raise ValueError('events require a completed run')
    from .run_integrity import verify as verify_inputs
    from .evidence_integrity import verify as verify_outputs
    if not verify_inputs(_job(job_id)['directory'])['passed'] or not verify_outputs(_job(job_id)['directory'])['passed']:raise ValueError('events require intact source evidence')
    return {'run_id':_job(job_id)['run_id'],'events':events(_job(job_id)['directory'])}

@threaded_tool()
def video_export(segments: list[dict], destination: str, output_resolution: list[int] | None = None, output: dict | None = None, allow_upscale: bool = False, font_file: str | None = None) -> dict:
    """Edit intact real run recordings. Segments require run_directory,camera,start_sim_time_s,end_sim_time_s; optional speed,title. Preserve native cadence, save source hashes and sim/output time mapping. Upscaling requires explicit opt-in."""
    from .video_tools import export
    return export(segments,destination,output_resolution,output,allow_upscale,font_file=font_file)

@threaded_tool()
def video_inspect(path: str, output_dir: str | None = None, representative_count: int = 5, job_id: str | None = None, camera: str | None = None) -> dict:
    """Probe/decode real video; when job_id/camera supplied, bind to intact source and verify native capture dimensions and physics frame clock. Representative PNG paths are returned for actual visual review."""
    from .video_tools import inspect
    record=None
    if job_id is not None:
        from .jobs import _job,status
        from .evidence_integrity import verify
        from .run_integrity import verify as verify_inputs
        from pathlib import Path
        state=status(job_id)
        if state['state']!='completed':raise ValueError('source provenance requires a completed run')
        run=_job(job_id)['directory']
        if not verify(run)['passed'] or not verify_inputs(run)['passed']:raise ValueError('source integrity failed')
        record=state['result'].get('videos',{}).get(camera)
        if not record or Path(record['path']).resolve()!=Path(path).expanduser().resolve():raise ValueError('video path does not match the selected run/camera')
    return inspect(path,output_dir,representative_count,record)

@threaded_tool(annotations=_read_local)
def scene_plan_stream(scene_id: str, prefix: str, labels: list[str], routes: dict, position: list[float], size: list[float], interval_steps: int = 240, first_step: int = 1, mass_kg: float = .1, spawn_steps: list[int] | None = None) -> dict:
    """Propose scheduled workpieces and per-class robot cycles without editing the scene. Each routes[label] uses robot_id, wait={axis,minimum,maximum,max_steps}, cycle=[phases], and optional slots. Use the cycle returned by robot_plan_pick_cycle; apply returned operations with base_revision."""
    from .composition import plan_stream
    from .scene import SceneStore
    scene=SceneStore().get(scene_id)
    result=plan_stream(scene,prefix,labels,routes,position,size,interval_steps,first_step,mass_kg,spawn_steps)
    result['base_revision']=scene['revision']
    return result

@threaded_tool(annotations=_read_local)
def scene_plan_stream_case(scene_id: str, belt_id: str, bins: dict, forbidden_objects: list[str]) -> dict:
    """Propose a scene-derived physical evidence case using explicit per-class inner bin bounds and forbidden objects. This is not independent acceptance or path-safety certification."""
    from .scene import SceneStore
    from .scene_edits.stream_case import plan_case
    scene=SceneStore().get(scene_id);result=plan_case(scene,belt_id,bins,forbidden_objects)
    result['base_revision']=scene['revision']
    return result

@threaded_tool(annotations=_read_local)
def scene_plan_collision_audit(scene_id: str, robot_ids: list[str]) -> dict:
    """Propose discrete overlap monitoring and model-specific mechanical exceptions for supported robot paths or matching generated profiles. Include every robot in the stream case, review exclusions, apply operations, regenerate the case, add collision_policy and run verification. This does not certify swept-path or real-robot safety."""
    from .scene import SceneStore
    from .scene_edits.collision_audit import propose
    scene = SceneStore().get(scene_id)
    result = propose(scene, robot_ids)
    result['base_revision'] = scene['revision']
    return result

@threaded_tool(annotations=_read_local)
def scene_plan_synchronize(scene_id: str, job_id: str, ids: list[str]) -> dict:
    """Propose interleaved spawn times from observed pickup delays in an intact completed stream run. Review and apply the proposal, regenerate the case, and verify simultaneous cycles and safety in a new run; this is not a guarantee."""
    from .jobs import synchronize_plan
    return synchronize_plan(scene_id, job_id, ids)

@threaded_tool(annotations=_read_local)
def scene_plan_retime(scene_id: str, ids: list[str], spacing_factor: float) -> dict:
    """Propose retiming selected scheduled objects, preserving their order and first spawn. Review and apply the operations, then rerun."""
    from .scene import SceneStore
    from .scene_edits.retime import retime
    scene=SceneStore().get(scene_id);result=retime(scene,ids,spacing_factor)
    result['base_revision']=scene['revision']
    return result

@threaded_tool(annotations=_read_local)
def scene_plan_interleave(scene_id: str, ids: list[str], class_order: list[str], interval_steps: int, first_step: int | None = None) -> dict:
    """Propose a class-aware round-robin spawn schedule while preserving each class's item order. Review robot timing and other objects, apply operations, regenerate the case, and rerun physics."""
    from .scene import SceneStore
    from .scene_edits.interleave import interleave
    scene=SceneStore().get(scene_id)
    result=interleave(scene,ids,class_order,interval_steps,first_step)
    result['base_revision']=scene['revision']
    return result

@threaded_tool(annotations=_read_local)
def scene_plan_swap_routes(scene_id: str, first_robot: str, second_robot: str) -> dict:
    """Propose swapping two equal-sized, single-class scheduled robot routes. Review bin labels, reachability and physical results."""
    from .scene import SceneStore
    from .scene_edits.swap_routes import swap_routes
    scene=SceneStore().get(scene_id);result=swap_routes(scene,first_robot,second_robot)
    result['base_revision']=scene['revision']
    return result

@threaded_tool(annotations=_read_local)
def scene_plan_translate_group(scene_id: str, ids: list[str], delta: list[float], move_targets: dict | None = None) -> dict:
    """Propose moving objects by a world-space delta and optionally moving one robot's explicitly selected nearby absolute waypoints. Review the returned phase indices and rerun."""
    from .scene import SceneStore
    from .scene_edits.translate_group import translate_group
    scene=SceneStore().get(scene_id);result=translate_group(scene,ids,delta,move_targets)
    result['base_revision']=scene['revision']
    return result

@threaded_tool(annotations=_read_local)
def scene_validate(scene_id: str) -> dict:
    """Check supported object schemas. This is not physics validation."""
    from .scene import SceneStore, validate
    scene = SceneStore().get(scene_id)
    issues = validate(scene)
    warnings = [{'object':name, 'message':'pose follower is experimental: no collision or trajectory validation'} for name,obj in scene['objects'].items() if 'pose_follower' in obj]
    return {'issues':issues, 'warnings':warnings, 'physics_validation':'not implemented'}

@threaded_tool()
def scene_export(scene_id: str, destination: str) -> dict:
    """Export supported scene objects to a USD file on this server."""
    from .scene import SceneStore
    from .usd_export import export_scene
    return export_scene(SceneStore().get(scene_id), destination)

@threaded_tool()
def simulation_start(scene_id: str, steps: int = 120, seed: int | None = None, case_path: str | None = None, continue_on_controller_error: bool = False, archive_verified_objects: bool = False, case: dict | None = None, request_id: str | None = None) -> dict:
    """Start or queue an experimental Isaac job, optionally pinning an inline case or server-side JSON/YAML case. Reusing the same request_id with identical parameters returns the original job; use a new ID for a distinct run. continue_on_controller_error keeps physics running after a controller failure. archive_verified_objects requires a pinned stream case."""
    from .jobs import start
    return start(scene_id, steps, seed, case_path, continue_on_controller_error, archive_verified_objects, case, request_id)

@threaded_tool()
def job_status(job_id: str, wait_seconds: float = 0, receipt_path: str | None = None) -> dict:
    """Check a job; optionally wait machine-side and save a compact completion receipt. For wait_seconds>0, the caller must choose a new unused absolute receipt_path in their own output directory. A timeout preserves the same job_id; wait again with a new unused receipt path. Waiting grants no physical acceptance. Configure a client timeout longer than wait_seconds."""
    if wait_seconds:
        if receipt_path is None:raise ValueError('waiting requires a new receipt_path')
        from .workflows import wait_job
        return wait_job(job_id,receipt_path,wait_seconds)
    if receipt_path is not None:raise ValueError('receipt_path requires positive wait_seconds')
    from .jobs import status
    return status(job_id)

@threaded_tool(annotations=_read_local)
def run_observe(job_id: str, sample_index: int = -1) -> dict:
    """Read the latest state while running or after failure, or a sample from a completed run."""
    from .jobs import sample
    return sample(job_id, sample_index)

@threaded_tool(annotations=_read_local)
def run_contacts(job_id: str, category: str = 'contact_counts', offset: int = 0, limit: int = 100) -> dict:
    """Page recorded contact_counts, robot_contacts, or optional overlap_counts from a completed run. Overlap counts include expected contacts and do not measure penetration."""
    from .jobs import contacts_page
    return contacts_page(job_id, category, offset, limit)

@threaded_tool(annotations=_read_local)
def run_verify_lock(job_id: str) -> dict:
    """Recheck saved run inputs and external dependencies against recorded hashes."""
    from .jobs import verify_lock
    return verify_lock(job_id)

@threaded_tool(annotations=_read_local)
def run_verify(job_id: str, case_path: str | None = None, case_type: str | None = None, mode: str = 'positive', reference_job_id: str | None = None) -> dict:
    """Check completed physical evidence against an independent pinned local case. Types: contact, suction, moving, repeated, domino, parallel, stream, mechanism, passive_network. Passive schemas infer their type. Mechanism detached_drawer and network no_trigger/broken_rope/locked_door modes require the matching reference_job_id and isolated declared changes. A single positive network run does not accept the whole stage: use run_verify_passive_suite with its frozen required controls. This verifier only reads measurements and never releases or moves a mechanism."""
    from .jobs import verify_task
    return verify_task(job_id,case_path,case_type,mode,reference_job_id)

@threaded_tool(annotations=_read_local)
def run_verify_passive_suite(positive_job_id: str, control_job_ids: dict[str,str], case_path: str | None = None) -> dict:
    """Read-only acceptance of a frozen passive-network positive plus its required isolated controls. control_job_ids maps no_trigger, broken_rope and/or locked_door to completed distinct job IDs. Case bytes, source changes, sampled physical clocks, runtime settings and evidence locks are checked; missing controls cannot accept a P2/P3 stage. This checks physical acceptance, not final video or artistic quality."""
    from .jobs import verify_passive_suite
    return verify_passive_suite(positive_job_id,control_job_ids,case_path)

@threaded_tool(annotations=_read_local)
def run_verify_evidence(job_id: str) -> dict:
    """Recheck saved output hashes; this is not a signature or task-success check."""
    from .jobs import verify_evidence
    return verify_evidence(job_id)

@threaded_tool(annotations=_read_local)
def run_video_chunk(job_id: str, camera: str, offset: int = 0, length: int = 262144) -> dict:
    """Read a bounded, base64-encoded chunk of a completed camera recording."""
    from .jobs import video_chunk
    return video_chunk(job_id, camera, offset, length)

@threaded_tool(annotations=_read_local)
def scene_observe(job_id: str, camera: str) -> Image:
    """Return a live/last preview (when enabled) or a completed camera image."""
    from .jobs import camera_image
    return Image(path=camera_image(job_id, camera))

@threaded_tool()
def job_cancel(job_id: str) -> dict:
    """Request cancellation; poll status for confirmation."""
    from .jobs import cancel
    return cancel(job_id)

@threaded_tool()
def simulation_pause(job_id: str) -> dict:
    """Request a cooperative timeline pause; poll job_status for acknowledgment."""
    from .jobs import set_paused
    return set_paused(job_id,True)

@threaded_tool()
def simulation_resume(job_id: str) -> dict:
    """Request resumption of a paused simulation; poll job_status."""
    from .jobs import set_paused
    return set_paused(job_id,False)

def main(transport='stdio', port=8765):
    if not 1 <= port <= 65535:
        raise ValueError('port must be between 1 and 65535')
    server.settings.host = '127.0.0.1'
    server.settings.port = port
    server.run(transport=transport)
