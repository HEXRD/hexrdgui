# Creating conda environment to build package

```
cd <hexrdgui_repo>/packaging
conda env create -f environment.yml
conda activate hexrdgui-package
```

# Building the package

```
cd <hexrdgui_repo>/packaging
cpack

```