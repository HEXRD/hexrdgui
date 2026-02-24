from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Signal, Slot, Qt
from PySide6.QtWidgets import QMessageBox, QTabWidget, QHBoxLayout, QWidget

import numpy as np

from hexrdgui.constants import PAN, ViewType, ZOOM
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_canvas import ImageCanvas
from hexrdgui.image_series_toolbar import (
    ImageSeriesToolbar,
    ImageSeriesInfoToolbar,
)
from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.navigation_toolbar import NavigationToolbar
from hexrdgui.utils.conversions import (
    angles_to_chi,
    stereo_to_angles,
    tth_to_q,
)
from hexrdgui import utils

if TYPE_CHECKING:
    from matplotlib.backend_bases import MouseEvent
    from matplotlib.colors import Normalize


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image_canvases = [ImageCanvas(self)]

        # Set up a mouse move connection to use with the status bar
        cid = self.image_canvases[0].mpl_connect(
            'motion_notify_event', self.on_motion_notify_event  # type: ignore[arg-type]
        )
        self.mpl_connections = [cid]

        self.image_names: list[str] = []
        self.current_index = 0

        # These will get set later
        self.cmap: str | None = None
        self.norm: Normalize | None = None
        self.scaling: Any = None
        self.toolbars: list[dict[str, Any]] = []
        self.toolbar_visible = True

        self.setup_connections()

    def setup_connections(self) -> None:
        self.tabBarClicked.connect(self.switch_toolbar)
        HexrdConfig().tab_images_changed.connect(self.load_images)
        HexrdConfig().detectors_changed.connect(self.reset_index)

    def clear(self) -> None:
        # This calls super().clear()
        # Hide all toolbars
        for tb in self.toolbars:
            tb['tb'].setVisible(False)
            tb['sb'].set_visible(False)
            tb['ib'].set_visible(False)

        super().clear()

    def reset_index(self) -> None:
        self.current_index = 0

    def allocate_canvases(self) -> None:
        while len(self.image_canvases) < len(self.image_names):
            self.image_canvases.append(ImageCanvas(self))

        # Make connections to use with the status bar
        while len(self.mpl_connections) < len(self.image_canvases):
            ind = len(self.mpl_connections)
            cid = self.image_canvases[ind].mpl_connect(
                'motion_notify_event', self.on_motion_notify_event  # type: ignore[arg-type]
            )

            self.mpl_connections.append(cid)

    def load_images_tabbed(self) -> None:
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

    def load_images_untabbed(self) -> None:
        self.clear()
        self.image_canvases[0].load_images(image_names=self.image_names)
        self.allocate_toolbars()
        self.addTab(self.image_canvases[0], '')

        self.update_canvas_cmaps()
        self.update_canvas_norms()
        self.tabBar().hide()

    @property
    def using_stitched_images(self) -> bool:
        return (
            HexrdConfig().image_mode == ViewType.raw
            and HexrdConfig().stitch_raw_roi_images
        )

    def update_image_names(self) -> None:
        if self.using_stitched_images:
            # The image names will be the detector group names
            image_names = HexrdConfig().detector_group_names
        else:
            image_names = list(HexrdConfig().imageseries_dict.keys())

        self.image_names = image_names

    def ims_for_name(self, name: str) -> Any:
        if self.using_stitched_images:
            # The name is a "group" name.
            # Just return the first ims that matches.
            for det_key in HexrdConfig().detectors:
                if HexrdConfig().detector_group(det_key) == name:
                    name = det_key

        return HexrdConfig().imageseries(name)

    def load_images(self) -> None:
        self.update_image_names()
        self.update_ims_toolbar()

        if HexrdConfig().tab_images:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

        self.switch_toolbar(self.currentIndex())

    def change_ims_image(self, pos: int) -> None:
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
    def show_toolbar(self, b: bool) -> None:
        self.toolbar_visible = b

        if self.current_index < 0 or not self.toolbars:
            return

        self.toolbars[self.current_index]['tb'].setVisible(b)
        self.toolbars[self.current_index]['sb'].set_visible(b)
        self.toolbars[self.current_index]['ib'].set_visible(b)

    def allocate_toolbars(self) -> None:
        parent = self.parent()
        while len(self.toolbars) != len(self.image_canvases):
            # The new one to add
            idx = len(self.toolbars)
            tb = NavigationToolbar(self.image_canvases[idx], parent, False)
            self.image_canvases[idx]._nav_toolbar = tb
            tb.setVisible(False)
            # Current detector
            ims = self.ims_for_name(self.image_names[idx])
            sb = ImageSeriesToolbar(ims, self)
            ib = ImageSeriesInfoToolbar(self)
            sb.set_visible(False)
            ib.set_visible(False)

            # This will put it at the bottom of the central widget
            toolbar = QHBoxLayout()
            toolbar.addWidget(ib.widget)  # type: ignore[arg-type]
            toolbar.addWidget(tb)
            toolbar.addWidget(sb.widget)  # type: ignore[arg-type]
            assert parent is not None
            parent.layout().addLayout(toolbar)  # type: ignore[attr-defined]
            parent.layout().setAlignment(toolbar, Qt.AlignmentFlag.AlignCenter)  # type: ignore[attr-defined]
            self.toolbars.append({'tb': tb, 'sb': sb, 'ib': ib})

    def switch_toolbar(self, idx: int) -> None:
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

    def update_ims_toolbar(self) -> None:
        idx = self.current_index
        if self.toolbars:
            ims = self.ims_for_name(self.image_names[idx])
            self.toolbars[idx]['sb'].update_ims(ims)
            self.toolbars[idx]['sb'].update_range(True)

    def toggle_off_toolbar(self) -> None:
        toolbars = [bars['tb'] for bars in self.toolbars]
        for tb in toolbars:
            if tb.mode == ZOOM:
                tb.zoom()
            if tb.mode == PAN:
                tb.pan()

    def show_cartesian(self) -> None:
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

    def show_polar(self) -> None:
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

    def show_stereo(self) -> None:
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
    def active_canvas(self) -> ImageCanvas:
        return self.image_canvases[self.current_index]

    @property
    def active_canvases(self) -> list[ImageCanvas]:
        """Get the canvases that are actively being used"""
        if not HexrdConfig().tab_images:
            return [self.image_canvases[0]]

        return self.image_canvases[: len(self.image_names)]

    def update_canvas_cmaps(self) -> None:
        if self.cmap is not None:
            for canvas in self.active_canvases:
                canvas.set_cmap(self.cmap)

    def update_canvas_norms(self) -> None:
        if self.norm is not None:
            for canvas in self.active_canvases:
                canvas.set_norm(self.norm)

    def update_canvas_scaling(self) -> None:
        if self.scaling is not None:
            for canvas in self.active_canvases:
                canvas.set_scaling(self.scaling)

    def set_cmap(self, cmap: str) -> None:
        self.cmap = cmap
        self.update_canvas_cmaps()

    def set_norm(self, norm: Normalize | None) -> None:
        self.norm = norm
        self.update_canvas_norms()

    def set_scaling(self, scaling: Any) -> None:
        self.scaling = scaling
        self.update_canvas_scaling()

    @property
    def scaled_image_data(self) -> dict[str, np.ndarray]:
        # Even for tabbed mode for a raw view, this function should
        # return the whole image data dict.
        return self.image_canvases[0].scaled_display_image_dict

    @property
    def image_ready(self) -> bool:
        return self.image_canvases[0].image_ready

    def on_motion_notify_event(self, event: MouseEvent) -> None:
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
            'mode': mode,
        }

        # These get modified when we perform stitching, so keep
        # the raw versions around.
        raw_xy_data = [event.xdata, event.ydata]
        stitched = (
            mode == ViewType.raw
            and event.inaxes.get_images()
            and HexrdConfig().stitch_raw_roi_images
        )
        if stitched:
            # Convert the xdata and ydata to subpanel coordinates
            canvas = self.active_canvas
            group = event.inaxes.get_title()
            ij = np.array([event.ydata, event.xdata])
            # iviewer is RawViewer here (mode == ViewType.raw)
            result = canvas.iviewer.stitched_to_raw(  # type: ignore[union-attr]
                ij, group
            )
            if result:
                det_key = next(iter(result))
                info['x_data'] = result[det_key][0][1]
                info['y_data'] = result[det_key][0][0]
            else:
                # The mouse wasn't hovering over a subpanel
                self.clear_mouse_position.emit()
                return
        elif mode == ViewType.raw:
            # The title is the name of the detector
            det_key = event.inaxes.get_title()

        # TODO: we are currently calculating the pixel intensity
        # mathematically, because I couldn't find any other way
        # to obtain it. If we find a better way, let's do it.

        if event.inaxes.get_images():
            # Image was created with imshow()
            artist = event.inaxes.get_images()[0]

            # Compute i and j
            i, j = utils.coords2index(artist, info['x_data'], info['y_data'])  # type: ignore[arg-type]
            if stitched:
                # For the intensity, use raw xy data for i and j
                raw_i, raw_j = utils.coords2index(artist, *raw_xy_data)  # type: ignore[arg-type]
            else:
                # They should be the same
                raw_i, raw_j = i, j

            try:
                arr = artist.get_array()
                assert arr is not None
                intensity = arr.data[raw_i, raw_j]
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
            assert iviewer is not None
            instr = iviewer.instr

            if mode in (ViewType.cartesian, ViewType.raw):
                if mode == ViewType.cartesian:
                    dpanel = iviewer.dpanel  # type: ignore[union-attr]
                else:
                    dpanel = instr.detectors[det_key]

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
                    instr=instr,
                    stereo_size=stereo_size,
                )
            else:
                tth = np.radians(info['x_data'])  # type: ignore[arg-type]
                eta = np.radians(info['y_data'])  # type: ignore[arg-type]

            # We will only display the active material's hkls
            material = HexrdConfig().active_material
            plane_data = material.planeData
            dsp = 0.5 * plane_data.wavelength / np.sin(0.5 * tth)
            hkl = str(plane_data.getHKLs(asStr=True, allHKLs=True, thisTTh=tth))

            chi = angles_to_chi(
                np.array([[tth, eta]]),
                HexrdConfig().sample_tilt,
                bvec=instr.beam_vector,
                evec=instr.eta_vector,
            )[0]

            info['tth'] = np.degrees(tth)
            info['eta'] = np.degrees(eta)
            info['dsp'] = dsp
            info['hkl'] = hkl
            info['material_name'] = material.name
            info['Q'] = tth_to_q(info['tth'], instr.beam_energy)  # type: ignore[assignment, arg-type]
            info['chi'] = chi
        elif mode == ViewType.polar:
            # No intensities in the polar view implies we are in the azimuthal
            # integral plot. Compute Q.
            info['is_lineout'] = True
            info['tth'] = info['x_data']

            iviewer2 = self.image_canvases[0].iviewer
            assert iviewer2 is not None
            instr = iviewer2.instr
            info['Q'] = tth_to_q(info['tth'], instr.beam_energy)  # type: ignore[assignment, arg-type]

        hovered_masks: list[str] = []
        if (
            intensity is not None
            and mode in (ViewType.raw, ViewType.polar)
            and not stitched
        ):
            for mask in MaskManager().masks.values():
                if mask.type == MaskType.threshold or (
                    not mask.visible and not mask.show_border and not mask.highlight
                ):
                    continue

                mask_arr = mask.get_masked_arrays(mode, instr)  # type: ignore[call-arg]
                if mode == ViewType.raw:
                    mask_arr = [x[1] for x in mask_arr if x[0] == det_key]
                    if mask_arr:
                        mask_arr = np.logical_and.reduce(mask_arr)
                    else:
                        mask_arr = None

                if mask_arr is not None and not mask_arr[i, j]:
                    if mask.name is not None:
                        hovered_masks.append(mask.name)

        if hovered_masks:
            plural = len(hovered_masks) > 1
            masks_str = ', '.join(hovered_masks)
            if plural:
                label = f'masks = ({masks_str})'
            else:
                label = f'mask = {masks_str}'

            info['masks_str'] = label

        display_detector = (
            intensity is not None
            and (mode != ViewType.raw or stitched)
            and len(instr.detectors) > 1
        )
        if display_detector:
            # If we are not in the raw view and there is more than one
            # detector, then let's also display the detector we are
            # hovering over (if any)
            det_dict = instr.detectors

            ang_crd = np.radians([[info['tth'], info['eta']]])  # type: ignore[arg-type]
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

    def export_current_plot(self, filename: str) -> None:
        self.image_canvases[0].export_current_plot(filename)

    def polar_show_snip1d(self) -> None:
        self.image_canvases[0].polar_show_snip1d()

    def create_waterfall_plot(self) -> None:
        self.image_canvases[0].create_waterfall_plot()

    def export_to_maud(self, filename: str) -> None:
        self.image_canvases[0].export_to_maud(filename)


if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # This will just test for __init__ errors
    ImageTabWidget()
