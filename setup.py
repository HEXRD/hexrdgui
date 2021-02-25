# -*- coding: utf-8 -*-
import os
from setuptools import setup, find_packages, Extension

install_reqs = [
    'Pillow',
    'matplotlib',
    'importlib-resources',
    'fabio>=0.11',
    'pyyaml',
    'hexrd@git+https://github.com/hexrd/hexrd.git@master',
    'silx'
]

# This is a hack to get around the fact that pyside2 on conda-forge doesn't install
# dist info so setuptools can't find it, even though its there, which results in
# pkg_resources.DistributionNotFound, even though the package is available. So we
# only added it if we aren't building with conda.
if os.environ.get('CONDA_BUILD') != '1':
    install_reqs.append('pyside2')

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
        'Programming Language :: Python :: 3.8'
    ],
    packages=find_packages(),
    package_data={'hexrd': ['ui/resources/**/*']},
    python_requires='>=3.8',
    install_requires=install_reqs,
    entry_points={
        'gui_scripts': [
            'hexrdgui = hexrd.ui.main:main'
        ]
    }
)
