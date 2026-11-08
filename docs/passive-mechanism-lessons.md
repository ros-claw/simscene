# Passive mechanism authoring lessons

These are engineering observations from the sugar-chain development, not a
whole-house success claim or a replacement for per-scene physical validation.
See the [network contract](passive-network-verification.md) and
[mechanism authoring reference](../skills/build-scene/references/passive-mechanisms.md)
for the actual interface.

## A visible support must also be a collider

Set `collision: true` explicitly on static task supports. A visible box can be
pure scenery. Check the exported collider paths and real contact callbacks,
including any support added during a repair. When combining modules, use their
latest `scene_get` snapshots or update the operation generators as well; replaying
an early generator can silently reintroduce an already repaired omission.

## A guide can carry the load that friction needs

A world-grounded horizontal prismatic joint locks vertical motion. Its reaction
can support the drawer's weight, leaving a nearby nominal support rail with
little or no contact normal force. Increasing a Coulomb friction coefficient
alone does not establish the desired resistance: friction capacity depends on
the actual normal load.

Choose a physical support arrangement deliberately. For example, a separate
vertical degree of freedom can let a body rest on its support, or an explicit
gravity-loaded pressure pad can apply a measurable contact load. A pressure pad
adds a mass, guide and contact to the force inventory. It must remain present in
both positive and disconnected-cable controls and cannot be counted as extra
household categories or purposeful action time. Validate equilibrium, actual
load motion and the isolated intervention in the assembled scene.

## A module's clearance includes its working envelope

Two individually valid mechanisms can collide after placement. Include the
door sweep, protruding latch tabs, wheel flanges, drawer output pin, cradle and
full cart route when reserving space. Review actual collider paths, rather than
only the visible asset bounds. Preserve the original-to-assembled rigid
transform and ID map, including world joint frames and attached visuals.

A world anchor or ideal guide also needs an understandable visual mounting.
Show bearing brackets and rail seats connected to the furniture or foundation,
and disclose the ideal constraint. Visual mounting does not add a new force
source, task category or activity interval.

An invisible numerical guide must not become an accidental collider in the
mechanical chain. Keep an explicit filter inventory against the real bodies,
then inspect actual per-step callbacks to confirm the intended exclusion.
Changing the guide's size to improve its inertia can introduce an overlap far
from the visible body. Preserve genuine body, wheel, latch and ground contacts;
filtering those contacts would change the mechanism being demonstrated.

## Test both ends of a module

A cart that rolls from rest into its outgoing domino has not yet demonstrated
its input interface. Include the real upstream drawer tab, waiting latch and
all auxiliary guides in a coupled test. Preserve the intended pre-trigger quiet
interval, then check the genuine input-to-latch and body-to-output contacts.
Run the corresponding no-input scene for the same horizon. A module can pass
its output test while its input is physically pinned in the assembled scene.

For a door or latch repair, include the full moving envelope of every connected
part, including wide crossbars and protruding tabs. A collision-free centerline
or a clear final pose does not establish clearance during the motion.

## Rope equilibrium and transmission are different checks

A segmented cable can wrap a pulley and pull a load yet fail its initial quiet
state or a disconnected-end control. Examine both complete quaternion changes
and translation. Axial drift cannot be dismissed merely because the cable axis
still points in the expected direction. A loose disconnected endpoint may need
a real open support before release.

An articulated cable with extra planar bending constraints is a declared
approximation. Enumerate those constraints, preserve external pulley contacts,
and verify that cutting the single load attachment actually disconnects the
weight-to-load path. The approximation must not be presented as a freely
flexible 3D cable. A moving free pulley and contact callbacks witness contact;
they do not themselves measure tension or prove no-slip.

## Total wheel angle does not establish grounded rolling

Report each real wheel or drum independently. Similar total travel and radius
times angle can conceal long airborne intervals, backwards spin or a skewed
axle. Check the signed spin together with actual ground callbacks over the
cart's useful forward progress. Passive axle travel may permit gravity to load
the rollers; its limits, carrier masses and mounting need to be explicit.
Contact and rest offsets also belong to the physical model. Validate their
effect rather than assuming that a larger contact shell repairs load sharing.

Use the actual receiving contact to end this check. Inspect all cart parts so
that an invisible guide or carrier cannot secretly strike the outgoing domino.

## Count physical intervals and inspect transient contact

At 60 Hz, 120 consecutive samples span 119 intervals. A two-second stability
confirmation requires at least 121 samples and an explicit endpoint-time
difference of at least two seconds. Effective activity ends at the original
complete entry that remains contained; confirmation waiting adds no task time.

Check all sugar corners at every recorded step, including the first floor
impact. A final settled pose cannot erase an earlier violation. Contact/rest
offsets and solver settings are physical model parameters: disclose them and
repair the model under the original receiver bounds instead of relaxing the
case after seeing a failure.

## Keep edits, recordings and evidence distinct

An editable project is a new artifact. Preserve original run locks and failed
attempts; validate a moved project with an actual full replay, separately from
schema/export checks. Asset snapshot paths legitimately differ across runs,
but equality requires independently verified selected content and complete
dependency/runtime closures. A source URL or archive label alone is insufficient.

Measure the physical chain in simulation intervals, union simultaneous useful
motion once, and report source-film and director-cut lengths separately. Camera
motion, residual rope jitter and completed wheel spin do not extend the task.
