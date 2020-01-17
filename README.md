# Develop

Requires Python 3.6+

```bash
git clone git@github.com:/HEXRD/hexrd.git
git clone git@github.com:/HEXRD/hexrdgui.git
```

## pip

```bash
pip install numpy
# For now we need to explicitly install hexrd, until we push it to PyPI
pip install -e hexrd
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
