from PySide2.QtCore import Signal, Slot, Qt
from PySide2.QtWidgets import QFileDialog, QMessageBox, QTabWidget

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_canvas import ImageCanvas

# Remove these buttons from the navigation toolbar
nav_toolbar_blacklist = [
    'Subplots'
]
NavigationToolbar2QT.toolitems = [x for x in NavigationToolbar2QT.toolitems if
                                  x[0] not in nav_toolbar_blacklist]


class ImageTabWidget(QTabWidget):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    def __init__(self, parent=None):
        super(ImageTabWidget, self).__init__(parent)
        self.image_canvases = [ImageCanvas(self)]
        self.image_names = []

        # These will get set later
        self.cmap = None
        self.norm = None
        self.nav_toolbars = []
        self.nav_toolbar_visible = True

        self.set_tabbed_view(False)

        self.setup_connections()

    def setup_connections(self):
        self.currentChanged.connect(self.switch_nav_toolbar)

    def allocate_canvases(self):
        while len(self.image_canvases) < len(self.image_names):
            self.image_canvases.append(ImageCanvas(self))

    def load_images_tabbed(self):
        self.clear()
        self.allocate_canvases()
        for i, name in enumerate(self.image_names):
            self.image_canvases[i].load_images(image_names=[name])
            self.addTab(self.image_canvases[i], name)

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().show()

    def load_images_untabbed(self):
        self.clear()
        self.image_canvases[0].load_images(image_names=self.image_names)
        self.addTab(self.image_canvases[0], '')

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().hide()

    def load_images(self):
        self.image_names = list(HexrdConfig().images().keys())

        if self.tabbed_view:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

        self.new_images_loaded.emit()

    @Slot(bool)
    def set_tabbed_view(self, tabbed_view=False):
        self.tabbed_view = tabbed_view
        if self.tabbed_view:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

    @Slot(bool)
    def show_nav_toolbar(self, b):
        self.nav_toolbar_visible = b

        idx = self.currentIndex()
        if idx < 0:
            return

        self.nav_toolbars[idx].setVisible(b)

    def allocate_nav_toolbars(self):
        parent = self.parent()
        while len(self.nav_toolbars) != len(self.image_canvases):
            # The new one to add
            idx = len(self.nav_toolbars)
            tb = NavigationToolbar2QT(self.image_canvases[idx], parent, False)

            # Invisible by default
            tb.setVisible(False)

            # This will put it at the bottom of the central widget
            parent.layout().addWidget(tb)
            parent.layout().setAlignment(tb, Qt.AlignCenter)
            self.nav_toolbars.append(tb)

    def switch_nav_toolbar(self):
        idx = self.currentIndex()
        if idx < 0:
            return

        # Make sure all the toolbars are present and accounted for
        self.allocate_nav_toolbars()

        # None should be visible except the current one
        for tb in self.nav_toolbars:
            tb.setVisible(False)

        self.nav_toolbars[idx].setVisible(self.nav_toolbar_visible)

    def show_calibration(self):
        # Make sure we actually have images
        if len(self.image_names) == 0:
            msg = 'Cannot run calibration without images!'
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.clear()
        self.image_canvases[0].show_calibration()
        self.addTab(self.image_canvases[0], '')
        self.tabBar().hide()

    def show_polar_calibration(self):
        # Make sure we actually have images
        if len(self.image_names) == 0:
            msg = 'Cannot run calibration without images!'
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.clear()
        self.image_canvases[0].show_polar_calibration()
        self.addTab(self.image_canvases[0], '')
        self.tabBar().hide()

    def active_canvases(self):
        """Get the canvases that are actively being used"""
        if not self.tabbed_view:
            return [self.image_canvases[0]]

        return self.image_canvases[:len(self.image_names)]

    def value_range(self):
        """Get the range of values in the images"""
        mins_maxes = [x.get_min_max() for x in self.active_canvases()]
        minimum = min([x[0] for x in mins_maxes])
        maximum = max([x[1] for x in mins_maxes])

        return minimum, maximum

    def update_canvas_cmaps(self):
        if self.cmap is not None:
            for canvas in self.active_canvases():
                canvas.set_cmap(self.cmap)

    def update_canvas_norms(self):
        if self.norm is not None:
            for canvas in self.active_canvases():
                canvas.set_norm(self.norm)

    def set_cmap(self, cmap):
        self.cmap = cmap
        self.update_canvas_cmaps()

    def set_norm(self, norm):
        self.norm = norm
        self.update_canvas_norms()

if __name__ == '__main__':
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # This will just test for __init__ errors
    ImageTabWidget()
