# Develop

Requires Python 3.6+

```bash
git clone git@github.com:/joelvbernier/hexrd3.git
git clone git@github.com:/cryos/hexrdgui.git
```

## pip

```bash
pip install numpy
# For now we need to explicitly install hexrd, until we push it to PyPI
pip install -e hexrd3
pip install -e hexrdgui
```

## conda

```bash
conda build -c cjh1 -c conda-forge conda.recipe/
conda install -c cjh1 -c conda-forge --use-local hexrdgui
```

# Run

```bash
hexrd
```
