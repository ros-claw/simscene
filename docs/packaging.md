# Development plugin packages

The package builder creates separate portable Agent Plugins, Claude Code and
DeepSeek Harness overlay roots. It bundles the SimScene Python package and MCP dependencies, but does
not bundle Isaac Sim, USD (`pxr`), robot assets or simulation data. Binary
Python wheels are specific to the builder's platform and Python version.
The bundled third-party distributions retain their own license metadata;
the repository's Apache-2.0 license applies to SimScene source code.

```sh
python3 plugins/build.py --output /absolute/path/to/new-dist
```

The builder refuses to overwrite an existing destination. If dependencies are
already installed in the active interpreter and network access is unavailable,
use `--use-installed-deps`; it verifies the installed dependency closure and
records versions in `server/dependency-lock.json`. The generated packages are
under `portable/simscene`, `claude/simscene` and `deepseek/simscene`. Building does not register or
install either plugin. Check that `python3` on the destination host matches the
build interpreter; install compatible USD Python bindings separately, and set
`SIMSCENE_ISAAC_PYTHON` to Isaac Sim's `python.sh` on the simulation host.
Some Agent clients filter the environment of MCP servers. If the server does
not see that variable, configure it in the client's MCP server environment or
run `simscene configure --isaac-python /absolute/path/to/python.sh` under the
same user and configuration directory used by the server. The same applies to
`SIMSCENE_HOME`, `SIMSCENE_CACHE` and GPU selection variables.

To install the portable files, make the skill discoverable in an existing
project and register the MCP server with the installed Codex CLI:

```sh
python3 /absolute/path/to/new-dist/portable/simscene/install.py \
  --destination /absolute/path/to/installed/simscene \
  --project /absolute/path/to/project \
  --register-codex --isaac-python /absolute/path/to/isaac-sim/python.sh
```

The installer checks its source and installed paths, refuses to overwrite an
existing destination, project skill or `simscene` MCP registration, invokes
`codex mcp add` and reads the registration back. Its result distinguishes a
copied package, a project skill and an MCP registration. It does not claim a
native marketplace plugin installation. If registration readback fails, the
result marks its state uncertain so it can be inspected with `codex mcp get
simscene --json`. Omit `--project` or `--register-codex` when those steps are
not wanted. Runtime data and cache remain outside the installed package.
An isolated Codex-home test installed the files and project skill, registered
the server, verified the actual registration and exercised the installed MCP
launcher; its records are in `evidence/installer-isolated-v15/`. This test
does not modify the user's regular Codex registration.
On the supplied workstation the current v30 portable package is installed at
`/home/dell/.local/share/simscene/plugins/simscene-v30`, the project skill is
in `.agents/skills/build-scene`, and `codex mcp add` registered its launcher
with the supplied 6.2 Python path. The readback is in
`evidence/local-install-v30/`. A live packaged MCP `environment_probe` and
observed-timing planning check are in `evidence/observed-synchronization-repair/`;
the installed v30 launcher also completed a real 120-step Isaac load/render
smoke test with intact input/output locks, recorded in `evidence/local-install-v30/`;
earlier registration records remain in `evidence/local-install-v29/`,
`evidence/local-install-v28/`,
`evidence/local-install-v27/`,
`evidence/local-install-v26/`,
`evidence/local-install-v25/`,
`evidence/local-install-v24/`,
`evidence/local-install-v23/` and
`evidence/local-install-v22/`, and v21 installation
records remain in `evidence/local-install-v21/`. This is a local MCP
registration and project skill, not a native marketplace installation.
The SimScene user defaults were also configured with that Isaac launcher for
CLI and SDK use; environment overrides still take precedence.
The current Python implementation was built into the wheel in `evidence/local-install-v30/` and
installed into `/home/dell/.local/share/simscene/venv-v30`; its `bin/simscene`
and SDK import were checked from outside the checkout. That virtual environment
uses system-site packages for its existing dependencies, including USD; it is
not an air-gapped bundle of Isaac Sim or all Python dependencies.

The portable root follows the [OpenAI plugin packaging guidance](https://developers.openai.com/plugins/build/plugins)
and the [local stdio server format](https://developers.openai.com/plugins/deploy/desktop-only).
The portable launch script and the Claude launch script have been tested as
MCP servers from a clean working directory, including USD export. This does not
prove installation in either host. An isolated Claude Code 2.1.312 host loaded
the skill and connected the packaged MCP server; the model turn stopped because
no Anthropic credential was configured. Its directory-profile validator passes
with author/icon warnings. No Codex desktop marketplace installation was tested.
A fresh Codex CLI session was also run with the bundled server and a restricted,
explicitly approved tool set; it built and exported a six-box scene from a
natural-language request. The evaluation did not use Isaac or a robot. See
`evidence/agent-codex-scene/evaluation.json` for its scope and tool outcomes.
Another fresh Codex session searched for a conveyor and made three actual
Isaac runs, using the observed stationary parcel to add a moving surface and
revise the view. It used shell commands and a repaired local copy of the online
search result; the online acquisition had not completed during the evaluation.
Its prompt, actions, output and observed displacement are in
`evidence/agent-codex-online/`. Neither test is the formal three-arm agent test.
Another session made a six-bin workbench and an orbiting camera, inspected an
initial Isaac render and reran it with a wider view. Its post-hoc independent
geometry and playback report is in `evidence/agent-codex-workbench/`. The case
was not frozen in advance and the robot was not commanded to manipulate parts.
The implementation and physical validation remain experimental.

The DeepSeek root contains `cordis.patch.yml` following the official
[MCP overlay format](https://deepseek-harness.github.io/deepseek-harness/en/guide/mcp-memory).
It references the absolute path where the package was built. After moving the
root, generate a new patch at a new path:

```sh
python3 plugins/deepseek_patch.py --plugin-root /absolute/path/to/simscene --output /absolute/path/to/new-cordis.patch.yml
dsh web --patch /absolute/path/to/new-cordis.patch.yml
```

For skill discovery, add the package's `skills` directory to the existing
`dsh-skill-filesystem` `customSkillDirs` without overwriting other configured
roots, or copy the skill into the project's `.agents/skills`. The generated
overlay only adds the MCP client; it does not alter a profile or register a
skill automatically. The packaged launcher and overlay composition were tested
with the actual DeepSeek Harness 0.2.1-rc.2. Its headless host launched the MCP
server and issued `ListTools`; the model turn could not proceed without a
DeepSeek API key. This does not establish an authenticated model session or
end-to-end tool use.

For the three supported robot models, `robot_prepare_profile` accepts the local
USD path returned after acquiring an individual asset and generates controller
files on the simulation host. The equivalent CLI is `simscene prepare-profile
MODEL ASSET_PATH`. Install compatible USD, NumPy and SciPy Python bindings on
that host (`pip install -e '.[ik]'` from this checkout supplies the latter two); the
corresponding Isaac runtime must contain NVIDIA's controller configurations.
Generated profiles are experimental, persist under `SIMSCENE_HOME/profiles`,
and require physical compatibility and collision validation; this directory is
separate from the capacity-limited asset cache.
`robot_suggest_configuration` proposes an initial follower configuration for a
base pose from a generated profile. `robot_plan_pick_cycle` proposes phase
templates for approximately 4 cm cubes with the matching grippers; neither
tool proves reachability, collision clearance or physical success.
