# Independent whole-home examiner v5

This external version preserves frozen v4 and the installed v41 package. New
files are `whole_home_fidelity_v5.py` and `whole_home_suite_v5.py`; their public
schemas are `simscene.whole_home_fidelity.v3` and `simscene.whole_home_suite.v3`,
with report orchestration version 5. The v41 software freeze remains
`17aaa6433e87e2cc9101908492e272d8b7955687a99511ad3f3d23b3dc2d98ce`.

The sole behavioral change recognizes two legal passive USD schema defaults in
the static catalog. OpenUSD documents `float physics:breakForce = inf` and
`float physics:breakTorque = inf` as joint breaking thresholds. They are not
applied force/torque values. The local `Usd.SchemaRegistry` independently returns
the same positive-infinite fallback and Float type for both attributes.
[OpenUSD joint schema reference](https://openusd.org/release/api/class_usd_physics_joint.html)

Recognition requires **all** of the following:

* The actual prim satisfies typed `UsdPhysics.Joint`.
* The full name is exactly `physics:breakForce` or `physics:breakTorque`.
* The actual value is a positive-infinite float, with no time samples.
* The actual concrete schema definition exists and supplies the same positive-
  infinite float fallback and Float attribute type.
* The resolved attribute type and every authored property-stack type agree
  with that canonical Float type. A conflicting raw Sdf declaration is rejected
  even when USD's typed resolution presents it as Float.

The original tagged value, authored status, time-sample inventory and full
attribute remain in the catalog. An explicit canonical-default interpretation
and schema/stack-type evidence are added; nothing is omitted or clamped to a
finite value. Recognition has no asset-name/path whitelist and does not rely
on a particular asset being inert. It applies equally to a legitimate passive
joint while leaving every active-physics rejection in force. Drives, force and
surface-velocity schemas/attributes, kinematics, time-authored physics/transforms,
all other authored infinities, negative infinity and NaN remain rejected.

The motivating static artifact contains imported joint prims with `enabled=true`
but no RigidBodyAPI/CollisionAPI in their visual-only endpoint subtree. That
inert-subtree interpretation is separately inventoried; it is not a reason to
hide the joints or waive the catalog. The generic fix recognizes documented
breaking-threshold semantics, not an actor exemption. V4's actual rejection
artifact and its code/freeze are retained unchanged.

Every task/case/activity/control/variant/geometry/terminal predicate is unchanged
from v4. The original all-200 first/final60-degree tips, six transmitting kinds,
50/45/.85/2 timing floors, 121-sample **and actual two-second** hold, all three
controls, three consecutive repeats, exact .20m cup variant plus meaningful
local change, runtime13 identity, native videos, acquired identities and distinct
editable replay remain. Source/worker/SDK/package105/1080 files are untouched.
The original bounded-retention orchestration and mask CSV remain identical.

Generic tests use real temporary USD prims/attributes for positive defaults,
wrong prim/name/type, NaN, negative infinity, time samples and continued drive/
kinematic/force/mass rejection. A real USD prim plus a narrow registry shim
tests absent/changed future schema fallback without installing a custom schema
plugin. These are CPU fixtures, not physics evidence. Generic code/policy/tests
are frozen before applying v5 to any candidate catalog or binding formal cases.
