# Source and asset evidence

Source lifecycle, content acquisition, preparation and physical verification describe different facts.

| Source state | Meaning |
|---|---|
| `candidate` | Found or statically described; not admitted for ordinary search. |
| `audited` | Static source review exists; explicit selection may use the implemented development adapter and is marked experimental. |
| `enabled` | An implemented adapter passed finite integration examples. Default search includes it only when `default_enabled` is true. |
| `quarantined` | Withheld because of a specific fault or unresolved risk. |
| `reference_only` | Informational reference, not an operational asset source. |

Discovery always returns candidate repositories. A repository count is not a prepared-asset count. Dataset rows, renders, material variations, LODs and mirrored files are not unique-object counts. Similar titles or geometry do not establish common provenance.

| Asset fact/evidence | What it establishes |
|---|---|
| `unknown` / null | The fact has not been established. It cannot satisfy a strict required capability. |
| `declared` | An upstream card, metadata entry or explicit recipe states the value. Manufacturer facts and experimental assumptions must remain distinguishable. |
| `inspected` | A bounded static inspection of the selected content established a particular fact. This does not prove runtime behavior. |
| `runtime_verified` | A locally executed case verified a named behavior for a particular asset version, preparation recipe and actual backend/toolchain. |

An upstream benchmark or claim is `upstream_reported`; it is not a locally executed acceptance record. An audit may retain the declaration but never upgrade it to local physical evidence.

A content lock records the exact selected files, hashes, paths, origins and notices. A successful download does not establish a complete dependency closure. Missing dependencies or unavailable USD tools remain incomplete/unverified. HTTP cache ETags are not SHA-256 content identities.

A prepared package is a derived, traceable asset. Its static schema, metres/Z-up convention, body map and collision report can be inspected while runtime validation remains `not_run`. A visual-only import has no dynamic-physics guarantee. A joint count does not establish usable joint limits/drives. One convex hull does not establish a container's open cavity.

A physical pass binds the selected source revision/content, preparation parameters, actual engine versions, frozen case and input/evidence locks. Repeated clean initialization of one layout establishes repeatability, not layout generalization. Rendered pictures and successful video encoding do not establish physics. Performance or token improvements require a separate matched measurement; source admission makes no such claim.

See [SOURCES.md](SOURCES.md) for the exact scope and limitations of each admitted example, and [ADDING_A_SOURCE.md](ADDING_A_SOURCE.md) for the review path. License/access failures remain separate from geometry and physics quality.
