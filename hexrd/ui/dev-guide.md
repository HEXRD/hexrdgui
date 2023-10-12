Developer's Guide
=================

This document is written with the intention of providing an explanation
and a guide to some of the code infrastructure of hexrdgui.

Singleton Configuration
-----------------------

Perhaps the most important design to mention is the fact that there is
a [singleton configuration](hexrd_config.py) that contains most of the
configuration of the program at any given time (except for the color
map configuration, which may also be added in the future).

All of the configuration in the `HexrdConfig` singleton is stored as a
python dictionary, but most of it is designed to be accessed as
properties. For example, if you wish to see if the canvas is to show
overlays, you can check:
```
b = HexrdConfig().show_overlays
```

Since the `HexrdConfig` is a `QObject` as well, it can emit signals to
inform the GUI that something needs updating. Setting some of the
properties results in `HexrdConfig()` emitting a signal. For instance,
```
HexrdConfig().show_overlays = b
```
will emit a `overlay_config_changed` signal. The canvas is connected to
this signal, and when it receives the signal, it re-draws the overlays.

The properties' underlying functions are sometimes named with an
underscore at the beginning, and they are present so that widgets can
directly connect to them. For instance:
```
self.ui.show_overlays.toggled.connect(HexrdConfig()._set_show_overlays)
```

The singleton configuration also makes saving and loading settings
easy, because an entire dictionary can be saved with
`QSettings().setValue()`. This is currently being done for a few of the
different configuration keys.

Currently, there are a few main keys for the configuration:
```
instrument: contains the instrument config used by hexrd
materials: contains materials settings and the loaded materials
image: contains image settings
calibration: contains settings used for calibration
indexing: contains settings used for indexing
```

No additional keys should be added to `instrument`, and `indexing`,
because they are based upon config settings in the `hexrd` repository.

However, additional keys can be added to `materials`, `image`, and
`calibration` as needed. Additional main keys can be added as well,
when more generic categories are needed.

UI Files
--------

One nice feature of PySide6 is that UI files can be loaded at runtime.
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

If some events need to be overridden, `QObject.installEventFilter()` can
be used.

If your class needs to emit signals, two things must be done:

1. Your class needs to inherit from `QObject`.
2. You need to run `super().__init__(parent)`. If you don't do this, you
   will encounter incomprehensible errors.

A UI class that emits signals needs to be set up like the following:
```
from PySide6.QtCore import Signal, QObject

from hexrd.ui.ui_loader import UiLoader

class SomeWidget(QObject):

    the_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('some_widget.ui', parent)

    def emit_signal(self):
        self.the_signal.emit()
```

For updating the GUI with internal config, the design pattern we typically
use is as follows:
```
from hexrd.ui.utils import block_signals

...

    @property
    def all_widgets(self):
        return [
            self.ui.widget1,
            self.ui.widget2,
            ...
        ]

    def update_gui(self):
        with block_signals(*self.all_widgets):
            self.ui.widget1.setValue(...)
            ...
```

We need to block the widget signals when we are updating the values, so that
they do not modify the config as well. The reason we use a context manager
is so that if an exception is raised, they will be unblocked automatically.

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

Formatting
----------

Generally, we try to adhere to pep8 rules. It is highly recommended that
you run `flake8` on the file you have worked on, and fix any errors.
This has not always been enforced, so there are some files that do not
adhere to pep8.
