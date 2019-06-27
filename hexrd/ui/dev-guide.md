Developer's Guide
=================

This document is written with the intention of providing an explanation
and a guide to some of the code infrastructure of hexrd-gui.

Singleton Configuration
-----------------------

Perhaps the most important design to mention is the fact that there is
a [singleton configuration](hexrd_config.py) that contains most of the
configuration of the program at any given time (except for the color
map configuration, which may also be added in the future).

All of the configuration in the `HexrdConfig` singleton is stored as a
python dictionary, but most of it is designed to be accessed as
properties. For example, if you wish to see if the canvas is to show
rings, you can check:
```
b = HexrdConfig().show_rings
```

Since the `HexrdConfig` is a `QObject` as well, it can emit signals to
inform the GUI that something needs updating. Setting some of the
properties results in `HexrdConfig()` emitting a signal. For instance,
```
HexrdConfig().show_rings = b
```
will emit a `ring_config_changed` signal. The canvas is connected to
this signal, and when it receives the signal, it re-draws the rings.

The properties' underlying functions are named with an underscore
at the beginning, and they are present so that widgets can directly
connect to them. For instance:
```
show_rings_checkbox.toggled.connect(HexrdConfig()._set_show_rings)
```

The singleton configuration also makes saving and loading settings
easy, because an entire dictionary can be saved with
`QSettings().setValue()`. This is currently done for the instrument
configuration, but not many other parts.

UI Files
--------

One nice feature of PySide2 is that UI files can be loaded at runtime.
However, this comes with a few complications. Namely, there is no
`setupUi()` function that can be called. This means that the object
that owns the widget does not need to be the type of the widget.

The design of the classes that contain widgets in this source code
are usually as follows:
```
from hexrd.ui.ui_loader import UiLoader

class SomeWidget:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('some_widget.ui', parent)
```

If some events need to be overridden, QObject.installEventFilter() can
be used.

Resources
---------

Resources are placed within the `hexrd.ui.resources` directory, and they
can be loaded like so:
```
from hexrd.ui import resource_loader
text = resource_loader.load_resource(hexrd.ui.resources.some_path,
                                     'file_name')
```

This loads resources using
[importlib_resources](https://importlib-resources.readthedocs.io/en/latest/),
which is beneficial since it is fast and can load resources even if the
python package is zipped.

Slow Processes to Avoid
-----------------------

The `Material` class in the HEXRD code will sometimes call
`_newPdata()` when its properties are changed. This function can be
slow, especially if `Material._hklMax` is very large. Thus, we generally
try to avoid the `_newPdata()` function, or any changes that will
trigger it (such as changing the space group) unless it is truly
necessary.
