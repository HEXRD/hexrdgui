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

Currently, there are three main keys for the configuration:
```
instrument: contains the instrument config used by hexrd
materials: contains materials settings and the loaded materials
resolution: contains resolution settings
```

No additional keys should be added to `instrument`, because it is
supposed to be exactly what is passed to the `hexrd` source code.

However, additional keys can be added to `materials` and `resolution`
as needed. Additional main keys can be added as well, when more
generic categories are needed.

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

Central Widget
--------------

The central widget is currently `ImageTabWidget`, a subclass of
`QImageTabWidget`. Then, `ImageCanvas`, which subclasses from the
matplotlib `FigureCanvas`, make up the tabs.

Often, there will be only one tab, in which case the tab bar should
be hidden so that it appears to just be a standard canvas. But when
there are more than one tab, one image canvas is used for each tab.

The `ImageCanvas` is where most things are drawn: the raw images,
the cartesian calibration, and the polar calibration.

Calibration Config Widget
-------------------------

The calibration config widget is one of the more complicated pieces
of the code. Since there are many widgets inside, rather than adding
setters and getters for every single widget/config pair, we decided
to create a [yaml file](resources/calibration/yaml_to_gui.yml) that
maps the widgets to their yaml paths. If you look inside
[yaml_to_gui.yml](resources/calibration/yaml_to_gui.yml), you can see
that it looks just like an instrument configuration file, except that
instead of values, it contains the names of the widgets that set/get
each value.

There is one special key in the calibration config file:
"detector_name". This is special, because there can be many different
detectors. When detector values are set/get, the "detector_name" key
gets replaced with the name of the current detector.

Calibration Tree Widget
-----------------------

The calibration tree widget uses a model/view approach. The design
mostly follows the example
[given here](https://doc.qt.io/qt-5/qtwidgets-itemviews-simpletreemodel-example.html).
Basically, there are `TreeItem`s, which do not subclass from any Qt
types. The item model is `CalTreeItemModel`, which subclasses from
`QAbstractItemModel`. And the view is `CalTreeView`, which subclasses
from `QTreeView`.

Async Worker
------------

The `AsyncWorker` class is probably a good go-to if you need to do
something in a background thread. It subclasses from `QRunnable`, and
it emits the following signals:
```
finished(None) # Emitted both on error and on normal finish
error(tuple) # Emitted when an error occurs, and provides error info
result(object) # Emitted on normal finish, and provides the result object
progress(int) # Emitted only if a progress callback was used, and it
              # provides the current step of progress as an int
```

The `AsyncWorker` is used like the following:
```
thread_pool = QThreadPool() # Probably should be a member variable
worker = AsyncWorker(func_to_call)
thread_pool.start(worker)

worker.signals.result.connect(finish_func)
```
