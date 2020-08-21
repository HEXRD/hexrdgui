import numpy as np

from PySide2.QtCore import QObject, Signal

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.ui_loader import UiLoader

from matplotlib import patches, path

from skimage.draw import rectangle, ellipse


class MaskRegionsDialog(QObject):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    def __init__(self, parent=None):
        super(MaskRegionsDialog, self).__init__(parent)

        self.parent = parent
        self.images = []
        self.canvas_ids = []
        self.axes = None
        self.press = []
        self.masks = {det:[] for det in HexrdConfig().detector_names}

        loader = UiLoader()
        self.ui = loader.load_file('mask_regions_dialog.ui', parent)

        self.setup_canvas_connections()
        self.setup_ui_connections()
    
    def show(self):
        self.select_shape()
        self.ui.show()

    def disconnect(self):
        for ids, img in zip(self.canvas_ids, self.images):
            [img.mpl_disconnect(id) for id in ids]
        self.canvas_ids.clear()
        self.images.clear()

    def setup_canvas_connections(self):
        self.disconnect()

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
        self.ui.shape.currentIndexChanged.connect(self.select_shape)

    def select_shape(self):
        self.selection = self.ui.shape.currentText()
        self.patch = None

    def create_patch(self):
        if self.selection == 'Rectangle':
            self.patch = patches.Rectangle(self.press, 0, 0, fill=False)
        elif self.selection == 'Ellipse':
            self.patch = patches.Ellipse(self.press, 0, 0, fill=False)
        self.axes.add_patch(self.patch)

    def update_patch(self, event):
        x0, y0 = self.press
        height = event.ydata - y0
        width = event.xdata - x0
        if self.selection == 'Rectangle':
            self.patch.set_height(height)
            self.patch.set_width(width)
        if self.selection == 'Ellipse':
            center = [(width / 2 + x0), (height / 2 + y0)]
            self.patch.set_center(center)
            self.patch.height = height
            self.patch.width = width

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
        img = HexrdConfig().image(self.det, 0)
        if self.selection == 'Rectangle':
            rr, cc = rectangle(self.press, self.end, shape=img.shape)
        elif self.selection == 'Ellipse':
            cx, cy = self.patch.get_center()
            c_rad = self.patch.height / 2
            r_rad = self.patch.width / 2
            rr, cc = ellipse(cx, cy, r_rad, c_rad, shape=img.shape)

        mask = np.ones(img.shape, dtype=bool)
        mask[cc, rr] = False
        self.masks[self.det].append(mask)

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
        files = []
        for key, values in self.masks.items():
            img = HexrdConfig().image(key, 0)
            for mask in values:
                img[~mask] = 0
            files.append([img])

        for canvas in self.parent.image_tab_widget.active_canvases():
            for axes in canvas.raw_axes:
                axes.patches.clear()

        self.disconnect()
        ImageLoadManager().read_data(files)
        self.new_images_loaded.emit()
        self.canvas.draw()
