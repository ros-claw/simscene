# Catalog and prepared-asset validation

These results apply to selected assets and recipes on **Isaac Sim
6.2.0-rc.14+release.52805.02189a84.gl**, Omni Physics 110.4.4 and OpenUSD
0.25.11 on Linux with RTX A6000 hardware. CPU physics was requested; loaded
scene settings read back GPU dynamics disabled, MBP and 60 Hz. That readback
describes scene settings, rather than independent device telemetry. Newton has
not been tested.

| Source / role | Actual evidence | Scope |
|---|---|---|
| NVIDIA USD Search / selected workbench | Metadata search, bounded selected closure, measured bare-table composition and native rendered footage | Visual-only native member with explicitly measured collision proxies; individual asset license remains unknown and blocks the new planning route |
| ABO / notebook rigid body | Three clean drops; missing-support control; four separately observed ramp/baffle/receiver instances; cold rebuild and warm edit | `B01DN8TB5U`, pinned revision, experimental 150 mm scale and 0.12 kg mass; actual imported geometry |
| GSO / scanned product rigid body | Canonical search/plan/durable preparation; 600-step drop; missing-support control; native textured rendering | Selected fondant box, 120 mm longest extent, experimental 0.12 kg; standard GLB variant |
| USDCraft / native hinge | Preserved native two-link articulation; driven forward/reverse actual DOF and frame readback; separate passive contact and collider-disabled control | `ds_R021_02`; metre/Z-up single-DOF only; native limits, mass, collision and friction retained |
| Poly Haven / HDRI | Selected 1k EXR size/MD5/SHA256; warm restore; normal light-only USD preparation and actual two-camera rendering | `studio_small_03`; no geometry, physical body or invented bounds; provider searches configured IDs |
| ProjectSim / BOM package | Pinned descriptor/BOM acquisition; normal visual preparation; native shader smoke; source and prepared eviction/restore | `industrial_pipe_valve`; visual-only, optional vendor metadata stale, no conformance or articulated support claim |
| Sand3D / guide and open receiver | Actual isolated generation, normal preparation, changed-dimension runs, opening passage and closed-top control | Shipped templates only; explicit measured collision approximations, rather than automatic mechanical understanding |

## Profile compatibility

| Profile | Input / role | Admission limit |
|---|---|---|
| `visual_prop_v1` | GLB or native USD visual geometry | Data-only source closure; explicit source-physics policy; no dynamic-body claim |
| `static_fixture_v1` | Measured static support or guide | Explicit verified proxy/support regions; no automatic load certification |
| `rigid_prop_v1` | One imported moving rigid body | Canonical units/axis, experimental mass and bounded measured convex-hull error |
| `articulated_prop_v1` | Existing native hinge/slider | Canonical metre/Z-up, two links and one admitted revolute/prismatic DOF; no joint synthesis or unsafe inertia scaling |
| `container_v1` | Upward open receiver | Explicit source-matched floor/four-wall proxy and passage geometry; no sealed single hull |
| `environment_v1` | Selected HDRI | Light-only self-contained package; no body, dimensions or bounds |

The [kinetic gallery](../../examples/kinetic_asset_gallery/README.md) runs four
independently checked exhibits in one 3,600-step run. Its GSO/domino/ball
handoff chain passes a same-case missing-middle control: upstream still moves,
downstream stays inactive, and the other three exhibits remain successful.
The cabinet uses a declared schedule; the whole gallery is not one passive
causal chain. Native 1080p30 recording and camera-event proposals have separate
frame/provenance checks rather than serving as physical verdicts.

The notebook and scanned product use measured convex-hull fidelity limits.
Rejected geometry remains rejected: a jewellery box filled too much empty
space, and the original-size notebook exceeded the frozen tolerance. Explicit
experimental resizing produced the accepted notebook; the tolerance was not
relaxed. Source mass declarations and recipe assumptions are distinct from
manufacturer measurements.

Native articulation admission rejects missing mass, unsupported graph topology,
time-sampled motion and unsupported joint/inertia scaling. The selected hinge
preparation also excludes executable action/Python graph logic; material shader
node graphs remain supported. Cached prepared stages face the same playback
admission check.

The selected hinge retains its authored friction, approximately 10 Nm static effort. Its passive
prototype used a heavy, explicitly gravity-loaded bench fixture. This is a
rigid-body causal test, **not** a structural-load or consumer-use certification.
Declared drive schedules and measured physical responses remain separate.

Open containers retain an upward passage through five measured wall/floor
proxies. Verification checks the entire probe passing the opening, direct floor
contact, final containment and two seconds of settling. A closed top fails the
passage test. A single convex hull is not treated as an open container.

HDRI preparation preserves the selected texture inside its hashed package;
rendering confirms the actual texture reference and visible product materials
and shadows. The diagnostic overview cropped the initial product top, which was
recorded as a framing failure. Rendering a texture successfully does not certify
final-film composition. Material-map acquisition helpers do not imply a rigid
or geometric preparation profile.

The official Central adapter uses a distinct public HTTP service and literal
filename filters. It exposes that degraded search mode, unavailable predicates,
empty results and failures. Returned owner locators still require their own
license and package admission. The 37-entry research inventory is not a claim
that 37 libraries were integrated.

Every formal trial freezes its acceptance case before running and checks source
and preparation pins, input integrity and saved-output integrity separately.
Missing-support, missing-striker-collision, closed-top and missing-domino
controls discriminate their stated physical paths. Validators only read
evidence; they never release an object or repair the running scene.

The public [gravity-cell recipe](../../examples/catalog_gravity_cell/README.md)
provides locked source URLs, parameters and reproduction commands without model
payloads. Portable prepared-role exports verify original source geometry and
profiles, rebuild into new directories and freeze new case pins; old physical
verdicts are not copied. Metadata-only search, cold model transfers, warm reuse,
derived artifacts and video storage are accounted separately.

Fixed-layout repetitions and same-machine rebuilds establish that scope only.
They do not establish unfamiliar-user generalization or cross-task token/time
savings. The [paired evaluation protocol](catalog-efficiency.md) records those
questions separately; an optimization target is not a measured advantage.
