# Typed gravity support evidence

Read this when a passive network includes a gravity-loaded support/friction pad
that must remain quiet while supporting a task-path body. The declaration is
`structural_loads` in `simscene.passive_network.v2` or its D6 extension v3.
It does not grant the pad an activation event or effective-action seconds.

Each pad declares `kind: gravity_loaded_support_pad`, `guide_joint_id`,
`support_body_id`, `support_motion_event`, the pad/support Box part indices,
`gravity_direction_world: [0,0,-1]`, and frozen thresholds. A primitive Box uses
a null part index; a compound uses a zero-based colliding Box part index.

Use an initially present dynamic pad with explicit positive mass and one
colliding Box. Its sole joint is an enabled undriven world-to-pad prismatic
guide, parallel to gravity and initially away from both limits. The actual
dynamic support must belong to the task path. A static shelf, clamped guide,
extra joint or active body cannot substitute for this load path.

Require the entire initial pad footprint to lie inside the selected support,
with margin covering both bodies' quiet-motion budgets and frame tolerance.
Freeze seating steps, contact/penetration bounds, guide clearance and tilt
tolerance before running. The initial hold must cover seating plus two steps;
do not invent the seating window after observing success.

The read-only checker uses every original physical step: opposing support-face
geometry, actual contacts, penetration, gravity alignment, guide freedom,
support-event identity and the pad's declared quiet bounds. Missing evidence
fails admission. It measures neither calibrated normal force nor cable tension.

Use `run_verify` on the complete network case and its stopping controls. This
local assertion cannot accept the whole scene or waive passive, causal, quiet,
terminal and timing checks. See
[network verification](passive-network-verification.md) for the surrounding case.
