#!/usr/bin/env python3
from __future__ import print_function

import sys
import os
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

argparser.add_argument('--force',
    action='store_true',
    help='verbose output')

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


class Skel:
    def __init__(self):
        self.root = os.path.abspath(os.getcwd())

        self.args = argparser.parse_args()

        self.project = jsxn.Project()

        try:
            with open('values.txt', 'r') as fp:
                key,value = fp.readline().split('=')
                key = key.strip()
                value = value.strip()
                self.project[key] = value
        except NotImplementedError:
            pass

        self.project.namespace   = self.args.namespace
        self.project.proper_name = self.args.project
        self.project.lower_name  = self.args.project.lower()

        self.project.py_path = os.path.join(self.args.namespace, self.project.lower_name)
        self.project.py_name = self.project.py_path.replace(os.path.sep, '.')

    @classmethod
    def main(cls):
        self = cls()

        template_directory = os.path.join(self.root, 'templates')
        loader = tornado.template.Loader(template_directory)
        trim = len(template_directory) + 1

        for (base,directories,filenames) in os.walk(template_directory):
            for filename in filenames:
                path = os.path.join(base, filename)[trim:]

                dest = os.path.join(self.root, 'projects', self.project.lower_name, path)
                for key,value in dict(self.project).items():
                    dest = dest.replace(f'_{key}', value)

                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                except OSError as e:
                    print(e)
                    continue

                if filename.endswith('.skel'):
                    dest = f'{dest[:-5]}'
                    content = loader.load(path).generate(**dict(self.project))
                    print(path, '=>', dest[len(self.root)+1:])
                    open(dest, 'wb').write(content)
                    continue
                else:
                    shutil.copy(os.path.join('templates',path), dest)
                    print(path, '=>', dest[len(self.root)+1:])
                    continue

        return 0


if '__main__' == __name__:
    sys.exit(Skel.main())
