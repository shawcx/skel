#!/usr/bin/env python3

import setuptools

exec(compile(open('{{ py_path }}/version.py').read(),'version.py','exec'))

setuptools.setup(
    name                 = '{{ proper_name }}',
    author               = __author__,
    author_email         = __email__,
    version              = __version__,
    license              = __license__,
    url                  = __url__,
    description          = __description__,
    long_description     = open('README.md').read(),
    packages             = setuptools.find_packages(),
    include_package_data = True,
    zip_safe             = False,
    install_requires = [
        'tornado',
        ],
    )
