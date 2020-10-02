# Develop

Requires Python 3.8+

```bash
git clone https://github.com/HEXRD/hexrd.git
git clone https://github.com/HEXRD/hexrdgui.git
```

## pip

```bash
pip install numpy
# For now we need to explicitly install hexrd, until we push it to PyPI
pip install -e hexrd
pip install -e hexrdgui
```

## conda

### Linux
```bash
# First, make sure python3.8+ is installed.
# If it is not, run the following command:
conda install -c anaconda python=3.8
# Install deps using conda package
conda install -c HEXRD -c cjh1 -c anaconda -c conda-forge hexrdgui
# Now using pip to link repo's into environment for development
pip install --no-deps -U -e hexrd
CONDA_BUILD=1 pip install --no-deps -U -e hexrdgui
```

### Mac OS
```bash
# First, make sure python3.8+ is installed.
# On OSX you will need to use the Python package from the HEXRD channel
# See the following issue for more details: https://github.com/HEXRD/hexrdgui/issues/505
conda install -c HEXRD python=3.8.4
# Install deps using conda package
conda install -c HEXRD -c cjh1 -c anaconda -c conda-forge hexrdgui
# Now using pip to link repo's into environment for development
pip install --no-deps -U -e hexrd
CONDA_BUILD=1 pip install --no-deps -U -e hexrdgui
```

### Windows
```bash
# First, make sure python3.8+ is installed.
# If it is not, run the following command:
conda install -c anaconda python=3.8
# Install deps using conda package
conda install -c HEXRD -c cjh1 -c anaconda -c conda-forge hexrdgui
# Now using pip to link repo's into environment for development
pip install --no-deps -U -e hexrd
set CONDA_BUILD=1
pip install --no-deps -U -e hexrdgui
```

# Install

## conda (release)
### Install the latest release

```bash
conda install -c hexrd -c cjh1 -c anaconda -c conda-forge hexrdgui
```

## conda (prerelease)
### Install the latest changes on master. This release may be unstable.

```bash
conda install -c hexrd/label/hexrd-prerelease -c hexrd/label/hexrdgui-prerelease -c cjh1 -c anaconda -c conda-forge hexrdgui
```

## Binary packages

Binary packages for Windows, Mac and Linux can be found attached to each [release](https://github.com/HEXRD/hexrdgui/releases)

# Run

```bash
hexrdgui
```

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
