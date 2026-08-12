# Orcshot

A Linux port of [Greenshot](https://getgreenshot.org/), built as a faithful Python + GTK3
behavioral port - not affiliated with or endorsed by the Greenshot project. See
[REQUIREMENTS.md](REQUIREMENTS.md) for full scope, platform priorities, and architecture decisions.

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
