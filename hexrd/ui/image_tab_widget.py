from PySide2.QtCore import Signal, Slot, Qt
from PySide2.QtWidgets import QMessageBox, QTabWidget, QHBoxLayout

import numpy as np

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_canvas import ImageCanvas
from hexrd.ui.image_series_toolbar import ImageSeriesToolbar
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui import utils


class ImageTabWidget(QTabWidget):

    # Tell the main window that an update is needed
    update_needed = Signal()
    # Tell the template dialog widow that an update is needed
    template_update_needed = Signal()

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
        self.current_index = 0

        # These will get set later
        self.cmap = None
        self.norm = None
        self.toolbars = []
        self.toolbar_visible = True

        self.setup_connections()

    def setup_connections(self):
        self.tabBarClicked.connect(self.switch_toolbar)
        HexrdConfig().tab_images_changed.connect(self.load_images)
        HexrdConfig().detectors_changed.connect(self.reset_index)

    def reset_index(self):
        self.current_index = 0

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
        self.allocate_toolbars()
        for i, name in enumerate(self.image_names):
            self.image_canvases[i].load_images(
                image_names=[name], template=self.template_canvas)
            self.addTab(self.image_canvases[i], name)

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().show()
        self.setCurrentIndex(self.current_index)

    def load_images_untabbed(self):
        self.clear()
        self.image_canvases[0].load_images(
            image_names=self.image_names, template=self.template_canvas)
        self.allocate_toolbars()
        self.addTab(self.image_canvases[0], '')

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().hide()

    def update_image_names(self):
        if self.image_names != list(HexrdConfig().imageseries_dict.keys()):
            self.image_names = list(HexrdConfig().imageseries_dict.keys())

    def load_images(self, template=False):
        self.template_canvas = template
        self.update_image_names()
        self.update_ims_toolbar()

        if HexrdConfig().tab_images:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

        self.switch_toolbar(self.currentIndex())

    def add_template(self, patch):
        self.image_canvases[0].add_template(patch)
        self.template_update_needed.emit()

    def remove_template(self, template):
        self.image_canvases[0].remove_template(template)
        self.template_update_needed.emit()

    def change_ims_image(self, pos):
        HexrdConfig().current_imageseries_idx = pos
        if self.template_canvas:
            self.template_update_needed.emit()
        else:
            self.update_needed.emit()

    @Slot(bool)
    def show_toolbar(self, b):
        self.toolbar_visible = b

        if self.current_index < 0 or not self.toolbars:
            return

        self.toolbars[self.current_index]['tb'].setVisible(b)
        self.toolbars[self.current_index]['sb'].set_visible(b)

    def allocate_toolbars(self):
        parent = self.parent()
        while len(self.toolbars) != len(self.image_canvases):
            # The new one to add
            idx = len(self.toolbars)
            tb = NavigationToolbar(self.image_canvases[idx], parent, False)
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

    def switch_toolbar(self, idx):
        if idx < 0:
            return

        self.current_index = idx

        # None should be visible except the current one
        for i, toolbar in enumerate(self.toolbars):
            status = self.toolbar_visible if idx == i else False
            toolbar['tb'].setVisible(status)
            toolbar['sb'].set_visible(status)
        self.update_ims_toolbar()

    def update_ims_toolbar(self):
        idx = self.current_index
        if self.toolbars:
            self.toolbars[idx]['sb'].update_name(self.image_names[idx])
            self.toolbars[idx]['sb'].update_range(True)

    def show_cartesian(self):
        self.update_image_names()
        self.update_ims_toolbar()

        # Make sure we actually have images
        if len(self.image_names) == 0:
            msg = 'Cannot show Cartesian view without images!'
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.clear()
        self.image_canvases[0].show_cartesian()
        self.addTab(self.image_canvases[0], '')
        self.tabBar().hide()
        self.switch_toolbar(self.currentIndex())

    def show_polar(self):
        self.update_image_names()
        self.update_ims_toolbar()

        # Make sure we actually have images
        if len(self.image_names) == 0:
            msg = 'Cannot show Polar view without images!'
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.clear()
        self.image_canvases[0].show_polar()
        self.addTab(self.image_canvases[0], '')
        self.tabBar().hide()
        self.switch_toolbar(self.currentIndex())

    def active_canvases(self):
        """Get the canvases that are actively being used"""
        if not HexrdConfig().tab_images:
            return [self.image_canvases[0]]

        return self.image_canvases[:len(self.image_names)]

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

            # We will only display the active material's hkls
            plane_data = HexrdConfig().active_material.planeData
            dsp = 0.5 * plane_data.wavelength / np.sin(0.5 * tth)
            hkl = str(plane_data.getHKLs(asStr=True, allHKLs=True,
                                         thisTTh=tth))

            info['tth'] = np.degrees(tth)
            info['eta'] = np.degrees(eta)
            info['dsp'] = dsp
            info['hkl'] = hkl

        self.new_mouse_position.emit(info)

    def export_polar_plot(self, filename):
        self.image_canvases[0].export_polar_plot(filename)

    def polar_show_snip1d(self):
        self.image_canvases[0].polar_show_snip1d()


if __name__ == '__main__':
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # This will just test for __init__ errors
    ImageTabWidget()
