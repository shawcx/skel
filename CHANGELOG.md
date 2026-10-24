# Changelog

## Unreleased

- `--with postgres`: PostgreSQL through async SQLAlchemy and asyncpg, with the password in
  a `password_file`, and with `docker` a `db` service that the app waits for. Its tests
  run when `TEST_POSTGRES_URL` is set.
- `sqlite` and `postgres` share the models and API in a `db` feature that comes with
  either, and can't be used together.

## 0.1.0 (2026-10-24)

The first release. skel generates a project built on the ideas of _.py, without needing
_.py, and can update it later.

- A Tornado web app with a Bootstrap and WebSocket frontend built with esbuild and sass,
  or a plain asyncio service with `--without web`, or a web app without npm with
  `--without frontend`.
- Settings from layered ini files, a `prefix` for running behind a reverse proxy, JSON
  handlers that encode bytes, UUIDs and datetimes, and exit code 1 on errors.
- pytest tests and a Makefile with `make venv`, `run`, `test` and `dist`, which also work
  on Windows.
- Optional features: `auth` (logins, users and sessions that survive a restart),
  `docker`, `github`, `gitlab`, `nginx`, `sqlite` and `systemd`.
- `.skel.toml` in every project, and `skel --update` to merge newer templates into it.
- `skel` installs with pipx or `uv tool install`, takes values from
  `~/.config/skel/values.txt` and `--set`, and can commit the new project with `--git`.
