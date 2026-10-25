
import sys
import os
import re
import json
import shutil
import argparse
import subprocess
import importlib.metadata

from .jsxn import jsxn
from .version import __version__

import tornado.template

# resolve everything relative to this package, not the current directory
ROOT      = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(ROOT, 'templates')

# optional features are templates/+<feature> directories
FEATURES = sorted(name[1:] for name in os.listdir(TEMPLATES)
    if name.startswith('+') and os.path.isdir(os.path.join(TEMPLATES, name)))

# features that are on unless --without leaves them out
DEFAULTS = ['frontend', 'web']

# features that only work with other features
REQUIRES = {
    'auth'     : ['web'],
    'frontend' : ['web'],
    'nginx'    : ['web'],
    }

# features that bring others with them, which can't be chosen on their own
IMPLIES = {
    'postgres' : ['db'],
    'sqlite'   : ['db'],
    }
IMPLIED = sorted(set(f for implied in IMPLIES.values() for f in implied))

# features that can't be used together
EXCLUSIVE = [
    {'postgres', 'sqlite'},
    ]

# a {% %} tag alone on a line, but not an escaped {%! %}
TAG_LINE = re.compile(r'^[ \t]*(\{%(?!!)(?:(?!%\}).)*%\})[ \t]*\r?\n', re.M)


argparser = argparse.ArgumentParser(prog='skel')

argparser.add_argument('project',
    metavar='<project>', nargs='?',
    help='project name')

argparser.add_argument('--update',
    metavar='<directory>',
    help='update a project made by skel to the current templates, keeping its changes')

argparser.add_argument('--dry-run',
    action='store_true',
    help='with --update, show what would change without changing anything')

argparser.add_argument('--namespace',
    metavar='<namespace>', default='',
    help='parent namespace of the project')

argparser.add_argument('--output', '-o',
    metavar='<directory>',
    help='directory to create the project in, defaults to <project> in the current directory')

argparser.add_argument('--with',
    metavar='<feature>', dest='features', action='append', default=[],
    help=f'add optional features, comma separated or repeated: {", ".join(f for f in FEATURES if f not in DEFAULTS + IMPLIED)}')

argparser.add_argument('--without',
    metavar='<feature>', action='append', default=[],
    help=f'leave out features that are on by default: {", ".join(DEFAULTS)}')

argparser.add_argument('--set',
    metavar='<key>=<value>', dest='values', action='append', default=[],
    help='set a value such as author=Name, after values.txt')

argparser.add_argument('--git',
    action='store_true',
    help='make the project a git repository and commit it')

argparser.add_argument('--force',
    action='store_true',
    help='overwrite an existing project')

argparser.add_argument('--verbose', '-V',
    action='store_true',
    help='verbose output')

argparser.add_argument('--version',
    action='version', version=f'%(prog)s {__version__}')

@jsxn
class Project:
    namespace   : str
    proper_name : str
    lower_name  : str
    py_path     : str
    py_name     : str
    __author__  : str
    __email__   : str
    __license__ : str
    __url__     : str


def split(options):
    '''the features in --with or --without options, comma separated or repeated'''
    return set(f for option in options for f in option.split(',') if f)


def checkout():
    '''the top of skel's git checkout and its commit, or None when skel is installed'''
    top = os.path.dirname(ROOT)
    out = subprocess.run(['git', '-C', top, 'rev-parse', '--show-toplevel', 'HEAD'],
        capture_output=True, text=True) if shutil.which('git') else None
    if not out or out.returncode:
        return None
    toplevel,commit = out.stdout.split()
    # an installed skel can be inside some other repository, a venv in a project say
    if os.path.realpath(toplevel) != os.path.realpath(top):
        return None
    return top,commit


def installed():
    '''the repository and commit of a skel that pip installed from git, or None'''
    try:
        dist = importlib.metadata.distribution('skel')
        direct = json.loads(dist.read_text('direct_url.json') or '{}')
    except (importlib.metadata.PackageNotFoundError,ValueError):
        return None
    # the skel that's running, not another one on the path
    if os.path.realpath(dist.locate_file('skel/__init__.py')) != os.path.realpath(__file__):
        return None
    vcs = direct.get('vcs_info', {})
    if vcs.get('vcs') != 'git' or not vcs.get('commit_id'):
        return None
    return direct['url'],vcs['commit_id']


def user_values():
    '''the user's values.txt, in ~/.config/skel, or %APPDATA%\\skel on Windows'''
    base = os.environ.get('XDG_CONFIG_HOME')
    if not base and os.name == 'nt':
        base = os.environ.get('APPDATA')
    if not base:
        base = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'skel', 'values.txt')


