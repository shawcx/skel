# Changelog

## 0.2.0 (2026-10-24)

PostgreSQL, database migrations, a lighter frontend with live messages, and `--update`
from an installed skel.

- `--with postgres`: PostgreSQL through async SQLAlchemy and asyncpg, with the password in
  a `password_file`, and with `docker` a `db` service that the app waits for. Its tests
  run when `TEST_POSTGRES_URL` is set.
- `sqlite` and `postgres` share the models and API in a `db` feature that comes with
  either, and can't be used together.
- Database migrations with Alembic: the app brings its database up to the newest migration
  when it starts, `make migration MESSAGE="..."` writes the next one after a change to the
  models, and `make test` fails while a change has no migration. A database made by 0.1.0
  has its tables already, so mark it as migrated with
  `CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY); INSERT INTO alembic_version VALUES ('0001');`
- skel makes files with LF line endings on Windows too, which `--update` needs.
- `--update` works from an installed skel, which clones the repository it came from, and a
  skel that pip installed from git records its commit.
- Pushing a `v*` tag runs the tests and makes a GitHub release with the wheel and sdist.
- The frontend no longer uses jQuery, Backbone or Underscore. The app is an `EventTarget`,
  the server's add, update and delete messages change a `Collection`, and the scripts are
  ES modules. The bundle is 84 KB instead of 217 KB.
- With `sqlite` or `postgres`, posting to `/api/messages` sends the message to every
  WebSocket, and with the frontend the index page has a Messages card that lists them and
  shows new ones as they're posted.

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
