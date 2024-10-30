# -*- coding: utf-8 -*-
import os
from setuptools import setup, find_packages, Extension

install_reqs = [
    'hexrd',
    'fabio>=0.11',
    'matplotlib',
    'Pillow',
    # PySide 6.8.0 is causing segmentation faults in the testing
    # Keep this version downgraded until that is fixed.
    'pyside6<6.8.0',
    'pyyaml',
    'silx',
]

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
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    packages=find_packages(),
    package_data={'hexrdgui': ['resources/**/*']},
    python_requires='>=3.10',
    install_requires=install_reqs,
    entry_points={
        'gui_scripts': [
            'hexrdgui = hexrdgui.main:main'
        ]
    }
)
