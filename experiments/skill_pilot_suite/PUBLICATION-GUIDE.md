# Reusing the historical pilot

This directory publishes the original task contracts, scoring code, redacted
results and token summaries. The [file manifest](PUBLICATION-MANIFEST.json)
lists the distributed files. Raw model sessions, account metadata, full SDKs,
worker copies and private run directories are excluded.

The original four arms remain **0/4 on-budget protocol passes**. Supplemental
v2 scoring reads the same observations after two interface corrections; it is
not a new trial or a replacement for the original verdict. See the
[result summary](results/REVIEW.md).

For a new experiment, freeze a new runtime identity, installed package and
actual cache configuration, then use fresh directories and a bounded budget.
Keep the original design and supplemental scorer versions separate. Historical
run locks include host-specific paths; changing those paths does not recreate
the original custody check. The frozen v43 runtime and raw historical
observations are not distributed here, so this repository alone cannot rerun
the historical jobs byte for byte.

These two tasks are public examples, not new blind tasks. For the V2 catalog
study, use the separate [protocol and measured scope](../../docs/validation/catalog-efficiency.md).
