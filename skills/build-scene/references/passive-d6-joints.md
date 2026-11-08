# Passive D6 joints

Use D6 for segmented cables that need explicit bend and twist limits. It is a
passive `PhysicsJoint`, with no drive or automatic downstream release.

```json
{
  "kind": "joint",
  "joint": {
    "type": "d6", "body0": "link_a", "body1": "link_b",
    "local_pos0": [0, 0, 0.01], "local_pos1": [0, 0, -0.01],
    "dof_limits": {
      "transX": "locked", "transY": "locked", "transZ": "locked",
      "rotX": [-15, 15], "rotY": [-70, 70], "rotZ": [-70, 70]
    }
  }
}
```

This illustrates the declaration, not a ready cable. All six axes are required;
use `free`, `locked`, or an ordered finite range. Translation is in metres and
angular limits in degrees, strictly inside ±180°. A USD lock uses low greater
than high; it does not mean a one-unit displacement. Equal numeric endpoints
are rejected. Two swing limits form a pyramid, not a cone.

Joint X is the twist axis. Capsule length is local Z: rotate both local joint
frames deliberately and check their initial agreement before release. Keep
adjacent/self-collision choices explicit. A constraint can begin preloaded even
when its anchors coincide.

Use the loaded configuration and same-sample body poses to inspect joint-frame
translation, relative quaternion, twist and swing. These reconstructed values
are distinct from an independent native joint-angle getter. Overall swing is
not either individual pyramid coordinate. Declaration readback alone does not
prove limit enforcement or calibrated rope elasticity, tension or friction.

For `simscene.mechanism.v2`, set `rope_joint_model: passive_d6_limited` and
declare the complete interior chain; endpoints retain their fixed/spherical
contract. Before accepting a new load or layout, verify resting compatibility,
actual transmission and a matched drawer-end cut. Keep both endpoints' original
motion, complete observations, case and runtime pins. See
[network verification](passive-network-verification.md) for composition.