def display(path):
    '''show paths under the current directory as relative, others as absolute'''
    try:
        rel = os.path.relpath(path)
    except ValueError:
        # on Windows there is no relative path between drives
        return path
    return path if rel.startswith('..') else rel


class Loader(tornado.template.Loader):
    '''remove a {% %} tag's line along with the tag, so blocks such as
       {% if %} ... {% end %} don't leave blank lines in the output'''
    def _create_template(self, name):
        with open(os.path.join(self.root, name), 'rb') as fp:
            text = fp.read().decode('utf-8')
        return tornado.template.Template(TAG_LINE.sub(r'\1', text), name=name, loader=self)


class Skel:
    def __init__(self, args):
        self.root = ROOT
        self.templates = TEMPLATES

        self.args = args
        if not args.project:
            argparser.error('the project name is needed')

        self.chosen  = chosen  = split(self.args.features)
        self.without = without = split(self.args.without)
        for feature in sorted(chosen | without):
            if feature not in FEATURES or feature in IMPLIED:
                choices = ", ".join(f for f in FEATURES if f not in IMPLIED)
                argparser.error(f'unknown feature: {feature}, choose from {choices}')
        for group in EXCLUSIVE:
            if len(group & chosen) > 1:
                argparser.error(f'choose one of {", ".join(sorted(group))}')
        for feature in sorted(without):
            if feature not in DEFAULTS:
                argparser.error(f'{feature} is not on by default, --without works for {", ".join(DEFAULTS)}')
            if feature in chosen:
                argparser.error(f'{feature} is in both --with and --without')

        features = set(DEFAULTS) - without | chosen
        for feature in chosen:
            features.update(IMPLIES.get(feature, []))
        # a default feature that needs a feature left out goes too, so
        # --without web also leaves out frontend
        for feature in DEFAULTS:
            if feature not in chosen and not set(REQUIRES.get(feature, [])) <= features:
                features.discard(feature)
        for feature in sorted(features):
            for needed in REQUIRES.get(feature, []):
                if needed not in features:
                    argparser.error(f'{feature} needs {needed}')
        self.features = sorted(features)

        self.project = jsxn.Project()
        # optional values from values.txt default to empty
        for key in self.project.__slots__:
            if key.startswith('__'):
                self.project[key] = ''

        # values.txt in a checkout of skel, then the user's, then --set
        self.load_values(os.path.join(os.path.dirname(self.root), 'values.txt'))
        self.load_values(user_values())
        for value in self.args.values:
            key,sep,value = value.partition('=')
            if not sep:
                argparser.error(f'--set expects <key>=<value>: {key}')
            if not self.set_value(key, value):
                argparser.error(f'unknown key for --set: {key.strip()}, choose from {", ".join(self.keys())}')

        self.project.namespace   = self.args.namespace
        self.project.proper_name = self.args.project
        self.project.lower_name  = self.args.project.lower()

        # always use / since py_path also ends up in Makefiles and .gitignore
        self.project.py_path = '/'.join(filter(None, [self.args.namespace, self.project.lower_name]))
        self.project.py_name = self.project.py_path.replace('/', '.')

        self.output = os.path.abspath(self.args.output or self.project.lower_name)

        # path components like _lower_name or _py_path are replaced with their values
        keys = sorted((k for k,v in self.project if not k.startswith('__')), key=len, reverse=True)
        self.path_re = re.compile('_(' + '|'.join(keys) + ')')

    def keys(self):
        '''the keys that values.txt and --set can set'''
        return [key.strip('_') for key in self.project.__slots__ if key.startswith('__')]

    def set_value(self, key, value):
        '''set author or __author__ and the other optional values, false for other keys'''
        key = key.strip().strip('_')
        if key not in self.keys():
            return False
        self.project[f'__{key}__'] = value.strip()
        return True

    def load_values(self, path):
        '''read key = value lines, ignoring blank lines and # comments'''
        try:
            with open(path, 'r') as fp:
                lines = fp.readlines()
        except FileNotFoundError:
            return

        for lineno,line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                key,value = line.split('=', 1)
            except ValueError:
                print(f'{path}:{lineno}: expected key = value', file=sys.stderr)
                continue
            if not self.set_value(key, value):
                print(f'{path}:{lineno}: unknown key: {key.strip()}', file=sys.stderr)

    def destination(self, path):
        '''map a path relative to the templates directory to its output path'''
        path = self.path_re.sub(lambda m: self.project[m.group(1)] or '', path)
        if path.endswith('.skel'):
            path = path[:-5]
        return os.path.join(self.output, os.path.normpath(path))

    def sources(self):
        '''yield the template path and output path of every file to create'''
        for top in [self.templates] + [os.path.join(self.templates, '+' + f) for f in self.features]:
            for (base,directories,filenames) in os.walk(top):
                if base == self.templates:
                    # features are only added when selected
                    directories[:] = [d for d in directories if not d.startswith('+')]
                # installing skel compiles the .py templates
                directories[:] = [d for d in directories if d != '__pycache__']
                for filename in filenames:
                    src = os.path.join(base, filename)
                    yield os.path.relpath(src, self.templates), self.destination(os.path.relpath(src, top))

    def commit(self):
        '''make the project a git repository with its files in a commit'''
        def git(*args):
            out = subprocess.run(['git', '-C', self.output, *args], capture_output=True, text=True)
            if out.returncode:
                raise RuntimeError(f'git {args[0]}: {(out.stderr or out.stdout).strip()}')
            return out

        git('init', '-q')
        git('add', '--all')
        # --force over a project that's already committed may change nothing
        if not git('status', '--porcelain').stdout.strip():
            print('Nothing changed to commit')
            return
        git('commit', '-q', '-m', f'Generate {self.project.proper_name} with skel\n\n'
            f'Features: {", ".join(f for f in self.features if f not in IMPLIED) or "none"}')
        print('Committed to a git repository')

    def record(self):
        '''write .skel.toml, which says how skel made the project for skel --update'''
        found = checkout()
        if found:
            # the templates of a checkout match its commit only when they're committed
            commit = found[1] if not modified(found[0]) else None
        else:
            commit = (installed() or (None,None))[1]
        values = {key:self.project[f'__{key}__'] for key in self.keys()}
        lines = [
            '# how skel made this project, skel --update reads it',
            f'version   = {json.dumps(__version__)}',
            *([f'commit    = {json.dumps(commit)}'] if commit else []),
            f'name      = {json.dumps(self.project.proper_name)}',
            f'namespace = {json.dumps(self.project.namespace)}',
            f'with      = {json.dumps(sorted(self.chosen))}',
            f'without   = {json.dumps(sorted(self.without))}',
            '',
            '[values]',
            *(f'{key:<7} = {json.dumps(value, ensure_ascii=False)}' for key,value in values.items()),
            ]
        with open(os.path.join(self.output, '.skel.toml'), 'w', encoding='utf-8', newline='\n') as fp:
            fp.write('\n'.join(lines) + '\n')

    def run(self):
        if os.path.exists(self.output) and not self.args.force:
            print(f'{self.output} already exists, use --force to overwrite', file=sys.stderr)
            return 1
        if self.args.git and not shutil.which('git'):
            print('--git needs git', file=sys.stderr)
            return 1

        # a feature adds files, it can't replace one from the base or another feature
        sources = {}
        for path,dest in self.sources():
            if dest in sources:
                print(f'{path}: {sources[dest]} already creates {display(dest)}', file=sys.stderr)
                return 1
            sources[dest] = path

        loader = Loader(self.templates, autoescape=None)

        for dest,path in sources.items():
            try:
                if path.endswith('.skel'):
                    content = loader.load(path).generate(features=self.features, **dict(self.project))
                    # a template that renders to nothing, such as one that needs
                    # a feature that isn't selected, isn't created
                    if not content.strip():
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, 'wb') as fp:
                        fp.write(content)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy(os.path.join(self.templates, path), dest)
            except Exception as e:
                print(f'{path}: {e}', file=sys.stderr)
                return 1

            if self.args.verbose:
                print(path, '=>', display(dest))

        self.record()
        print(f'Created {display(self.output)}')

        if self.args.git:
            try:
                self.commit()
            except RuntimeError as e:
                print(e, file=sys.stderr)
                return 1
        return 0


def modified(top):
    '''true if the templates or code in a checkout have changes that aren't committed'''
    out = subprocess.run(['git', '-C', top, 'status', '--porcelain', '--', 'skel'],
        capture_output=True, text=True)
    return bool(out.stdout.strip())


def main():
    args = argparser.parse_args()
    if args.update:
        if args.project:
            argparser.error('--update takes the project directory instead of a name')
        from . import update
        return update.update(args)
    if args.dry_run:
        argparser.error('--dry-run only works with --update')
    return Skel(args).run()
