from PySide2.QtCore import Signal, Slot, Qt
from PySide2.QtWidgets import QMessageBox, QTabWidget, QHBoxLayout

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT

import numpy as np

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_canvas import ImageCanvas
from hexrd.ui.image_series_toolbar import ImageSeriesToolbar
from hexrd.ui import utils

# Remove these buttons from the navigation toolbar
nav_toolbar_blacklist = [
    'Subplots'
]
NavigationToolbar2QT.toolitems = [x for x in NavigationToolbar2QT.toolitems if
                                  x[0] not in nav_toolbar_blacklist]


class ImageTabWidget(QTabWidget):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    # Emitted when the mouse is moving on the canvas, but outside
    # an image/plot. Intended to clear the status bar.
    clear_mouse_position = Signal()

    # Emitted when the mouse moves on top of an image/plot
    # Arguments are: x, y, xdata, ydata, intensity
    new_mouse_position = Signal(dict)

    def __init__(self, parent=None):
        super(ImageTabWidget, self).__init__(parent)
        self.image_canvases = [ImageCanvas(self)]

        # Set up a mouse move connection to use with the status bar
        cid = self.image_canvases[0].mpl_connect(
            'motion_notify_event',
            self.on_motion_notify_event)
        self.mpl_connections = [cid]

        self.image_names = []

        # These will get set later
        self.cmap = None
        self.norm = None
        self.toolbars = []
        self.toolbar_visible = True

        self.set_tabbed_view(False)

        self.setup_connections()

    def setup_connections(self):
        self.currentChanged.connect(self.switch_toolbar)

    def allocate_canvases(self):
        while len(self.image_canvases) < len(self.image_names):
            self.image_canvases.append(ImageCanvas(self))

        # Make connections to use with the status bar
        while len(self.mpl_connections) < len(self.image_canvases):
            ind = len(self.mpl_connections)
            cid = self.image_canvases[ind].mpl_connect(
                'motion_notify_event',
                self.on_motion_notify_event)

            self.mpl_connections.append(cid)

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
        self.image_canvases[0].load_images(
            image_names=self.image_names)
        self.addTab(self.image_canvases[0], '')

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().hide()

    def load_images(self):
        self.image_names = list(HexrdConfig().imageseries_dict.keys())

        if self.tabbed_view:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

        self.new_images_loaded.emit()
        self.update_ims_toolbar()

    def change_ims_image(self, pos, name):
        HexrdConfig().current_imageseries_idx = pos
        idx = self.currentIndex()
        if not self.tabbed_view:
            self.image_canvases[0].load_images(
                image_names=self.image_names)
        else:
            self.image_canvases[idx].load_images(
                image_names=[name])

    @Slot(bool)
    def set_tabbed_view(self, tabbed_view=False):
        self.tabbed_view = tabbed_view
        if self.tabbed_view:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

    @Slot(bool)
    def show_toolbar(self, b):
        self.toolbar_visible = b

        idx = self.currentIndex()
        if idx < 0 or not self.toolbars:
            return

        self.toolbars[idx]['tb'].setVisible(b)
        self.toolbars[idx]['sb'].set_visible(b)

    def allocate_toolbars(self):
        parent = self.parent()
        while len(self.toolbars) != len(self.image_canvases):
            # The new one to add
            idx = len(self.toolbars)
            tb = NavigationToolbar2QT(self.image_canvases[idx], parent, False)
            # Current detector
            name = self.image_names[idx]
            sb = ImageSeriesToolbar(name, self)

            # This will put it at the bottom of the central widget
            toolbar = QHBoxLayout()
            toolbar.addWidget(tb)
            toolbar.addWidget(sb.widget)
            parent.layout().addLayout(toolbar)
            parent.layout().setAlignment(toolbar, Qt.AlignCenter)
            self.toolbars.append({'tb': tb, 'sb': sb})

    def switch_toolbar(self):
        idx = self.currentIndex()
        if idx < 0:
            return

        # Make sure all the toolbars are present and accounted for
        self.allocate_toolbars()

        # None should be visible except the current one
        for toolbar in self.toolbars:
            toolbar['tb'].setVisible(False)
            toolbar['sb'].set_visible(False)

        self.toolbars[idx]['tb'].setVisible(self.toolbar_visible)
        self.toolbars[idx]['sb'].set_visible(self.toolbar_visible)

    def update_ims_toolbar(self):
        for toolbar in self.toolbars:
            toolbar['sb'].update_range()

    def show_cartesian(self):
        # Make sure we actually have images
        if len(self.image_names) == 0:
            msg = 'Cannot run calibration without images!'
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.clear()
        self.image_canvases[0].show_cartesian()
        self.addTab(self.image_canvases[0], '')
        self.tabBar().hide()

    def show_polar(self):
        # Make sure we actually have images
        if len(self.image_names) == 0:
            msg = 'Cannot run calibration without images!'
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.clear()
        self.image_canvases[0].show_polar()
        self.addTab(self.image_canvases[0], '')
        self.tabBar().hide()

    def active_canvases(self):
        """Get the canvases that are actively being used"""
        if not self.tabbed_view:
            return [self.image_canvases[0]]

        return self.image_canvases[:len(self.image_names)]

    def value_range(self):
        """Get the range of values in the images"""
        mins_maxes = [x.percentile_range() for x in self.active_canvases()]
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

    def on_motion_notify_event(self, event):
        # Clear the info if the mouse leaves a plot
        if event.inaxes is None:
            self.clear_mouse_position.emit()
            return

        mode = self.image_canvases[0].mode

        if mode is None:
            mode = 'images'

        info = {
            'x': event.x,
            'y': event.y,
            'x_data': event.xdata,
            'y_data': event.ydata,
            'mode': mode
        }

        # TODO: we are currently calculating the pixel intensity
        # mathematically, because I couldn't find any other way
        # to obtain it. If we find a better way, let's do it.

        if event.inaxes.get_images():
            # Image was created with imshow()
            artist = event.inaxes.get_images()[0]
            i, j = utils.coords2index(artist, info['x_data'], info['y_data'])
            intensity = artist.get_array()[i, j]
        else:
            # This is probably just a plot. Do not calculate intensity.
            intensity = None

        info['intensity'] = intensity

        # intensity being None implies here that the mouse is on top of the
        # azimuthal integration plot in the polar view.
        if mode in ['cartesian', 'polar'] and intensity is not None:

            iviewer = self.image_canvases[0].iviewer

            if mode == 'cartesian':
                xy_data = iviewer.dpanel.pixelToCart(np.vstack([i, j]).T)
                ang_data, gvec = iviewer.dpanel.cart_to_angles(xy_data)
                tth = ang_data[:, 0][0]
                eta = ang_data[:, 1][0]
            else:
                tth = np.radians(info['x_data'])
                eta = np.radians(info['y_data'])

            dsp = 0.5 * iviewer.plane_data.wavelength / np.sin(0.5 * tth)
            hkl = str(iviewer.plane_data.getHKLs(asStr=True, allHKLs=True,
                                                 thisTTh=tth))

            info['tth'] = np.degrees(tth)
            info['eta'] = np.degrees(eta)
            info['dsp'] = dsp
            info['hkl'] = hkl

        self.new_mouse_position.emit(info)


if __name__ == '__main__':
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # This will just test for __init__ errors
    ImageTabWidget()
