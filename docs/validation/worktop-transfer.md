# Reusing the first-delivery worktop

The worktop transfer trials reuse the [released first-delivery
recipe](../../examples/first_delivery/README.md) with selected ABO and GSO
objects. The support is an editable, static collision-enabled box with a
horizontal 0.66 × 0.50 m top at 0.72 m. The trials use 240 steps at 60 Hz and
seed 42. Imported props use an explicit convex-hull profile and a 0.12 kg
experimental mass. The initial body height and the asset pins are frozen for
each pose before running.

## Recorded trials

| Tested prop | Observed XY envelope around worktop center | Vertical drop | Direct worktop callbacks |
| --- | ---: | ---: | ---: |
| GSO Ready-to-Use Rolled Fondant box | 90.7 × 240.4 mm | 234.8 mm | 24 (steps 13–36) |
| AmazonBasics Classic Blank Notebook | 89.5 × 150.0 mm | 232.5 mm | 25 (steps 12–36) |
| Crunch Girl Scouts Peanut Butter Creme carton | 151.1 × 149.1 mm | 234.8 mm | 24 (steps 13–36) |

All three pinned runs passed their independent gravity, direct contact, final
bounds and settling checks. Profile parameters and raw run hashes are in the
observations. In the two transfer runs, the prepared prop was placed at the
measured center with a 232.5 mm bottom clearance. Both used the same support
and thresholds as the release trial after freezing the exact object pins and
its initial body-origin height.

The first cold notebook catalog query exhausted its 12-second budget before
any model acquisition. A separate retry completed the metadata query within
45 seconds and produced the recorded notebook result.

## Select for a measured support

A build from the current source exposes the resource template

```text
simscene://recipes/worktop-fit/{width_m}/{depth_m}/{edge_clearance_m}
```

For example, read `simscene://recipes/worktop-fit/0.30/0.24/0.02` to look for
poses that fit a 0.30 × 0.24 m usable rectangle with a 20 mm margin on every
edge. Use the measured unobstructed rectangle of a level, static support with
collision enabled. Width and depth follow the pose axes in the evidence.

The filter compares this rectangle with the measured XY envelope around the
original worktop center. The envelope includes the initial and every recorded
physics sample for that pose. Matches retain the source revision, preparation
parameters and tested pose. The contact and settling entries refer to the
recorded worktop and run. Apply the recorded orientation and offset from
the usable rectangle center. If that rectangle is a subregion of the support,
convert the center and offset to the support-local coordinates used by
`place_on`. Confirm the placement with `scene_measure` and verify a new run.

The filter runs locally and performs no catalog downloads. The checked-in
[observations](../../src/simscene/recipes/data/worktop-support.json) contain
finite cases with measured motion and support. The dev2 download provides the
original GSO first-delivery recipe. The fit resource is a post-release addition
to the source branch.
