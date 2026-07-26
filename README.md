# Greenshot Linux

A Linux Mint (Cinnamon) port of [Greenshot](https://getgreenshot.org/), built as a faithful
Python + GTK3 behavioral port. See [REQUIREMENTS.md](REQUIREMENTS.md) for full scope, platform
priorities, and architecture decisions.

## Development setup

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Requires system packages for building PyGObject: `libcairo2-dev`, `libgirepository-2.0-dev`,
`libgtk-3-dev`.

## Running tests

```
.venv/bin/pytest
```
