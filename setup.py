# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

install_reqs = [
    'pyside2',
    'Pillow',
    'matplotlib',
    'importlib-resources',
    'fabio'
]

setup(
    name='hexrd',
    use_scm_version=True,
    setup_requires=['setuptools-scm'],
    description='',
    long_description='',
    author='Kitware, Inc.',
    author_email='kitware@kitware.com',
    url='https://github.com/cryos/hexrd',
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
    python_requires='>=3.6',
    install_requires=install_reqs,
    entry_points={
        'console_scripts': [
            'hexrd = hexrd.main_window:main'
        ]
    }
)
