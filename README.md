# skel

Generate a Tornado web application with a Bootstrap and WebSocket frontend, or with
`--without web` a plain asyncio service.

## Usage

    skel [--namespace <namespace>] [--output <directory>] [--with <feature>,...]
         [--without <feature>,...] [--set <key>=<value>] [--git] [--force] [-V] <Project>
    skel --update <directory> [--with <feature>,...] [--without <feature>,...] [--dry-run]

Install the `skel` command with `pipx install git+https://github.com/shawcx/skel` (or
`uv tool install` with the same URL), which records skel's commit in the projects it makes
for `--update`, or run `./skel.py` from a checkout. In a checkout:

    make run NAME=Slog NS=skunk     # ./skel.py --force --namespace skunk --output projects/slog Slog
    make run WITH=systemd           # also passes --with systemd
    make run WITHOUT=web            # also passes --without web
    make test                       # generate projects into a temp directory and check they work
    make test-frontend              # build a project's web assets and load it in headless Chrome (needs npm)
    make test-docker                # build and run a web app and a service with docker compose

Projects are created in `<project>` in the current directory unless `--output` is given.
An existing project is only overwritten with `--force`. `--git` makes the project a git
repository and commits it, with its features in the message. Requires Python 3.11+ and
`tornado`.

`make test` also needs `pytest`, and SQLAlchemy, Alembic and aiosqlite for the `sqlite`
feature. It uses `.venv` if there is one, which can be made with:

    uv venv && uv pip install tornado "setuptools>=77" pip pytest "sqlalchemy[asyncio]" alembic aiosqlite asyncpg

`make test-docker` also runs PostgreSQL in a container, for the `postgres` feature.

The generated project has its own README. Run `make` in it to build the web assets,
which needs `npm`, then `make run`.

## Updating projects

Every project has a `.skel.toml` that records the skel version, skel's commit when it ran
from a checkout with no changes to `skel/` or pip installed it from git, and the name,
namespace, features and values.
`skel --update <directory>` reads it and renders the project twice, with the skel that made
it and with the current one, and then brings the difference into the project:

- files that only skel changed are updated, and new ones are added
- files that only the project changed are kept
- files that both changed are merged with `git merge-file`, and lines changed on both
  sides get conflict markers, which make `--update` exit with 1
- files that skel no longer makes are kept

`--with` and `--without` add or remove features as part of the update, and `--dry-run`
shows what would change. It needs git, to get the old templates at the recorded commit, or
the tag `v<version>` when there isn't one. A checkout of skel has them in its history, and
an installed skel clones the repository that pip installed it from, or GitHub's.

## Values

Optional values fill in project metadata (`version.py`, `pyproject.toml`, `package.json`):
`author`, `email`, `license` and `url`. They're read in this order, later ones winning:

- `values.txt` in a checkout of skel
- `~/.config/skel/values.txt`, or `%APPDATA%\skel\values.txt` on Windows
- `--set <key>=<value>` options

The files have `key = value` lines, and lines starting with `#` are ignored. Keys can be
written with or without the underscores, `author` or `__author__`.

## Templates

Everything under `skel/templates/` is copied into the new project:

- Files ending in `.skel` are rendered as Tornado templates and the suffix is dropped.
  Use `{{! ... }}` and `{%! ... %}` to emit template syntax into the output,
  for example in the generated HTML templates.
- Other files are copied as-is.
- `_<key>` in a file or directory name is replaced with that value:

| Key           | `Slog` with `--namespace skunk` |
|---------------|---------------------------------|
| `proper_name` | `Slog`                          |
| `lower_name`  | `slog`                          |
| `namespace`   | `skunk`                         |
| `py_path`     | `skunk/slog`                    |
| `py_name`     | `skunk.slog`                    |

The same keys, plus the values as `__author__` and so on, are available inside `.skel` templates.

A line holding only a `{% %}` tag is removed along with the tag, so blocks don't
leave blank lines in the output.

## Features

Optional features are added with `--with`, and `web` and `frontend`, which are on by
default, are left out with `--without`. Each feature is a `skel/templates/+<feature>/`
directory, laid out like `skel/templates/`, whose files are added to the project. A feature
can't replace a file that `skel/templates/` or another feature creates. Shared templates
check the sorted `features` list instead:

    {% if 'systemd' in features %}
    from . import systemd
    {% end %}

A template that renders to nothing isn't created, so a feature's file can depend on
another feature by wrapping all of it in an `{% if %}`.

`DEFAULTS` and `REQUIRES` in `skel/__init__.py` list the default features and the features that
need others. Leaving out a feature also leaves out the default features that need it,
so `--without web` also leaves out `frontend`. `IMPLIES` lists features that bring others
with them, such as `sqlite` and `postgres`, which both bring `db` with the models,
migrations and API they share, and `EXCLUSIVE` the ones that can't be used together.

| Feature    | Adds                                                                          |
|------------|-------------------------------------------------------------------------------|
| `web`      | on by default: the Tornado server, handlers, page templates and a WebSocket   |
| `frontend` | on by default: Bootstrap, Font Awesome and the JS in `src/`, built with npm   |
| `auth`     | logins for every page and the WebSocket, with users added by `--add-user`     |
| `docker`   | a Dockerfile and compose.yaml that run the app as a locked-down container     |
| `github`   | a GitHub Actions workflow that runs the tests and builds the web assets       |
| `gitlab`   | a GitLab CI pipeline that runs the tests and builds the web assets            |
| `nginx`    | `--nginx [<server_name>]`, which writes an nginx site that proxies to the app |
| `postgres` | PostgreSQL through async SQLAlchemy, with a `db` service when using docker    |
| `sqlite`   | SQLite through async SQLAlchemy, with Alembic migrations, a model and an API  |
| `systemd`  | `--systemd [<user>]`, which writes a systemd service for the app              |

## Releasing

Set the version in `skel/version.py`, rename the changelog's `Unreleased` section to the
version and date, commit, and push a tag like `v0.2.0`. `release.yml` runs the tests, checks
that the tag matches the version and that `CHANGELOG.md` has notes for it, then makes a
GitHub release with the wheel and sdist. Afterwards, set the version to the next `.dev0`.
