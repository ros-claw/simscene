# Drawer and payload workspace

This model-free recipe combines one pinned USDCraft two-drawer cabinet, one
independent GSO box and two ABO notebook props. The payload's 0.12 kg mass and
the prop scale are explicit experimental assumptions. Both drawers use
scheduled, bounded position drives; no passive triggering is claimed.

1. Read `assets.lock.json`, search the indicated sources, and prepare the
   selected revisions and parameters. Supply bindings for `cabinet`, `box`
   and `book_a`; the second notebook reuses `book_a`'s prepared model.
2. Resolve `recipe.json` and `recipe-control.json` separately with the packaged
   `apply_scene_recipe.py --operations-only` helper, then apply each batch with
   MCP `scene_apply` to a separate new scene. The control removes every lower
   drawer drive command and leaves the upper schedule and other objects alone.
3. Use `freeze_recipe_case.py case.json --bindings ... --asset-lock ...
   --output ...` **once** and pass those exact case bytes to both 600-step,
   seed-42 Isaac CPU runs. The upper hold is steps 130–149, the lower hold is
   270–359, and the final observation covers steps 540–600.
4. Run `check.py --positive RUN_DIR --control RUN_DIR --case FROZEN_CASE
   --output NEW_REPORT`. It verifies input/output locks, the unique control
   difference, independent rigid body and native collider geometry, actual
   joint/pose measurements, contacts, support and final stability. Check the
   two native camera recordings and supply a separate visual review.

This example is limited to its pinned assets, sizes, measured collision cavity,
drive schedule and engine configuration. A geometric precheck or successful
asset preparation is not physical evidence; a new run needs new results. Contact
callbacks demonstrate recorded contact and do not certify that every possible
penetration was detected. Assets and large recordings are acquired separately.
