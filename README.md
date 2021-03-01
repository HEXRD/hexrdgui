# Installing

Requires Python 3.8+

### OSX

On OSX HEXRDGUI requires Python from conda-forge, to ensure it is built with the
latest SDK. See the following issue for more details: https://github.com/HEXRD/hexrdgui/issues/505.
This can be installed using the following command:

```bash
conda install -c conda-forge python=3.8
```

## conda (release)

To install the latest stable release

```bash
conda install -c hexrd -c anaconda -c conda-forge hexrdgui
```

## conda (prerelease)
To install the latest changes on master, do the following.  Note that this release may be unstable.

```bash
conda install -c hexrd/label/hexrd-prerelease -c hexrd/label/hexrdgui-prerelease -c HEXRD -c anaconda -c conda-forge hexrdgui
```

## Binary packages

Binary packages for Windows, Mac and Linux can be found attached to each official [release](https://github.com/HEXRD/hexrdgui/releases).

# Run

```bash
hexrdgui
```

# Development

Requires Python 3.8+.  First clone the Git repositories

```bash
git clone https://github.com/HEXRD/hexrd.git
git clone https://github.com/HEXRD/hexrdgui.git
```

## pip

```bash
# For now we need to explicitly install hexrd, until we push it to PyPI
pip install -e hexrd
pip install -e hexrdgui
```

## conda

### Linux
```bash
# First, make sure python3.8+ is installed in your target env.
# If it is not, run the following command:
conda install -c anaconda python=3.8
# Install deps using conda package
conda install -c HEXRD -c anaconda -c conda-forge hexrdgui
# Now using pip to link repo's into environment for development
CONDA_BUILD=1 pip install --no-build-isolation --no-deps -U -e hexrd
CONDA_BUILD=1 pip install --no-build-isolation --no-deps -U -e hexrdgui
```

### Mac OS
```bash
# First, make sure python3.8+ is installed in your target env.
# On OSX you will need to use the Python package from conda-forge
# See the following issue for more details: https://github.com/HEXRD/hexrdgui/issues/505
conda install -c conda-forge python=3.8
# Install deps using conda package
conda install -c HEXRD -c anaconda -c conda-forge hexrdgui
# Now using pip to link repo's into environment for development
CONDA_BUILD=1 pip install --no-build-isolation --no-deps -U -e hexrd
CONDA_BUILD=1 pip install --no-build-isolation --no-deps -U -e hexrdgui
```

### Windows
```bash
# First, make sure python3.8+ is installed in your target env.
# If it is not, run the following command:
conda install -c anaconda python=3.8
# Install deps using conda package
conda install -c HEXRD -c anaconda -c conda-forge hexrdgui
# Now using pip to link repo's into environment for development
set CONDA_BUILD=1
pip install --no-build-isolation --no-deps -U -e hexrd
pip install --no-build-isolation --no-deps -U -e hexrdgui
```

If you are running in Windows PowerShell or other environments where the stdout
and stderr is not appearing in the console you can run the python module directly
`python hexrdgui/hexrd/ui/main.py`, you should then see stdout and stderr.

# Packages

Packages are built for every PR push, merge into master or tag push. They are built using [GitHub Actions.](https://github.com/features/actions)

The following packages are upload as artifacts:

- `HEXRDGUI-Linux-<version>.tar.bz2` - The Linux conda package.
- `HEXRDGUI-MacOSX-<version>.tar.bz2` - The MacOSX conda package.
- `HEXRDGUI-Windows-<version>.tar.bz2` - The Windows conda package.
- `HEXRDGUI-<version>.tar.gz` - The Linux package (tarball).
- `HEXRDGUI-<version>.dmg` - The MacOS package (DMG).
- `HEXRDGUI-<version>.msi` - The Windows package (MSI).
- `HEXRDGUI-<version>.zip` - The Windows package (zip).

Note: That the packages on MacOS and Windows are not signed.

## PRs

PRs are built using the [`hexrd-prerelease`](https://anaconda.org/hexrd/repo/files?type=any&label=hexrd-prerelease) label on the [HEXRD](https://anaconda.org/hexrd) conda channel

## Merges to master

When a PR is merged into master the conda package is uploaded to the [HEXRD](https://anaconda.org/hexrd) channel using the [`hexrdgui-prerelease`](https://anaconda.org/hexrd/repo/files?type=any&label=hexrdgui-prerelease) label.

## Pushed tag

When a tag is pushed HEXRDGUI is built using the [`main`](https://anaconda.org/hexrd/repo/files?type=any&label=main) label on HEXRD conda channel and the result package is upload using the [`main`](https://anaconda.org/hexrd/repo/files?type=any&label=main) label.
