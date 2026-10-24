#!/usr/bin/env python3

import sys
import os
import re
import shutil
import argparse

from jsxn import jsxn

import tornado.template


# resolve everything relative to this script, not the current directory
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

# a {% %} tag alone on a line, but not an escaped {%! %}
TAG_LINE = re.compile(r'^[ \t]*(\{%(?!!)(?:(?!%\}).)*%\})[ \t]*\r?\n', re.M)


argparser = argparse.ArgumentParser()

argparser.add_argument('project',
    metavar='<project>',
    help='project name')

argparser.add_argument('--namespace',
    metavar='<namespace>', default='',
    help='parent namespace of the project')

argparser.add_argument('--output', '-o',
    metavar='<directory>',
    help='directory to create the project in, defaults to projects/<project>')

argparser.add_argument('--with',
    metavar='<feature>', dest='features', action='append', default=[],
    help=f'add optional features, comma separated or repeated: {", ".join(f for f in FEATURES if f not in DEFAULTS)}')

argparser.add_argument('--without',
    metavar='<feature>', action='append', default=[],
    help=f'leave out features that are on by default: {", ".join(DEFAULTS)}')

argparser.add_argument('--force',
    action='store_true',
    help='overwrite an existing project')

argparser.add_argument('--verbose', '-V',
    action='store_true',
    help='verbose output')

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
    def __init__(self):
        self.root = ROOT
        self.templates = TEMPLATES

        self.args = argparser.parse_args()

        chosen  = set(f for arg in self.args.features for f in arg.split(',') if f)
        without = set(f for arg in self.args.without  for f in arg.split(',') if f)
        for feature in sorted(chosen | without):
            if feature not in FEATURES:
                argparser.error(f'unknown feature: {feature}, choose from {", ".join(FEATURES)}')
        for feature in sorted(without):
            if feature not in DEFAULTS:
                argparser.error(f'{feature} is not on by default, --without works for {", ".join(DEFAULTS)}')
            if feature in chosen:
                argparser.error(f'{feature} is in both --with and --without')

        features = set(DEFAULTS) - without | chosen
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

        self.load_values(os.path.join(self.root, 'values.txt'))

        self.project.namespace   = self.args.namespace
        self.project.proper_name = self.args.project
        self.project.lower_name  = self.args.project.lower()

        # always use / since py_path also ends up in Makefiles and .gitignore
        self.project.py_path = '/'.join(filter(None, [self.args.namespace, self.project.lower_name]))
        self.project.py_name = self.project.py_path.replace('/', '.')

        if self.args.output:
            self.output = os.path.abspath(self.args.output)
        else:
            self.output = os.path.join(self.root, 'projects', self.project.lower_name)

        # path components like _lower_name or _py_path are replaced with their values
        keys = sorted((k for k,v in self.project if not k.startswith('__')), key=len, reverse=True)
        self.path_re = re.compile('_(' + '|'.join(keys) + ')')

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
            key = key.strip()
            if key not in self.project.__slots__:
                print(f'{path}:{lineno}: unknown key: {key}', file=sys.stderr)
                continue
            self.project[key] = value.strip()

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
                for filename in filenames:
                    src = os.path.join(base, filename)
                    yield os.path.relpath(src, self.templates), self.destination(os.path.relpath(src, top))

    @classmethod
    def main(cls):
        self = cls()

        if os.path.exists(self.output) and not self.args.force:
            print(f'{self.output} already exists, use --force to overwrite', file=sys.stderr)
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

        print(f'Created {display(self.output)}')
        return 0


if '__main__' == __name__:
    sys.exit(Skel.main())
