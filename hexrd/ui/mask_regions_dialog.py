from PySide2.QtCore import QObject, Signal, Qt

from hexrd.ui.create_raw_mask import convert_polar_to_raw, create_raw_mask
from hexrd.ui.create_polar_mask import create_polar_mask_from_raw
from hexrd.ui.interactive_template import InteractiveTemplate
from hexrd.ui.utils import unique_name
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.constants import ViewType
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import add_sample_points

from matplotlib import patches


class MaskRegionsDialog(QObject):

    # Emitted when new images are loaded
    new_mask_added = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.parent = parent
        self.canvas_ids = []
        self.axes = None
        self.bg_cache = None
        self.press = []
        self.added_templates = []
        self.interactive_templates = {}
        self.canvas = parent.image_tab_widget.active_canvas
        self.image_mode = None
        self.raw_mask_coords = []
        self.drawing_axes = None

        loader = UiLoader()
        self.ui = loader.load_file('mask_regions_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.setup_canvas_connections()
        self.setup_ui_connections()
        self.select_shape()

    def show(self):
        self.ui.show()

    def disconnect(self):
        for id in self.canvas_ids:
            self.canvas.mpl_disconnect(id)
        self.canvas_ids.clear()

    def setup_canvas_connections(self):
        self.disconnect()

        self.canvas_ids.append(self.canvas.mpl_connect(
            'button_press_event', self.button_pressed))
        self.canvas_ids.append(self.canvas.mpl_connect(
            'motion_notify_event', self.drag_motion))
        self.canvas_ids.append(self.canvas.mpl_connect(
            'button_release_event', self.button_released))
        self.canvas_ids.append(self.canvas.mpl_connect(
            'axes_enter_event', self.axes_entered))
        self.canvas_ids.append(self.canvas.mpl_connect(
            'axes_leave_event', self.axes_exited))

    def setup_ui_connections(self):
        self.ui.button_box.accepted.connect(self.apply_masks)
        self.ui.button_box.rejected.connect(self.cancel)
        self.ui.rejected.connect(self.cancel)
        self.ui.shape.currentIndexChanged.connect(self.select_shape)
        self.ui.undo.clicked.connect(self.undo_selection)

    def update_undo_enable_state(self):
        enabled = bool(len(self.added_templates))
        self.ui.undo.setEnabled(enabled)

    def select_shape(self):
        self.selection = self.ui.shape.currentText()
        self.interactive_template = None

    def create_interactive_template(self):
        kwargs = {
            'fill': False,
            'animated': True,
        }
        self.interactive_template = InteractiveTemplate(
            self.canvas, self.det, axes=self.axes)
        self.interactive_template.create_polygon([[0,0]], **kwargs)
        self.interactive_template.update_style(color='red')
        self.added_templates.append(self.det)

    def update_interactive_template(self, event):
        x0, y0 = self.press
        height = event.ydata - y0
        width = event.xdata - x0
        if self.selection == 'Rectangle':
            shape = patches.Rectangle(self.press, width, height)
        if self.selection == 'Ellipse':
            center = [(width / 2 + x0), (height / 2 + y0)]
            shape = patches.Ellipse(center, width, height)
        verts = shape.get_patch_transform().transform(
            shape.get_path().vertices[:-1])
        verts = add_sample_points(verts, 300)
        self.interactive_template.template.set_xy(verts)
        self.interactive_template.center = (
            self.interactive_template.get_midpoint())

    def discard_interactive_template(self):
        det = self.added_templates.pop()
        it = self.interactive_templates[det].pop()
        it.disconnect()
        it.template.remove()

    def undo_selection(self):
        if not self.added_templates:
            return

        self.discard_interactive_template()
        self.canvas.draw_idle()
        self.update_undo_enable_state()
        self.interactive_template = None

    def axes_entered(self, event):
        self.image_mode = self.canvas.mode

        if event.inaxes is self.canvas.azimuthal_integral_axis:
            # Ignore the azimuthal integral axis in the polar view
            return

        self.axes = event.inaxes

    def axes_exited(self, event):
        # If we are drawing a rectangle and we are close to the canvas edges,
        # snap it into place.
        self.snap_rectangle_to_edges(event)
        self.axes = None

    def snap_rectangle_to_edges(self, event):
        if not self.drawing_axes or self.selection != 'Rectangle':
            # We are either not still drawing or it is not a rectangle
            return

        # Snap the rectangle to the borders
        tth_min = HexrdConfig().polar_res_tth_min
        tth_max = HexrdConfig().polar_res_tth_max
        eta_min = HexrdConfig().polar_res_eta_min
        eta_max = HexrdConfig().polar_res_eta_max

        tth_range = tth_max - tth_min
        eta_range = eta_max - eta_min

        eta_pixel_size = HexrdConfig().polar_pixel_size_eta
        tth_pixel_size = HexrdConfig().polar_pixel_size_tth

        # If the mouse pointer is closer than 1% to any edges,
        # snap the coordinates over and update the patch.
        any_changes = False
        tol = 0.01
        if abs(event.xdata - tth_min) / tth_range < tol:
            # Add a small buffer so it isn't out of bounds by accident
            event.xdata = tth_min + tth_pixel_size / 2
            any_changes = True
        elif abs(event.xdata - tth_max) / tth_range < tol:
            # Subtract a small buffer so it isn't out of bounds by accident
            event.xdata = tth_max - tth_pixel_size / 2
            any_changes = True
        if abs(event.ydata - eta_min) / eta_range < tol:
            # Add a small buffer so it doesn't wrap around by accident
            event.ydata = eta_min + eta_pixel_size / 2
            any_changes = True
        elif abs(event.ydata - eta_max) / eta_range < tol:
            # Subtract a small buffer so it doesn't wrap around by accident
            event.ydata = eta_max - eta_pixel_size / 2
            any_changes = True

        if any_changes:
            # Trigger another drag motion event where we move the borders
            self.drag_motion(event)

    def check_pick(self, event):
        for templates in self.interactive_templates.values():
            for it in templates:
                it.static_mode = True
                transformed_click = it.template.get_transform().transform(
                    (event.xdata, event.ydata))
                if it.template.contains_point(transformed_click):
                    if self.interactive_template:
                        self.interactive_template.disconnect()
                    self.interactive_template = it
                    self.interactive_template.static_mode = False

    def button_pressed(self, event):
        if self.image_mode not in (ViewType.raw, ViewType.polar):
            print('Masking must be done in raw or polar view')
            return

        if not self.axes:
            return

        if event.button == 1:
            # Determine if selecting an existing template or drawing a new one
            self.check_pick(event)

            if (self.interactive_template and
                    not self.interactive_template.static_mode):
                return

            self.press = [event.xdata, event.ydata]
            self.det = self.axes.get_title()
            if not self.det:
                self.det = self.image_mode
            self.create_interactive_template()

            # For animating the patch
            self.canvas.draw() # Force canvas re-draw before caching
            self.bg_cache = self.canvas.copy_from_bbox(self.axes.bbox)

            self.drawing_axes = self.axes

    def drag_motion(self, event):
        if (
            not self.axes or
            not self.press or
            self.axes is not self.drawing_axes
        ):
            return

        if not self.interactive_template.static_mode:
            return

        self.update_interactive_template(event)

        # Update animation of patch
        self.canvas.restore_region(self.bg_cache)
        self.axes.draw_artist(self.interactive_template.template)
        self.canvas.blit(self.axes.bbox)

    def save_line_data(self):
        for det, its in self.interactive_templates.items():
            for it in its:
                data_coords = it.template.get_patch_transform().transform(
                    it.template.get_path().vertices[:-1])

                # So that this gets converted between raw and polar correctly,
                # make sure there are at least 300 points.
                data_coords = add_sample_points(data_coords, 300)

                if self.image_mode == ViewType.raw:
                    self.raw_mask_coords.append((det, data_coords))
                elif self.image_mode == ViewType.polar:
                    self.raw_mask_coords.append([data_coords])

    def create_masks(self):
        for data in self.raw_mask_coords:
            name = unique_name(
                HexrdConfig().raw_mask_coords, f'{self.image_mode}_mask_0')
            if self.image_mode == 'raw':
                HexrdConfig().raw_mask_coords[name] = [data]
                create_raw_mask(name, [data])
            elif self.image_mode == 'polar':
                raw_coords = convert_polar_to_raw(data)
                HexrdConfig().raw_mask_coords[name] = raw_coords
                create_polar_mask_from_raw(name, raw_coords)
            HexrdConfig().visible_masks.append(name)

        masks_changed_signal = {
            'raw': HexrdConfig().raw_masks_changed,
            'polar': HexrdConfig().polar_masks_changed
        }
        masks_changed_signal[self.image_mode].emit()

    def button_released(self, event):
        if not self.press or not self.interactive_template.static_mode:
            return

        # Save it
        self.interactive_template.update_style(color='black')
        self.interactive_templates.setdefault(self.det, []).append(
            self.interactive_template)

        # Turn off animation so the patch will stay
        self.interactive_template.template.set_animated(False)

        self.press.clear()
        self.det = None
        self.drawing_axes = None
        self.canvas.draw_idle()

        self.update_undo_enable_state()

    def apply_masks(self):
        if not self.interactive_templates:
            return

        self.save_line_data()
        self.disconnect()
        self.create_masks()
        while self.added_templates:
            self.discard_interactive_template()
        self.new_mask_added.emit(self.image_mode)
        self.disconnect()
        self.reset_all()

    def cancel(self):
        while self.added_templates:
            self.discard_interactive_template()

        self.disconnect()
        if self.canvas is not None:
            self.canvas.draw_idle()

    def canvas_changed(self, canvas):
        self.apply_masks()
        self.canvas = canvas
        if self.ui.isVisible():
            self.setup_canvas_connections()

    def reset_all(self):
        self.press.clear()
        self.added_templates.clear()
        for key in self.interactive_templates.keys():
            interactive_templates = self.interactive_templates[key]
            [it.disconnect() for it in interactive_templates]
        self.interactive_templates.clear()
        self.raw_mask_coords.clear()
