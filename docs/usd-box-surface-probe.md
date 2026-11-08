# Read-only USD box/surface evidence

`experiments/usd_box_surface_probe.py` tests a declared box against every valid
triangle in a selected local USD subtree. It performs no asset/scene editing,
simulation, GPU, renderer, collider cooking or trajectory reading. The frozen
`usd_geometry_probe.py` v2 file must retain SHA
`572671cb3d8baab09f01d85e583c127e660566596751e144e1dc423386d438f7`.
The new helper reuses that reader's geometry, units, transforms, native instance
paths, visibility/purpose, topology and displacement checks without modifying
the reader. Provenance requires a separate complete content lock.

The box JSON has exactly these fields:

| Field | Meaning |
| --- | --- |
| `center_world_m` | Finite three-vector in the selected asset stage's world axes, in metres |
| `axes_world` | Three finite unit orthogonal axis vectors; their dot products must match the identity within 1e-12 |
| `half_size_m` | Three finite, strictly positive half dimensions, measured along the declared axes |

No up-axis remapping occurs. Reference-layer units are not silently repaired;
the pinned reader's explicit composed transform determines the represented
vertices. A fresh CLI process avoids unsaved/stale USD caches. The query reads
only `Usd.TimeCode.Default()` and reports stage units, authored metadata,
selected visibility/purposes, prims, face/triangle counts and rejected geometry.

The accepted finite axes are used unchanged. The represented volume is
`center + sum(t[i] * axes[i])`, with `abs(t[i]) <= half_size[i]`. Because finite
unit vectors may only be approximately orthogonal, the three box face normals
are **cross products of its other two edge vectors**. Edges are not substituted
for exact face normals. This is the parallelepiped defined by those inputs,
without snapping or normalizing it to a different pose.

For each triangle, the separating axis test uses all necessary nonzero axes:
three box face normals, the triangle normal and nine triangle-edge/box-edge
cross products. Fractions represent the finite binary input vertices/axes
exactly, so SAT projections, dot products, cross products and comparisons have
no floating-point roundoff. This does **not** prove that the upstream USD
transform calculation had zero roundoff or that a renderer has the same
surface. The scope is the transformed finite vertices returned by the pinned
reader, and the caller's original finite axis vectors.

The only geometric expansion is a fixed 1 nm added to each declared half size.
It is used conservatively:

| Outcome | Interpretation |
| --- | --- |
| `intersecting_faces` | The original represented box and triangle intersect, with no exact SAT boundary equality |
| `touching_faces` | They intersect with an exact supporting-axis boundary equality |
| `ambiguous_faces` | The original inputs separate but the expanded box intersects, or represented geometry is degenerate |
| `surface_disjointness_established: true` | Every selected supported triangle was tested, no unknown remains and even the expanded box separates from every triangle |

The arrays retain original mesh, native-instance/prototype, face and fan
triangle identities, full triangle points and geometric normals. They contain
triangle records, so two triangles from one polygon keep the same face ID and
different triangle IDs. They are not deduplicated into a claim about an ideal
curved surface. The actual examined/separated counts and SAT-axis operation
count are reported. A single separating axis is sufficient to reject one
triangle; every non-separated triangle uses the full necessary axis set.

Subdivision/deformation, unsupported geometry, rejected topology, degenerate
faces, unknown displacement in strict scope, composition/cache errors, numeric
invalidity, resource failure or ambiguous near-boundary results make the whole
query incomplete. Partial hits remain evidence but cannot certify disjointness.
The default budgets are 50,000 faces per prim, 50,000 examined triangles total
and 10,000 visited prims. At most 13 SAT axes are tested per triangle: 650,000
axis tests by default, with a hard 100,000-triangle / 1,300,000-axis ceiling.
Optional budget arguments can only choose positive values up to the stated
hard caps; exhausting a budget returns incomplete. These are traversal/SAT
work bounds, not a wall-clock or peak-memory guarantee for upstream USD parsing.

Strict displacement scope is the default. Only an explicit
`--scope authored_base_geometry` measures the base mesh with connected
displacement candidates recorded but unevaluated. Every mode always retains
`rendered_surface_equivalence: "not_established"` and
`rendered_surface_query_complete: false`; no material-name exception exists.

**No surface intersection does not establish that the box is inside a cup or
inside an empty cavity.** A box outside a solid and a box wholly inside it can
both have no surface crossing. `containment_established` is always false and
`cavity_membership` is always `not_assessed`. Future cavity review also needs
independent mouth, interior-side and center witnesses. This helper supplies
no receiving box, sugar dimensions, scene coordinates, physical parameters or
simulation acceptance decision.

Read-only invocation with caller-declared, independently locked inputs:

```bash
PYTHONPATH=src /home/dell/.local/share/simscene/venv-v31/bin/python \
  experiments/usd_box_surface_probe.py /locked/asset.usd \
  --prim /Selected --box /declared/box.json --output /new/query.json
```

Output paths are created exclusively and never replace prior evidence. Exit
code 0 means the selected geometry query completed; it does **not** mean no
surface was intersected, containment succeeded or a physical test passed.
