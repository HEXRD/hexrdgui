![platforms](https://anaconda.org/hexrd/hexrdgui/badges/platforms.svg) ![current version](https://anaconda.org/hexrd/hexrdgui/badges/version.svg) ![last updated](https://anaconda.org/hexrd/hexrdgui/badges/latest_release_relative_date.svg) ![downloads](https://anaconda.org/hexrd/hexrdgui/badges/downloads.svg)

![image](https://user-images.githubusercontent.com/1154130/199154866-f46c7847-9e7f-456f-9c14-962144f8958c.png)

# Installing

Requires **Python 3.10**.  Currently, we build and test `hexrdgui` exclusively with dependencies from the `conda-forge` channel.

## conda (main release)

To install the latest stable release

```bash
conda install -c hexrd -c conda-forge python=3.10 hexrdgui
```

## conda (prerelease)
To install the latest changes on master, do the following.  Note that this release may be unstable.

```bash
conda install -c hexrd/label/hexrd-prerelease -c hexrd/label/hexrdgui-prerelease -c conda-forge python=3.10 hexrdgui
```

## Binary packages

Binary packages for Windows, Mac and Linux can be found attached to each main [release](https://github.com/HEXRD/hexrdgui/releases).

# Running

For conda installs, launch by typing
```bash
hexrdgui
```
in a shell.  Binary installs are native applications that open on double-click.

# Development

Requires Python 3.10.  First clone the Git repositories

```bash
git clone https://github.com/HEXRD/hexrd.git
git clone https://github.com/HEXRD/hexrdgui.git
```

## pip

For now we need to explicitly install `hexrd`, until we push it to PyPI.  *Not currently recommended!*
```bash
pip install -e hexrd
pip install -e hexrdgui
```

## conda

First, make sure python3.10 is installed in your target env.  If it is not, run the following command:
```bash
conda install -c conda-forge python=3.10
```

Next install dependencies using the prerelease conda package
```bash
conda install -c hexrd/label/hexrdgui-prerelease -c hexrd/label/hexrd-prerelease -c conda-forge hexrdgui
```

Finally, from the directory containing the hexrd and hexrdgui git repositories, use pip to link into environment for development:

#### For Linux and Mac OS X:
```bash
CONDA_BUILD=1 pip install --no-build-isolation --no-deps -U -e hexrd
CONDA_BUILD=1 pip install --no-build-isolation --no-deps -U -e hexrdgui
```

#### For Windows:
```bash
set CONDA_BUILD=1; `
pip install --no-build-isolation --no-deps -U -e hexrd; `
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
