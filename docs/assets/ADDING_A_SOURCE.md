# Adding an asset source

Use the curated YAML registry as the single production source inventory. Dynamic Hugging Face discovery returns candidate repositories and writes only local query snapshots. It never changes the registry, enables a provider, downloads model payloads, accepts gated terms, or executes a dataset's code.

1. Discover a small candidate set. The default budget is 20 seconds and 4 MiB of metadata, with at most two remote pages and 50 repositories. A bounded root-tree inspection is not a recursive inventory. Frozen continuation pages read the local candidate buffer and transfer no new metadata.
2. Review access, repository and per-asset licensing, file formats/codecs, object-level metadata, acquisition granularity, dependency strategy, physics declarations and existing examples separately. Unknown facts stay unknown. A public repository does not imply an unrestricted license; a repository license does not override component-specific terms.
3. Pin the full repository commit SHA before inspecting its tree or metadata entry. Branches and tags are not selection locks. Review pagination links against the exact origin, repository, revision and query. An unsupported metadata layout remains unsupported even when its filename sounds familiar.
4. Reuse an implemented adapter only after its actual schema and byte costs fit. A static candidate configuration can reuse an implemented registered adapter only at its exact reviewed revision and declared index path. Similar GLB/JSONL names in another repository do not create a new adapter. Candidate configurations are `candidate`, disabled by default, and require human code/registry review before use.
5. Implement and test the adapter boundary. Search may read bounded metadata; model, texture, archive and preview payloads require their own authorized acquisition paths. Do not use whole-repository downloads to complete a selected object. If a model is hidden in an archive, report the archive's real cost and leave range/member access unverified until measured.
6. Obtain a selected sample through a frozen acquisition plan, retain licensing and a complete hashed dependency closure, prepare its declared role, and test restoration after cache eviction. Confirm codec support in the actual converter environment. A static schema check is not a runtime test.
7. Record an actual acceptance example with its exact asset revision, preparation parameters, engine/toolchain, case, input/evidence locks and result. Include a meaningful negative control. Source admission requires implemented code and a finite integration example; it never certifies every object, variant or physics task in the source.
8. Edit the packaged registry explicitly, keep evidence scoped, and regenerate `SOURCES.md`. Do not copy the research inventory or discovery results into the enabled set wholesale.

The Python maintenance interfaces are:

```python
from simscene.catalog.discovery import discover_sources
from simscene.catalog.audit import audit_source, build_source_list

page = discover_sources("simready", {"limit": 10})
for candidate in page.candidates:
    audit = audit_source(candidate, {"usage_policy": "review"})
    # Inspect audit.to_dict(); no registry change occurs.
```

Regenerate the public list from the registry, then run its drift test:

```bash
python -c "from simscene.catalog.audit import build_source_list; print(build_source_list(), end='')" > docs/assets/SOURCES.md
python -m unittest discover -s tests -p 'test_catalog_audit.py'
```

401/403, gating, timeout, malformed JSON, unsafe pagination and exhausted budgets are observable failures, not successful empty searches. Discovery does not send credentials or automatically accept terms. Keep request ledgers and source failure evidence outside the repository; do not store credentials, signed URLs, raw model payloads or private authoring records in public docs.
