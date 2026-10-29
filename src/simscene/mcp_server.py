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
    """Atomically edit a revision. Supported kinds: box, sphere, asset, camera, light, counter; make ground from a static box. A light can use light={"type":"dome"}, {"type":"sphere","radius_m":0.2}, or {"type":"rect","width_m":2,"height_m":1}; default is distant. Configure intensity, optional light color/exposure and transform. A counter uses counter={"source":"spawned"} or {"source":"verified_archives","class_label":"red"}; verified counts require case-checked archiving. A non-colliding static box can use indicator={"robot_id":"arm"} to show the observed controller phase. A pose_follower can opt into reactive obstacle planning with avoid_obstacles listing static collision-enabled primitive IDs and obstacle_margin_m; this is not collision safety certification. A USD asset requires the local simulation-host asset_path returned by acquisition, not its online URL. Example: {"op":"add","id":"box1","object":{"kind":"box","size":[0.2,0.2,0.2],"position":[0,0,0.1]}}. IDs belong on the operation; object uses kind. Update uses {"op":"update","id":"box1","changes":{...}}. Also supports remove, place_on, arrange_line and look_at. For a static box surface use {"op":"bind_conveyor","id":"belt","speed_m_s":0.1,"direction":[1,0,0]}; imported assets cannot be conveyor surfaces directly. A camera can use camera_orbit={"center":[0,0,0.5],"radius_m":2,"height_m":1,"duration_s":8} for a circular view."""
    from .scene import SceneStore
    return SceneStore().apply(scene_id, base_revision, request_id, operations)

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

@threaded_tool(annotations=_read_local)
def job_status(job_id: str) -> dict:
    """Check a job started in this server session."""
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
def run_verify(job_id: str, case_path: str | None = None, case_type: str | None = None) -> dict:
    """Check completed physical evidence against an independent local case; defaults to the case pinned at simulation_start. Types: contact, suction, moving, repeated, domino, parallel, stream. A single-case pass is not full acceptance."""
    from .jobs import verify_task
    return verify_task(job_id,case_path,case_type)

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
