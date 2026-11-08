# Preparing and observing imported physical objects

`asset_plan(ref, profile_id, parameters, budget_bytes)` freezes a selection,
normalized experimental assumptions, observed runtime and transfer/staging
limits. A blocked plan gives concrete reasons; do not bypass unresolved license,
missing codec, unknown units or unsupported collision. Runtime probing and the
optional decoder installation are explicit setup steps. Search/plan never start
conversion or physics. Keep the basic MCP environment separate from Isaac and
optional Blender backends.

`asset_prepare(plan_id, request_id)` returns a durable job. Reconnect to the same
job/request after a timeout, and inspect compact status or use machine-side wait
with a new receipt file. An uncertain launch is not permission to start another.
Keep failed attempts and partial byte accounting. Changed physics parameters
need a new plan/preparation identity; warm source bytes may still be reused.

For a completed rigid preparation, the ordinary scene object uses:

```json
{"kind":"asset","asset_path":"<result.root>","dynamic":true,"collision":true,
 "asset_binding":{"manifest_path":"<result.manifest_path>",
                  "manifest_sha256":"<result.manifest_sha256>"}}
```

The binding has exactly these two keys. Scene transforms are metre positions
and normalized `orientation_wxyz`. Prepared scale, mass, collider and materials
are immutable; reprepare to change them. A recipe's mass is an experimental
assumption unless independently measured. A single convex hull can seal a cup
or fill an opening; reject unsuitable geometry rather than loosening acceptance
until it passes.

Observe the mapped nested rigid body, its actual visual bounds and real contact
actors, not just the stationary imported wrapper. Freeze a small case before
running: measurable gravity displacement, intended support contact, complete
target containment and settling. Include a missing-support/contact negative
control. Recheck input and evidence integrity. Runtime settings readback is
not independent device telemetry, and prepared `not_run` never becomes a pass
merely because conversion completed. Keep the verdict attached to the actual
run and exact preparation pin.

A render-only edit can reuse retained source footage. A different layout or
physical profile needs its own relevant run; an old case pin cannot certify it.
Restore an exact old package only from retained lock evidence, never by
self-hashing a changed manifest.

For retained native joints, an open receiver or HDRI lighting, read
[native asset roles](native-assets.md) before choosing the preparation profile.
