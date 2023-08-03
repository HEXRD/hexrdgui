from PySide2.QtCore import Signal, Slot, Qt
from PySide2.QtWidgets import QMessageBox, QTabWidget, QHBoxLayout

import numpy as np

from hexrd.ui.constants import PAN, ViewType, ZOOM
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_canvas import ImageCanvas
from hexrd.ui.image_series_toolbar import ImageSeriesToolbar, ImageSeriesInfoToolbar
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.utils.conversions import stereo_to_angles, tth_to_q
from hexrd.ui import utils


class ImageTabWidget(QTabWidget):

    # Tell the main window that an update is needed
    update_needed = Signal()

    # Emitted when the mouse is moving on the canvas, but outside
    # an image/plot. Intended to clear the status bar.
    clear_mouse_position = Signal()

    # Emitted when the mouse moves on top of an image/plot
    # Arguments are: x, y, xdata, ydata, intensity
    new_mouse_position = Signal(dict)

    # Tell the main window that the active canvas has changed
    new_active_canvas = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.scaling = None
        self.toolbars = []
        self.toolbar_visible = True

        self.setup_connections()

    def setup_connections(self):
        self.tabBarClicked.connect(self.switch_toolbar)
        HexrdConfig().tab_images_changed.connect(self.load_images)
        HexrdConfig().detectors_changed.connect(self.reset_index)

    def clear(self):
        # This calls super().clear()
        # Hide all toolbars
        for tb in self.toolbars:
            tb['tb'].setVisible(False)
            tb['sb'].set_visible(False)
            tb['ib'].set_visible(False)

        super().clear()

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
            self.image_canvases[i].load_images(image_names=[name])
            self.addTab(self.image_canvases[i], name)

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().show()
        self.setCurrentIndex(self.current_index)

    def load_images_untabbed(self):
        self.clear()
        self.image_canvases[0].load_images(
            image_names=self.image_names)
        self.allocate_toolbars()
        self.addTab(self.image_canvases[0], '')

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().hide()

    def update_image_names(self):
        if self.image_names != list(HexrdConfig().imageseries_dict.keys()):
            self.image_names = list(HexrdConfig().imageseries_dict.keys())

    def load_images(self):
        self.update_image_names()
        self.update_ims_toolbar()

        if HexrdConfig().tab_images:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

        self.switch_toolbar(self.currentIndex())

    def change_ims_image(self, pos):
        HexrdConfig().current_imageseries_idx = pos
        self.update_needed.emit()

        is_aggregated = HexrdConfig().is_aggregated
        has_omegas = HexrdConfig().has_omegas
        if is_aggregated or not has_omegas:
            return

        # For rotation series, changing the image series index may require
        # a re-draw of the overlays. The rotation series overlays are designed
        # so that on an image series index change, the data does not have to
        # be re-generated, only the overlay needs to be redrawn.
        for overlay in HexrdConfig().overlays:
            redraw = overlay.is_rotation_series and overlay.aggregated is False
            if redraw:
                for canvas in self.active_canvases:
                    canvas.redraw_overlay(overlay)

    @Slot(bool)
    def show_toolbar(self, b):
        self.toolbar_visible = b

        if self.current_index < 0 or not self.toolbars:
            return

        self.toolbars[self.current_index]['tb'].setVisible(b)
        self.toolbars[self.current_index]['sb'].set_visible(b)
        self.toolbars[self.current_index]['ib'].set_visible(b)

    def allocate_toolbars(self):
        parent = self.parent()
        while len(self.toolbars) != len(self.image_canvases):
            # The new one to add
            idx = len(self.toolbars)
            tb = NavigationToolbar(self.image_canvases[idx], parent, False)
            # Current detector
            name = self.image_names[idx]
            sb = ImageSeriesToolbar(name, self)
            ib = ImageSeriesInfoToolbar(self)

            # This will put it at the bottom of the central widget
            toolbar = QHBoxLayout()
            toolbar.addWidget(ib.widget)
            toolbar.addWidget(tb)
            toolbar.addWidget(sb.widget)
            parent.layout().addLayout(toolbar)
            parent.layout().setAlignment(toolbar, Qt.AlignCenter)
            self.toolbars.append({'tb': tb, 'sb': sb, 'ib': ib})

    def switch_toolbar(self, idx):
        if idx < 0:
            return

        if self.current_index != idx:
            self.current_index = idx
            self.new_active_canvas.emit()

        # None should be visible except the current one
        for i, toolbar in enumerate(self.toolbars):
            status = self.toolbar_visible if idx == i else False
            toolbar['tb'].setVisible(status)
            toolbar['sb'].set_visible(status)
            toolbar['ib'].set_visible(status)
        self.update_ims_toolbar()

    def update_ims_toolbar(self):
        idx = self.current_index
        if self.toolbars:
            self.toolbars[idx]['sb'].update_name(self.image_names[idx])
            self.toolbars[idx]['sb'].update_range(True)

    def toggle_off_toolbar(self):
        toolbars = [bars['tb'] for bars in self.toolbars]
        for tb in toolbars:
            if tb.mode == ZOOM:
                tb.zoom()
            if tb.mode == PAN:
                tb.pan()

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

    def show_stereo(self):
        self.update_image_names()
        self.update_ims_toolbar()

        # Make sure we actually have images
        if len(self.image_names) == 0:
            msg = 'Cannot show Stereo view without images!'
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.clear()
        self.image_canvases[0].show_stereo()
        self.addTab(self.image_canvases[0], '')
        self.tabBar().hide()
        self.switch_toolbar(self.currentIndex())

    @property
    def active_canvas(self):
        return self.image_canvases[self.current_index]

    @property
    def active_canvases(self):
        """Get the canvases that are actively being used"""
        if not HexrdConfig().tab_images:
            return [self.image_canvases[0]]

        return self.image_canvases[:len(self.image_names)]

    def update_canvas_cmaps(self):
        if self.cmap is not None:
            for canvas in self.active_canvases:
                canvas.set_cmap(self.cmap)

    def update_canvas_norms(self):
        if self.norm is not None:
            for canvas in self.active_canvases:
                canvas.set_norm(self.norm)

    def update_canvas_scaling(self):
        if self.scaling is not None:
            for canvas in self.active_canvases:
                canvas.set_scaling(self.scaling)

    def set_cmap(self, cmap):
        self.cmap = cmap
        self.update_canvas_cmaps()

    def set_norm(self, norm):
        self.norm = norm
        self.update_canvas_norms()

    def set_scaling(self, scaling):
        self.scaling = scaling
        self.update_canvas_scaling()

    @property
    def scaled_image_data(self):
        # Even for tabbed mode for a raw view, this function should
        # return the whole image data dict.
        return self.image_canvases[0].scaled_image_dict

    def on_motion_notify_event(self, event):
        # Clear the info if the mouse leaves a plot
        if event.inaxes is None:
            self.clear_mouse_position.emit()
            return

        mode = self.image_canvases[0].mode

        if mode is None:
            mode = ViewType.raw

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
            try:
                intensity = artist.get_array().data[i, j]
            except IndexError:
                # Most likely, this means we are slightly out of bounds,
                # and the index is too big. Just clear the status bar in
                # this case.
                # FIXME: can we avoid this somehow?
                self.clear_mouse_position.emit()
                return
        else:
            # This is probably just a plot. Do not calculate intensity.
            intensity = None

        info['intensity'] = intensity

        # intensity being None implies here that the mouse is on top of the
        # azimuthal integration plot in the polar view.
        if intensity is not None:

            iviewer = self.image_canvases[0].iviewer

            if mode in (ViewType.cartesian, ViewType.raw):
                if mode == ViewType.cartesian:
                    dpanel = iviewer.dpanel
                else:
                    # The title is the name of the detector
                    key = event.inaxes.get_title()
                    dpanel = iviewer.instr.detectors[key]

                xy_data = dpanel.pixelToCart(np.vstack([i, j]).T)
                ang_data, gvec = dpanel.cart_to_angles(xy_data)
                tth = ang_data[:, 0][0]
                eta = ang_data[:, 1][0]
            elif mode == ViewType.stereo:
                # The i and j need to be reversed here, because the function
                # expects `i` to be the row and `j` to be the column.
                stereo_size = HexrdConfig().stereo_size
                tth, eta = stereo_to_angles(
                    ij=np.vstack([j, i]).T,
                    instr=iviewer.instr,
                    stereo_size=stereo_size,
                )
            else:
                tth = np.radians(info['x_data'])
                eta = np.radians(info['y_data'])

            # We will only display the active material's hkls
            material = HexrdConfig().active_material
            plane_data = material.planeData
            dsp = 0.5 * plane_data.wavelength / np.sin(0.5 * tth)
            hkl = str(plane_data.getHKLs(asStr=True, allHKLs=True,
                                         thisTTh=tth))

            info['tth'] = np.degrees(tth)
            info['eta'] = np.degrees(eta)
            info['dsp'] = dsp
            info['hkl'] = hkl
            info['material_name'] = material.name
            info['Q'] = tth_to_q(info['tth'], iviewer.instr.beam_energy)
        elif mode == ViewType.polar:
            # No intensities in the polar view implies we are in the azimuthal
            # integral plot. Compute Q.
            info['is_lineout'] = True
            info['tth'] = info['x_data']

            iviewer = self.image_canvases[0].iviewer
            info['Q'] = tth_to_q(info['tth'], iviewer.instr.beam_energy)

        display_detector = (
            intensity is not None and
            mode != ViewType.raw and
            len(iviewer.instr.detectors) > 1
        )
        if display_detector:
            # If we are not in the raw view and there is more than one
            # detector, then let's also display the detector we are
            # hovering over (if any)
            det_dict = iviewer.instr.detectors

            ang_crd = np.radians([[info['tth'], info['eta']]])
            detector_matches = []
            for name, panel in det_dict.items():
                cart = panel.angles_to_cart(ang_crd)
                xys, valid = panel.clip_to_panel(cart, buffer_edges=False)
                if valid[0]:
                    detector_matches.append(name)

            if detector_matches:
                plural = len(detector_matches) > 1
                det_str = ', '.join(detector_matches)
                if plural:
                    label = f'detectors = ({det_str})'
                else:
                    label = f'detector = {det_str}'

                info['detectors_str'] = label
            else:
                info['detectors_str'] = 'detector = None'

        self.new_mouse_position.emit(info)

    def export_current_plot(self, filename):
        self.image_canvases[0].export_current_plot(filename)

    def polar_show_snip1d(self):
        self.image_canvases[0].polar_show_snip1d()

    def export_to_maud(self, filename):
        self.image_canvases[0].export_to_maud(filename)


if __name__ == '__main__':
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # This will just test for __init__ errors
    ImageTabWidget()
