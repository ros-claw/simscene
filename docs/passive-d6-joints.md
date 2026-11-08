# Passive D6 joints

The experimental dev8 interface adds a generic `PhysicsJoint` with explicit
per-axis `LimitAPI` modes. It does not apply a DriveAPI, force, pose target,
runtime body setter, or automatic task release. Old spherical joint scenes
keep their prior authoring behavior.

```json
{
  "kind": "joint",
  "joint": {
    "type": "d6",
    "body0": "link_a",
    "body1": "link_b",
    "local_pos0": [0, 0, 0.01],
    "local_pos1": [0, 0, -0.01],
    "dof_limits": {
      "transX": "locked",
      "transY": "locked",
      "transZ": "locked",
      "rotX": [-15, 15],
      "rotY": [-70, 70],
      "rotZ": [-70, 70]
    }
  }
}
```

This example specifies modes, not a ready cord assembly. Body poses, metric
anchors and local frame rotations must be designed together. Joint X is the
twist axis. A capsule's length is local Z; map the frames deliberately when
twist is meant to follow that length. Frame disagreement can preload or violate
a limit at the start. Adjacent body collisions and rope self-collision remain
explicit separate choices.

All six axes are mandatory. `free` omits that axis's LimitAPI. `locked` authors
finite low=1, high=-1, whose ordering is the USD lock sentinel, rather than a
one-unit displacement. Numeric ranges use low < high. Equal endpoints,
nonfinite bounds and ranges lost by USD Float quantization are rejected.
Angular ranges stay strictly within ±180°. Translation uses metres and angular
limits degrees. Double swing limits are a pyramid, not a cone.

Before motion the worker records the resolved loaded USD modes and attributes,
checks them against the authored values at USD Float precision, and rejects an
unexpected limit instance, animation, soft limit, projection or drive on a
declared passive D6. Loaded endpoints, local frames, flags and raw lock
sentinels are also checked. This is source
readback, not a native constraint-force measurement. Per-step observations keep
the translation and full quaternion of `J=(G0 L0)^-1 (G1 L1)`, twist about joint
X and overall swing. The overall swing is not either individual pyramid
coordinate. Twist is explicitly undefined at a 180° swing. These observations
never actuate the joint.

In strict runs D6 frames use the body transforms from the very same PhysX
tensor sample as the saved body poses, together with the loaded local frames.
The initial sample follows the same rule. `pose_source` records this choice.
Without a supplied tensor sample the standalone reader uses loaded USD body
transforms and labels that fallback. Neither path is an independent native
joint-angle getter. The four older joint types retain their previous reader.

For three locked translations the reported anchor error remains the full norm
of anchor separation. With other modes it is the translational violation of
the declared bounds; `frame_separation_m` independently retains the full norm.
Hard angle limits model an articulated cable with restricted relative bending
and twisting. They do not establish real fibre elasticity, stiffness, damping,
tension, friction calibration or rope-knot behavior.

CPU schema/frame tests are separate from native enforcement. Before accepting a
new rope model, test native locked/free/limited axes with gravity, off-origin
and rotated local frames, initial limit compatibility, a connected load and a
sole load-end cut. Preserve source and loaded settings, body transforms,
contacts, complete step clocks and failed attempts. New model admission must
have its own software/case version; old spherical-only checkers remain intact.

The dev9 verification interface admits this model explicitly as
`simscene.mechanism.v2`, with `rope_joint_model: passive_d6_limited` and strict
initial observations. Interior joints must join actual colliding dynamic
capsules, lock all three translations, and declare finite ordered ranges for
all three angles. Local frame X must follow capsule Z. Additional world or
body joints on the cord are rejected. The complete source D6 inventory must
equal the declared interior chain; the endpoints retain the original
spherical/fixed contract and the isolated drawer-end cut.

`simscene.passive_network.v3` embeds exactly one such cord assertion and the
existing typed structural loads. All older schemas keep their original public
dispatch. The original mechanism and network checkers remain byte-identical;
new modules retain their geometry, contact, motion, quiet, paired runtime and
action duration calculations. Existing spoon/door local assertions use the
retained numerical calculations in the new composition context.

Admission compares resolved loaded schemas, six-axis modes, raw sentinels,
Float local frames and flags to the source. It independently reconstructs
every joint observation from the saved native body poses at sample0 and each
consecutive step. `configuration.passed` proves this declaration and observation
identity. It does **not** prove absence of initial angular preload, calibrated
elasticity, or enforcement of every angular limit. Initial frame compatibility
needs its own static preflight before release. Observed principal twist excess
is explicitly diagnostic (`twist_excess_is_diagnostic: true`); overall swing is
never compared with either pyramid coordinate. Rope transmission still needs
all original slack, wrap, contact, anchor, motion and detached-end predicates,
and full scenes still need their original independent timing and controls.

Primary references: [Omni Physics joints](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.1/dev_guide/rigid_bodies_articulations/joints.html),
[OpenUSD physics proposal](https://openusd.org/25.11/wp_rigid_body_physics.html),
[PhysX D6 LimitAPI mapping](https://nvidia-omniverse.github.io/PhysX/ovphysx/latest/population/PhysicsLimitAPI.html).
