# Code, assets and generated content

SimScene code is Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Python dependency versions and the built wheel hash are recorded in each
plugin's `server/` build receipts. Optional Isaac Sim, Node/GLB decoding and
Sand3D runtimes are installed separately under their own terms.

The repository distributes recipes, references, tests and selected rendered
outputs. It does not bundle downloaded models, textures, vendor SDKs or complete
simulation-host caches. Rendered examples do not transfer model licenses.

| Selected source | Declared terms / attribution | Limits |
|---|---|---|
| NVIDIA USD Search / Isaac workbench | Original NVIDIA content terms; exact source URL in the example lock | Search software licensing is separate. The selected asset's individual license is unresolved; the new planning route blocks it. Existing visual-only compatibility examples assert no redistribution grant. |
| [ABO GLB conversion](https://huggingface.co/datasets/codepawl/abo-glb) | CC-BY-4.0 declaration; preserve conversion and upstream Amazon Berkeley Objects attribution and notices | Experimental resize and mass are preparation assumptions. |
| [GSO GLB conversion](https://huggingface.co/datasets/codepawl/scanned-objects-glb) | CC-BY-4.0 declaration; preserve conversion and Google Scanned Objects attribution and notices | Only the pinned standard GLB variant was tested. |
| [USDCraft](https://huggingface.co/datasets/nvidia/USDCraft-10K) | Apache-2.0 declaration; preserve NVIDIA source metadata and notices | A selected single-hinge model was tested; the dataset name is not a usable-model count. |
| [ProjectSim public samples](https://huggingface.co/datasets/projectsim/simready-assets) | Selected valve package descriptor declares CC-BY-4.0; preserve package author/descriptor/BOM attribution | Repository-wide license remains unresolved. Only that pinned visual package is admitted; no vendor-conformance claim. |
| [Poly Haven](https://polyhaven.com/) | Selected HDRI declares CC0-1.0; source ID and file hashes remain in the preparation package | Configured IDs and selected resolution only. |
| [Sand3D](https://github.com/Sandflow-ai/sand3d) | Separate reviewed generator runtime and its upstream license; template/program identity retained | The shipped trusted templates do not execute arbitrary downloaded programs. |

Actual prepared packages retain source identity, source-file inventories,
license evidence and local notices. Check those records before distributing a
scene or its dependencies. The [source registry](docs/assets/SOURCES.md) records
admission separately from per-asset physical suitability.
