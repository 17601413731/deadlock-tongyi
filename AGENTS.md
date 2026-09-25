# Repository Guidelines

## Project Structure & Module Organization

`dlchat/` contains the Python translation bridge, launcher, configuration, and translation logic. `mod/panorama/` holds the in-game JavaScript, XML layouts, and CSS. `data/` contains terminology and phrase files; `scripts/` has build, diagnostic, and data-maintenance tools. Python tests live in `tests/test_*.py`, while `scripts/js_check.js` exercises the Panorama mod offline. See `docs/` for protocol, build, and data details. Generated packages belong in the ignored `build/` directory.

## Build, Test, and Development Commands

Use Python 3.10 or newer on Windows. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python scripts\run_bridge.py --no-warmup
```

The last command starts the local bridge, normally on port 8791. To build the mod, run `python scripts\stage_compile.py --pack`; it requires the CSDK 12 toolchain described in `docs/mod-build.md` and writes `build/tongyi-pak01_dir.vpk`. For the complete player ZIP, follow the ordered PyInstaller and packaging commands in `README.md`.

## Coding Style & Naming Conventions

Follow nearby code: Python uses four-space indentation, `snake_case` for functions/modules, and `PascalCase` for classes. The Panorama runtime script uses tabs; the Node test harness uses two spaces. Preserve existing JavaScript/XML entry-point names and bridge request fields because the mod and server share a strict protocol. No repository-wide formatter or linter is configured.

## Testing Guidelines

Run `python -m unittest discover -s tests -t .` for the standard-library test suite. Run `node scripts/js_check.js` after changing Panorama JavaScript, layouts, or styles; the mod build also uses this check. Run `python scripts\check_data_quality.py` after editing terminology or phrase data. Add focused `test_*.py` cases for bridge or translation changes, keep tests offline, and isolate user settings with temporary directories. There is no stated coverage percentage requirement.

## Commit & Pull Request Guidelines

Recent commits use short, action-focused Chinese subjects, sometimes with a scope prefix such as `README:`. Keep each commit focused. In pull requests, describe the player-visible change, list the checks run, link a relevant issue, and include screenshots for visual mod changes.

## Configuration & Data

Keep API keys and local overrides out of Git; use the local settings page or ignored `config.local.yaml`. Do not hand-edit generated `data/glossary.json`, `data/phrases.json`, `data/templates.json`, or `data/gamenames.json`; update their generating scripts and rerun the data checks.
