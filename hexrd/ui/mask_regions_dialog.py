import numpy as np

from PySide2.QtCore import QObject, Signal

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.ui_loader import UiLoader

from matplotlib import patches, path

from skimage.draw import rectangle, ellipse


class MaskRegionsDialog(QObject):

    # Emitted when new images are loaded
    new_mask_added = Signal()

    def __init__(self, parent=None):
        super(MaskRegionsDialog, self).__init__(parent)

        self.parent = parent
        self.images = []
        self.canvas_ids = []
        self.axes = None
        self.press = []
        self.added_patches = []
        self.patches = {det: [] for det in HexrdConfig().detector_names}

        loader = UiLoader()
        self.ui = loader.load_file('mask_regions_dialog.ui', parent)

        self.setup_canvas_connections()
        self.setup_ui_connections()
        self.select_shape()

    def show(self):
        self.ui.show()

    def disconnect(self):
        for ids, img in zip(self.canvas_ids, self.images):
            [img.mpl_disconnect(id) for id in ids]
        self.canvas_ids.clear()
        self.images.clear()

    def setup_canvas_connections(self):
        for canvas in self.parent.image_tab_widget.active_canvases():
            press = canvas.mpl_connect(
                'button_press_event', self.button_pressed)
            drag = canvas.mpl_connect(
                'motion_notify_event', self.drag_motion)
            release = canvas.mpl_connect(
                'button_release_event', self.button_released)
            enter = canvas.mpl_connect(
                'axes_enter_event', self.axes_entered)
            exit = canvas.mpl_connect(
                'axes_leave_event', self.axes_exited)
            self.canvas_ids.append([press, drag, release, enter, exit])
            self.images.append(canvas)

    def setup_ui_connections(self):
        self.ui.button_box.accepted.connect(self.apply_masks)
        self.ui.button_box.rejected.connect(self.cancel)
        self.ui.shape.currentIndexChanged.connect(self.select_shape)
        self.ui.undo.clicked.connect(self.undo_selection)
        HexrdConfig().tab_images_changed.connect(self.tabbed_view_changed)

    def select_shape(self):
        self.selection = self.ui.shape.currentText()
        self.patch = None

    def create_patch(self):
        if self.selection == 'Rectangle':
            self.patch = patches.Rectangle((0, 0), 0, 0, fill=False)
        elif self.selection == 'Ellipse':
            self.patch = patches.Ellipse((0, 0), 0, 0, fill=False)
        self.axes.add_patch(self.patch)
        self.patches[self.det].append(self.patch)
        self.added_patches.append(self.det)

    def update_patch(self, event):
        x0, y0 = self.press
        height = event.ydata - y0
        width = event.xdata - x0
        if self.selection == 'Rectangle':
            self.patch.set_xy(self.press)
            self.patch.set_height(height)
            self.patch.set_width(width)
        if self.selection == 'Ellipse':
            center = [(width / 2 + x0), (height / 2 + y0)]
            self.patch.set_center(center)
            self.patch.height = height
            self.patch.width = width

    def tabbed_view_changed(self):
        self.disconnect()
        self.setup_canvas_connections()

        for canvas in self.parent.image_tab_widget.active_canvases():
            for axes in canvas.raw_axes:
                for p in self.patches.get(axes.get_title(), []):
                    # Artists cannot be reused or simply copied, instead
                    # a new artist must be created
                    obj, *attrs = p.__str__().split('(')
                    patch = getattr(patches, obj)((0, 0), 0, 0, fill=False)
                    for attr in ['xy', 'center', 'width', 'height']:
                        try:
                            getattr(patch, 'set_' + attr)(
                                getattr(p, 'get_' + attr)())
                        except Exception:
                            try:
                                setattr(patch, attr, getattr(p, attr))
                            except Exception:
                                continue
                    axes.add_patch(patch)
                self.patches[axes.get_title()] = axes.patches

    def discard_patch(self):
        det = self.added_patches.pop()
        if det == ViewType.polar:
            HexrdConfig().polar_masks_line_data.pop()
        else:
            HexrdConfig().raw_masks_line_data.pop()
        return self.patches[det].pop()

    def undo_selection(self):
        if not self.added_patches:
            return

        last_patch = self.discard_patch()
        if det == ViewType.polar and hasattr(self.canvas, 'axis'):
            self.canvas.axis.patches.remove(last_patch)
        else:
            for a in self.canvas.raw_axes:
                if a.get_title() == det:
                    a.patches.remove(last_patch)
        self.canvas.draw()

    def axes_entered(self, event):
        self.axes = event.inaxes
        self.canvas = event.canvas

    def axes_exited(self, event):
        self.axes = None

    def button_pressed(self, event):
        if not self.axes:
            return

        self.press = [int(event.xdata), int(event.ydata)]
        self.det = self.axes.get_title()
        self.create_patch()
        self.canvas.draw()

    def drag_motion(self, event):
        if not self.axes or not self.press:
            return

        self.update_patch(event)
        self.canvas.draw()

    def create_mask(self):
        data_coords = self.patch.get_patch_transform().transform(
            self.patch.get_path().vertices)
        pixel_coords = self.axes.transData.transform(data_coords)
        HexrdConfig().raw_masks_line_data.append(pixel_coords)

    def button_released(self, event):
        if not self.axes or not self.press:
            return

        self.end = [int(event.xdata), int(event.ydata)]
        self.create_mask()

        self.press.clear()
        self.end.clear()
        self.det = None
        self.canvas.draw()

    def apply_masks(self):
        self.disconnect()
        self.patches = {det: [] for det in HexrdConfig().detector_names}
        self.new_mask_added.emit()
        self.canvas.draw()

    def cancel(self):
        while self.added_patches:
            self.discard_patch()

        if hasattr(self.canvas, 'axis'):
            self.canvas.axis.patches.clear()
        for canvas in self.parent.image_tab_widget.active_canvases():
            for axes in canvas.raw_axes:
                axes.patches.clear()

        self.disconnect()
        self.canvas.draw()
