# skel

Generate a Tornado web application with a Bootstrap and WebSocket frontend.

## Usage

    ./skel.py [--namespace <namespace>] [--output <directory>] [--force] [-V] <Project>

    make run NAME=Slog NS=skunk     # same as ./skel.py --force --namespace skunk Slog
    make test                       # generate a project into a temp directory and check it works

Projects are created in `projects/<project>` unless `--output` is given. An existing
project is only overwritten with `--force`. Requires Python 3.10+ and `tornado`.

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
