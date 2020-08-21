from PySide2.QtCore import QObject

from hexrd.ui.ui_loader import UiLoader

from matplotlib import patches


class MaskRegionsDialog(QObject):

    def __init__(self, parent=None):
        super(MaskRegionsDialog, self).__init__(parent)

        self.parent = parent
        self.images = []
        self.canvas_ids = []
        self.axes = None
        self.press = []

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
        self.ui.shape.currentIndexChanged.connect(self.select_shape)

    def select_shape(self):
        self.selection = self.ui.shape.currentText()

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

    def button_released(self, event):
        if not self.axes or not self.press:
            return

        self.press.clear()
        self.det = None
        self.canvas.draw()
