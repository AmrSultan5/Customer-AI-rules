# Configuring Acme Widgets

All configuration lives in `acme.toml` at the root of your project.

## Global settings

- `log_dir` — directory for run logs. Defaults to `./.acme/logs/`.
- `default_size` — size applied to new widgets when none is given. Defaults to `medium`.
- `default_color` — color applied to new widgets when none is given. Defaults to `blue`.

## Per-widget settings

Each widget has its own `[widgets.<name>]` table with `size`, `color`, and an
optional `entrypoint` pointing at the script to run. If `entrypoint` is omitted,
Acme looks for `main.py` in the widget's folder.

## Environment variables

Any setting can be overridden with an environment variable named
`ACME_<SETTING>` in uppercase. For example, `ACME_LOG_DIR=/var/log/acme`
overrides `log_dir` for a single run.
