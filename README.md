# skel

Generate a Tornado web application with a Bootstrap and WebSocket frontend, or with
`--without web` a plain asyncio service.

## Usage

    ./skel.py [--namespace <namespace>] [--output <directory>] [--with <feature>,...]
              [--without <feature>,...] [--force] [-V] <Project>

    make run NAME=Slog NS=skunk     # same as ./skel.py --force --namespace skunk Slog
    make run WITH=systemd           # also passes --with systemd
    make run WITHOUT=web            # also passes --without web
    make test                       # generate projects into a temp directory and check they work
    make test-frontend              # build a project's web assets and load it in headless Chrome (needs npm)

Projects are created in `projects/<project>` unless `--output` is given. An existing
project is only overwritten with `--force`. Requires Python 3.10+ and `tornado`.

`make test` also needs `pytest`, and SQLAlchemy and aiosqlite for the `sqlite` feature. It
uses `.venv` if there is one, which can be made with:

    uv venv && uv pip install tornado "setuptools>=77" pip pytest "sqlalchemy[asyncio]" aiosqlite

The generated project has its own README. Run `make` in it to build the web assets,
which needs `npm`, then `make run`.

## values.txt

Optional `key = value` lines that fill in project metadata (`version.py`,
`pyproject.toml`, `package.json`). Supported keys are `__author__`, `__email__`,
`__license__` and `__url__`. Lines starting with `#` are ignored.

## Templates

Everything under `templates/` is copied into the new project:

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

The same keys, plus the `values.txt` keys, are available inside `.skel` templates.

A line holding only a `{% %}` tag is removed along with the tag, so blocks don't
leave blank lines in the output.

## Features

Optional features are added with `--with`, and `web` and `frontend`, which are on by
default, are left out with `--without`. Each feature is a `templates/+<feature>/`
directory, laid out like `templates/`, whose files are added to the project. A feature
can't replace a file that `templates/` or another feature creates. Shared templates
check the sorted `features` list instead:

    {% if 'systemd' in features %}
    from . import systemd
    {% end %}

A template that renders to nothing isn't created, so a feature's file can depend on
another feature by wrapping all of it in an `{% if %}`.

`DEFAULTS` and `REQUIRES` in `skel.py` list the default features and the features that
need others. Leaving out a feature also leaves out the default features that need it,
so `--without web` also leaves out `frontend`.

| Feature    | Adds                                                                          |
|------------|-------------------------------------------------------------------------------|
| `web`      | on by default: the Tornado server, handlers, page templates and a WebSocket   |
| `frontend` | on by default: Bootstrap, Font Awesome and the JS in `src/`, built with npm   |
| `auth`     | logins for every page and the WebSocket, with users added by `--add-user`     |
| `github`   | a GitHub Actions workflow that runs the tests and builds the web assets       |
| `gitlab`   | a GitLab CI pipeline that runs the tests and builds the web assets            |
| `nginx`    | `--nginx [<server_name>]`, which writes an nginx site that proxies to the app |
| `sqlite`   | a SQLite database through async SQLAlchemy, with an example model and API     |
| `systemd`  | `--systemd [<user>]`, which writes a systemd service for the app              |
