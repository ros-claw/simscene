# Plugin packages

Python package version `0.2.0.dev1` is an experimental V2 candidate. The single version
source is `pyproject.toml`; the builder maps its development suffix explicitly to
plugin version `0.2.0-dev.1`. Building or installing files does not publish a
release or establish physical compatibility for arbitrary assets.

The [V2 preview release](https://github.com/ros-claw/simscene/releases/tag/v0.2.0-dev.1)
provides an unmodified Python wheel, a Linux x86_64/Python 3.10 client bundle,
checksums and artifact provenance. Use a matching Python for the binary bundle;
other supported environments can build from source or install the wheel with
their own platform dependencies. Models and SDKs are acquired separately.

Release transport removes optional local pip origin records and uses a DeepSeek
relocation template. Runtime modules, matching skills and dependency versions
are unchanged. After extracting the ZIP, generate a local DeepSeek overlay:

```sh
PYTHONPATH=deepseek/simscene/server/vendor python3 configure_deepseek.py \
  --plugin-root deepseek/simscene --output /your/new/cordis.local.yml
```

The extracted release bundle passed the client/package suite after this
documented relocation. Its portable installation completed two actual Codex
tasks: native video with full pixel/physics checks and imported GLB preparation
with a new physical run. See [qualification records](../examples/catalog_benchmark/results/release-qualification.json).

The builder preserves three layouts: portable Agent Plugins, Claude Code, and a
DeepSeek Harness overlay. Each includes the wheel's Python code, catalog source
registry, preparation decoder lock metadata, recipe registry, generation templates,
worker entry points, both project skills, and the MCP dependency closure. Third
party distributions retain their license metadata. Isaac Sim, USD (`pxr`), Node
and its optional decoder installation, Sand3D and its separate runtime, models,
asset caches, user settings, and credentials are configured outside the package.
The decoder's small lock files describe the optional toolchain; they do not install it.

Both build paths first build the same local wheel with the active interpreter.
Install the build prerequisites (`setuptools>=61`, `wheel`, `packaging>=23`) and use
a new output directory:

```sh
python3 plugins/build.py --output /absolute/path/to/new-dist
python3 plugins/build.py --output /absolute/path/to/another-dist --use-installed-deps
```

The first command resolves MCP dependencies with pip. The second copies and
validates their already installed dependency closure, then installs the local
SimScene wheel with `--no-deps --no-index`. It makes no dependency downloads;
build prerequisites must already exist. Both refuse an existing destination,
check resources and Pillow in a fresh interpreter, and retain the own-project
wheel under `wheels/`. Each client tree has `server/dependency-lock.json` and
`server/build-info.json` with versions, build mode, and wheel SHA256. These are
platform/Python-specific bundles, not universal offline runtime distributions.

A wheel can also be installed using ordinary pip:

```sh
python3 -m venv /absolute/path/to/new-venv
/absolute/path/to/new-venv/bin/python -m pip install /absolute/path/to/new-dist/wheels/rosclaw_simscene-0.2.0.dev1-py3-none-any.whl
```

That installs the base Python dependencies. It does not install Isaac or optional
backends. Compatible host USD bindings are required for USD inspection/export.
Base catalog metadata and package resources remain usable when the optional GLB
decoder and generator runtimes are unavailable; operations requiring them return
explicit dependency/runtime errors. These packaging checks do not start a simulator.

To copy portable files and matching skills into a new project installation:

```sh
python3 /absolute/path/to/new-dist/portable/simscene/install.py \
  --destination /absolute/path/to/installed/simscene-v2 \
  --project /absolute/path/to/existing-project
```

Registration is a separate explicit option. A distinct name supports parallel
installation without replacing an existing `simscene` registration:

```sh
python3 /absolute/path/to/new-dist/portable/simscene/install.py \
  --destination /absolute/path/to/another-installed/simscene-v2 \
  --register-codex --mcp-name simscene-v2 \
  --isaac-python /absolute/path/to/isaac-sim/python.sh
```

The installer refuses existing package destinations, project skills, symlinks,
and a registration with the requested name. It copies the skills' matching
`.simscene-plugin-root` marker, invokes the client's `mcp add`, and verifies that
name, executable, arguments, and requested Isaac environment value by readback.
It does not rewrite the whole client configuration. A readback failure is
reported as uncertain registration, while copied package files remain available
for inspection. Omit `--register-codex` for files-only installation; no global
client configuration changes during the ordinary build or files-only install.

Some clients filter server environment variables. Configure the desired
`SIMSCENE_ISAAC_PYTHON`, `SIMSCENE_HOME`, `SIMSCENE_CACHE`, and `SIMSCENE_V2_CONFIG`
in that client's server environment. Runtime data and source/prepared caches
must remain outside the installed package. Generation and GLB decoding require
separately admitted runtime/toolchain configurations; a cached prepared asset
does not reuse a prior physics verdict for a new scene.

If your host needs a proxy, a client may filter its environment before starting
MCP. For Codex, explicitly forward the existing variable names in that server's
configuration; do not copy proxy credentials into a public configuration:

```toml
[mcp_servers.simscene]
env_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "all_proxy", "no_proxy"]
```

The evaluator forwards these names to both packages. On the tested host, this
resolved a case where a direct metadata request worked while the MCP request
timed out. Other clients need their corresponding environment-forwarding setup.

The DeepSeek root contains `cordis.patch.yml` with the absolute build location.
After moving it, generate a new overlay at a new path:

```sh
python3 plugins/deepseek_patch.py --plugin-root /absolute/path/to/moved/deepseek/simscene --output /absolute/path/to/new-cordis.patch.yml
dsh web --patch /absolute/path/to/new-cordis.patch.yml
```

Add the package's `skills` directory to the host's existing skill directories,
or install project skills separately. The overlay adds an MCP client; it does
not install a skill or replace a host profile.

| Client | Evidence boundary |
| --- | --- |
| Portable/Codex | Final release transport: stdio, resources, cached metadata, isolated registration/readback, and two authenticated Codex tasks passed. The tasks independently checked native video/physics and real GLB preparation/physics. No desktop marketplace installation is claimed. |
| Claude Code | Packaged stdio is tested. Existing host evidence covers skill/MCP loading; no authenticated Claude model task is claimed. |
| DeepSeek Harness | Packaged stdio is tested. Existing host evidence covers overlay loading and ListTools; no authenticated DeepSeek model task is claimed. |

`tests/agent/test_package.py` clears `PYTHONPATH`, changes working directory, and
uses a new virtual environment without host site-packages for resources, cached
catalog search, and explicit missing-optional-runtime behavior. Its host-Python
checks also exercise primitive USD export when USD bindings are installed.
Final candidate builds and acceptance records are kept outside the checkout;
client loading, model tool use, and actual simulation remain separate evidence
levels. Earlier development evidence does not certify a later source snapshot.
