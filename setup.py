# -*- coding: utf-8 -*-
import os
import platform
from setuptools import setup, find_packages, Extension

install_reqs = [
    'hexrd',
    'fabio>=0.11',
    'matplotlib',
    'Pillow',
    'pyside6',
    'pyyaml',
    'silx',
]

if platform.system() == 'Darwin':
    # This is needed to fix the application name on Mac
    install_reqs.append('pyobjc-framework-cocoa')

setup(
    name='hexrdgui',
    use_scm_version=True,
    setup_requires=['setuptools-scm'],
    description='',
    long_description='',
    author='Kitware, Inc.',
    author_email='kitware@kitware.com',
    url='https://github.com/hexrd/hexrdgui',
    license='BSD',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
    ],
    packages=find_packages(),
    package_data={'hexrdgui': ['resources/**/*']},
    python_requires='>=3.10',
    install_requires=install_reqs,
    entry_points={'gui_scripts': ['hexrdgui = hexrdgui.main:main']},
)
