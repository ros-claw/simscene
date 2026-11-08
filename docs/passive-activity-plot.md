# Plotting original purposeful activity

`experiments/plot_passive_activity.py` presents an accepted full report's original
per-step union flags. Its default window remains the stock release-to-entry
window. Groups must partition all frozen stage IDs exactly once; overlapping
group durations are never added together. PNG, SVG and PDF artifacts retain
source report, case, run-lock, font and output hashes.

For a full-house run with the frozen bounded-entry supplement, provide
`--entry-certificate /path/to/complete-certificate.json`. The plotter requires
verified file integrity, complete collapsed-entry/no-escape scope, the same
original full-report and run-lock hashes, and the exact complete original mask
hash. It selects only existing rows through the certified physical-entry step,
recomputes all four clock metrics and checks them against the certificate.
It never rewrites a report, synthesizes a flag or manufactures a physical pass.
The explicit bounded-clock v1 and v2 schemas are supported; the actual frozen
certificate retains authority for its matching independent examiner version.

The resulting chart marks the certified physical entry and separately shades
the original stability-confirmation wait, which earns no useful-action time.
The plot manifest also records the original stock endpoint and certificate SHA.
This remains a presentation artifact; the original suite and independent
bounded-entry report retain all acceptance authority.
