# Contributing to SimScene

SimScene is a development-stage scene composition and simulation plugin.
Please keep changes small and describe both expected behavior and validation.

## Development setup

Use Python 3.10 or newer in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[ik,build]' usd-core 'pytest>=8,<10'
python -m pytest tests --ignore=tests/agent -q
python -m unittest discover -s tests/agent -p 'test*.py'
```

CPU tests cover contracts, generated USD fixtures and selected small test data.
Pytest also collects function-style replay tests that unittest discovery alone
does not execute. These suites do not download robot models or start Isaac Sim. Some integration tests
under `tests/agent` build packages or invoke an installed client; run those
when changing the corresponding integration. SDK-dependent checks are opt-in and require a compatible Isaac installation
and GPU; ordinary CPU CI does not establish physical success.

Build a portable plugin without registering it:

```bash
python plugins/build.py --output /absolute/path/to/new-dist --use-installed-deps
```

See [packaging](docs/packaging.md) for installation and client-specific details.

## Changes and evidence

- Preserve stable object IDs, revision checks and request idempotency.
- Treat search results and IK solutions as candidates requiring inspection.
- Keep requested/actual physics steps and process-exit state distinct.
- Preserve failures; never present an amended post-hoc checker as a frozen test.
- Changing criteria requires a new documented case, frozen before a new run.
- Separate protocol mocks, real physical tests and fresh-agent acceptance.
- Do not commit credentials, caches, raw agent transcripts, installed vendor
  trees or downloaded third-party models and textures.

See [public validation scope](docs/validation.md) before adding validation data.

