# Activity plotting with the composed-mechanism entry certificate

`python -m experiments.plot_passive_activity_v4` is an additive presentation
entry point accepting the explicit `simscene.bounded_entry_clock.v4` certificate.
The original `plot_passive_activity.py` and its v2 freeze remain byte-identical.
The only source difference is the admitted schema name; a regression checks the
complete source bytes after that single literal replacement.

Use `--entry-certificate` with the independent complete certificate for the same
accepted individual report and original run lock. The reader still requires
collapsed entry bounds, no escape, all timing floors, complete file verification,
the exact full original mask hash and interval, and the independently recomputed
four prefix metrics. It selects existing rows only. It neither changes masks nor
produces a physical verdict. Unknown schemas and incomplete certificates fail.

The global case's explicit act partition supplies the figure rows. Stable waiting
time stays outside useful activity. See [the original plotting guide](passive-activity-plot.md)
for arguments and output formats.

The separate v3 entry point and freeze are preserved unchanged.
