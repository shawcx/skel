#!/usr/bin/env python3

import sys
import os
import re
import shutil
import argparse

from jsxn import jsxn

import tornado.template


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


class Skel:
    def __init__(self):
        # resolve everything relative to this script, not the current directory
        self.root = os.path.dirname(os.path.abspath(__file__))
        self.templates = os.path.join(self.root, 'templates')

        self.args = argparser.parse_args()

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

    @classmethod
    def main(cls):
        self = cls()

        if os.path.exists(self.output) and not self.args.force:
            print(f'{self.output} already exists, use --force to overwrite', file=sys.stderr)
            return 1

        loader = tornado.template.Loader(self.templates, autoescape=None)

        for (base,directories,filenames) in os.walk(self.templates):
            for filename in filenames:
                src  = os.path.join(base, filename)
                path = os.path.relpath(src, self.templates)
                dest = self.destination(path)

                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if filename.endswith('.skel'):
                        content = loader.load(path).generate(**dict(self.project))
                        with open(dest, 'wb') as fp:
                            fp.write(content)
                    else:
                        shutil.copy(src, dest)
                except Exception as e:
                    print(f'{path}: {e}', file=sys.stderr)
                    return 1

                if self.args.verbose:
                    print(path, '=>', display(dest))

        print(f'Created {display(self.output)}')
        return 0


if '__main__' == __name__:
    sys.exit(Skel.main())
