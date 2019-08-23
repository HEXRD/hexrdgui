# -*- coding: utf-8 -*-
import os
from setuptools import setup, find_packages, Extension

install_reqs = [
    'pyside2',
    'Pillow',
    'matplotlib',
    'importlib-resources',
    'fabio@git+https://github.com/joelvbernier/fabio.git@master',
    'pyyaml',
    'hexrd'
]

setup(
    name='hexrd-gui',
    use_scm_version=True,
    setup_requires=['setuptools-scm'],
    description='',
    long_description='',
    author='Kitware, Inc.',
    author_email='kitware@kitware.com',
    url='https://github.com/cryos/hexrdgui',
    license='BSD',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6'
    ],
    packages=find_packages(),
    package_data={'hexrd': ['ui/resources/**/*']},
    python_requires='>=3.6',
    install_requires=install_reqs,
    entry_points={
        'console_scripts': [
            'hexrd = hexrd.ui.main:main'
        ]
    }
)
