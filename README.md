# skel

Generate a Tornado web application with a Bootstrap and WebSocket frontend.

## Usage

    ./skel.py [--namespace <namespace>] [--output <directory>] [--with <feature>,...] [--force] [-V] <Project>

    make run NAME=Slog NS=skunk     # same as ./skel.py --force --namespace skunk Slog
    make run WITH=systemd           # also passes --with systemd
    make test                       # generate projects into a temp directory and check they work
    make test-frontend              # build a project's web assets and load it in headless Chrome (needs npm)

Projects are created in `projects/<project>` unless `--output` is given. An existing
project is only overwritten with `--force`. Requires Python 3.10+ and `tornado`, and
`make test` also needs `pytest`.

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

Optional features are added with `--with`. Each feature is a `templates/+<feature>/`
directory, laid out like `templates/`, whose files are added to the project. A feature
can't replace a file that `templates/` or another feature creates. Shared templates
check the sorted `features` list instead:

    {% if 'systemd' in features %}
    from . import systemd
    {% end %}

| Feature   | Adds                                                                          |
|-----------|-------------------------------------------------------------------------------|
| `auth`    | logins for every page and the WebSocket, with users added by `--add-user`     |
| `github`  | a GitHub Actions workflow that runs the tests and builds the web assets       |
| `gitlab`  | a GitLab CI pipeline that runs the tests and builds the web assets            |
| `nginx`   | `--nginx [<server_name>]`, which writes an nginx site that proxies to the app |
| `systemd` | `--systemd [<user>]`, which writes a systemd service for the app              |
