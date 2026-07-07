# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is a brand-new, empty project scaffolded by PyCharm. It currently contains only a placeholder
`main.py` (the default PyCharm "Hi" sample script) and no real application code, dependencies, tests,
or build tooling yet.

- Python 3.13 (see `.idea/misc.xml` for the configured interpreter, named `swee`)
- A `.venv` virtual environment exists at the repo root but has no packages installed beyond the
  standard library
- There is no `requirements.txt`, `pyproject.toml`, or `setup.py` — add one as soon as the project
  gains real dependencies
- There are no tests and no test runner configured yet
- There is no git history yet (no commits)

## Working in this repo

Since there is no established architecture, framework, or convention yet, do not assume any
particular structure (e.g. src layout, package name, CLI framework) — ask the user or infer it from
their first substantive request. When dependencies or a test suite are introduced, update this file
with the actual run/build/lint/test commands.
