# Box halfspace observer with the v41 reader

`experiments/box_halfspace_observation_v2.py` is the explicit
`simscene.box_halfspace_observation.v2` counterpart of the frozen v1 observer.
It changes only the public observation schema and the pinned network reader
SHA256 to `0ed9160f0225bcba3e621c2b22ce0a36720ca67203cb29330883abfd99a1adc1`.
The ce05 mechanism reader, geometry predicates, original-step handling,
earliest-entry rule, escape checks, file locks and CLI behavior are identical.
A source-identity regression enforces that two-substitution boundary.

The [original observation specification](box-halfspace-observation.md) applies
with the v2 schema and filename. Existing v1 code, evidence and freeze manifests
keep their original bytes and reader. The unchanged v1 guard rejects the new
reader; its legacy file tests use the exact archived original reader. The
complete geometry and file adversarial tests also run against v2.

The generic v2 source/tests and the actual independent static plane declaration
must be frozen before any formal run or candidate observation query. Original
run/evidence hashes must come from independent verified custody records. This
remains an additive geometry observation: it supplies neither physical suite
acceptance, measured cavity equivalence, stability nor between-step proof.
