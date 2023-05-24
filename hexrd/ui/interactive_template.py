import numpy as np

from PySide2.QtCore import Qt

from matplotlib import patches
from matplotlib.path import Path
from matplotlib.transforms import Affine2D

from skimage.draw import polygon

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui import resource_loader
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils import has_nan


class InteractiveTemplate:
    def __init__(self, parent=None):
        self.parent = parent.image_tab_widget.image_canvases[0]
        self.ax = self.parent.axes_images[0]
        self.panels = create_hedm_instrument().detectors
        self.img = None
        self.shape = None
        self.press = None
        self.total_rotation = 0.
        self.shape_styles = []
        self.translation = [0, 0]
        self.complete = False
        self.event_key = None
        self.parent.setFocusPolicy(Qt.ClickFocus)

    @property
    def raw_axes(self):
        return list(self.parent.raw_axes.values())[0]

    def update_image(self, img):
        self.img = img

    def rotate_shape(self, angle):
        angle = np.radians(angle)
        self.rotate_template(self.shape.xy, angle)
        self.redraw()

    def create_shape(self, module, file_name, det, instr):
        self.complete = False
        with resource_loader.resource_path(module, file_name) as f:
            data = np.loadtxt(f)
        verts = self.panels['default'].cartToPixel(data)
        verts[:, [0, 1]] = verts[:, [1, 0]]
        self.shape = patches.Polygon(verts, fill=False, lw=1, color='cyan')
        if has_nan(verts):
            # This template contains more than one polygon and the last point
            # should not be connected to the first. See Tardis IP for example.
            self.shape.set_closed(False)
        self.shape_styles.append({'line': '-', 'width': 1, 'color': 'cyan'})
        self.update_position(instr, det)
        self.connect_translate_rotate()
        self.raw_axes.add_patch(self.shape)
        self.redraw()

    def update_style(self, style, width, color):
        self.shape_styles[-1] = {'line': style, 'width': width, 'color': color}
        self.shape.set_linestyle(style)
        self.shape.set_linewidth(width)
        self.shape.set_edgecolor(color)
        self.redraw()

    def update_position(self, instr, det):
        pos = HexrdConfig().boundary_position(instr, det)
        if pos is None:
            self.center = self.get_midpoint()
        else:
            dx, dy = pos.get('translation', [0, 0])
            self.translation = [dx, dy]
            self.translate_template(dx, dy)
            self.total_rotation = pos['angle']
            self.rotate_template(self.shape.xy, pos['angle'])
        if instr == 'PXRDIP':
            self.rotate_shape(angle=90)

    @property
    def template(self):
        return self.shape

    @property
    def masked_image(self):
        mask = self.mask()
        return self.img, mask

    @property
    def bounds(self):
        l, r, b, t = self.ax.get_extent()
        x0, y0 = np.nanmin(self.shape.xy, axis=0)
        x1, y1 = np.nanmax(self.shape.xy, axis=0)
        return np.array([max(np.floor(y0), t),
                         min(np.ceil(y1), b),
                         max(np.floor(x0), l),
                         min(np.ceil(x1), r)]).astype(int)

    def cropped_image(self, height, width):
        y0, y1, x0, x1 = self.bounds
        y1 = y0+height if height else y1
        x1 = x0+width if width else x1
        self.img = self.img[y0:y1, x0:x1]
        self.cropped_shape = self.shape.xy - np.array([x0, y0])
        return self.img

    @property
    def rotation(self):
        return self.total_rotation

    def clear(self):
        if self.shape in self.raw_axes.patches:
            self.shape.remove()
            self.redraw()
        self.total_rotation = 0.

    def save_boundary(self, color):
        if self.shape in self.raw_axes.patches:
            self.shape.set_linestyle('--')
            self.redraw()

    def toggle_boundaries(self, show):
        if show:
            for patch, style in zip(self.patches, self.shape_styles):
                shape = patches.Polygon(
                    patch.xy,
                    fill=False,
                    ls='--',
                    lw=style['width'],
                    color=style['color']
                )
                if has_nan(patch.xy):
                    # This template contains more than one polygon and the last point
                    # should not be connected to the first. See Tardis IP for example.
                    shape.set_closed(False)
                self.raw_axes.add_patch(shape)
            if self.shape:
                self.shape = self.raw_axes.patches[-1]
                self.shape.remove()
                self.shape.set_linestyle(self.shape_styles[-1]['line'])
                self.raw_axes.add_patch(self.shape)
                self.connect_translate_rotate()
            self.redraw()
        else:
            if self.shape:
                self.disconnect()
            self.patches = [p for p in self.raw_axes.patches]
        self.redraw()

    def disconnect(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
        self.parent.mpl_disconnect(self.motion_cid)
        self.parent.mpl_disconnect(self.key_press_cid)
        self.parent.mpl_disconnect(self.button_drag_cid)

    def completed(self):
        self.disconnect()
        self.img = None
        self.shape = None
        self.press = None
        self.total_rotation = 0.
        self.complete = True

    def mask(self):
        col, row = self.cropped_shape.T
        col_nans = np.where(np.isnan(col))[0]
        row_nans = np.where(np.isnan(row))[0]
        cols = np.split(col, col_nans)
        rows = np.split(row, row_nans)
        master_mask = np.zeros(self.img.shape, dtype=bool)
        for c, r in zip(cols, rows):
            c = c[~np.isnan(c)]
            r = r[~np.isnan(r)]
            rr, cc = polygon(r, c, shape=self.img.shape)
            mask = np.zeros(self.img.shape, dtype=bool)
            mask[rr, cc] = True
            master_mask = np.logical_xor(master_mask, mask)
        self.img[~master_mask] = 0
        return master_mask

    def get_paths(self):
        all_paths = []
        points = []
        codes = []
        for coords in self.shape.get_path().vertices[:-1]:
            if np.isnan(coords).any():
                codes[0] = Path.MOVETO
                all_paths.append(Path(points, codes))
                codes = []
                points = []
            else:
                codes.append(Path.LINETO)
                points.append(coords)
        codes[0] = Path.MOVETO
        all_paths.append(Path(points, codes))

        return all_paths

    def redraw(self):
        self.parent.draw_idle()

    def scale_template(self, sx=1, sy=1):
        xy = self.shape.xy
        # Scale the shape
        scaled_xy = Affine2D().scale(sx, sy).transform(xy)
        self.shape.set_xy(scaled_xy)

        # Translate the shape back to where it was
        diff = np.array(self.center) - np.array(self.get_midpoint())
        new_xy = scaled_xy + diff
        self.shape.set_xy(new_xy)
        self.redraw()

    def on_press(self, event):
        self.event_key = event.key
        if event.key is None:
            self.on_press_translate(event)
        elif event.key == 'shift':
            self.on_press_rotate(event)

    def on_release(self, event):
        if self.event_key is None:
            self.on_translate_release(event)
        elif self.event_key == 'shift':
            self.on_rotate_release(event)

    def on_key(self, event):
        if 'shift' in event.key:
            self.on_key_rotate(event)
        else:
            self.on_key_translate(event)

    def connect_translate_rotate(self):
        self.button_press_cid = self.parent.mpl_connect(
            'button_press_event', self.on_press)
        self.button_release_cid = self.parent.mpl_connect(
            'button_release_event', self.on_release)
        self.motion_cid = self.parent.mpl_connect(
            'motion_notify_event', self.on_translate)
        self.key_press_cid = self.parent.mpl_connect(
            'key_press_event', self.on_key)
        self.button_drag_cid = self.parent.mpl_connect(
            'motion_notify_event', self.on_rotate)
        self.parent.setFocus()

    def translate_template(self, dx, dy):
        self.shape.set_xy(self.shape.xy + np.array([dx, dy]))
        self.center = self.get_midpoint()
        self.redraw()

    def on_key_translate(self, event):
        dx0, dy0 = self.translation
        dx1, dy1 = 0, 0
        delta = 0.5
        if event.key == 'right':
            dx1 = delta
        elif event.key == 'left':
            dx1 = -delta
        elif event.key == 'up':
            dy1 = -delta
        elif event.key == 'down':
            dy1 = delta
        else:
            return

        self.translation = [dx0 + dx1, dy0 + dy1]
        self.shape.set_xy(self.shape.xy + np.array([dx1, dy1]))
        self.redraw()

    def on_press_translate(self, event):
        if event.inaxes != self.shape.axes:
            return

        contains, info = self.shape.contains(event)
        if not contains:
            return
        self.press = self.shape.xy, event.xdata, event.ydata

    def on_translate(self, event):
        if self.press is None or event.inaxes != self.shape.axes:
            return

        xy, xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.center = self.get_midpoint()
        self.shape.set_xy(xy + np.array([dx, dy]))
        self.redraw()

    def on_translate_release(self, event):
        if self.press is None:
            return

        xy, xpress, ypress = self.press
        dx0, dy0 = self.translation
        dx1 = event.xdata - xpress
        dy1 = event.ydata - ypress
        self.translation = [dx0 + dx1, dy0 + dy1]
        self.shape.set_xy(xy + np.array([dx1, dy1]))
        self.press = None
        self.redraw()

    def on_press_rotate(self, event):
        if event.inaxes != self.shape.axes:
            return

        contains, info = self.shape.contains(event)
        if not contains:
            return
        # FIXME: Need to come back to this to understand why we
        # need to set the press value twice
        self.press = self.shape.xy, event.xdata, event.ydata
        self.center = self.get_midpoint()
        self.shape.set_transform(self.ax.axes.transData)
        self.press = self.shape.xy, event.xdata, event.ydata

    def rotate_template(self, points, angle):
        x = [np.cos(angle), np.sin(angle)]
        y = [-np.sin(angle), np.cos(angle)]
        verts = np.dot(points - self.center, np.array([x, y])) + self.center
        self.shape.set_xy(verts)

    def on_rotate(self, event):
        if self.press is None or event.inaxes != self.shape.axes or event.key != 'shift':
            return

        x, y = self.center
        xy, xpress, ypress = self.press
        angle = self.get_angle(event)
        self.rotate_template(xy, angle)
        self.redraw()

    def on_key_rotate(self, event):
        angle = 0.00175
        # !!! only catch arrow keys
        if event.key == 'shift+left' or event.key == 'shift+up':
            angle *= -1.
        elif event.key == 'shift+right' and event.key == 'shift+down':
            angle *= 1.
        self.total_rotation += angle
        self.rotate_template(self.shape.xy, angle)
        self.redraw()

    def get_midpoint(self):
        x0, y0 = np.nanmin(self.shape.xy, axis=0)
        x1, y1 = np.nanmax(self.shape.xy, axis=0)
        return [(x1 + x0)/2, (y1 + y0)/2]

    def mouse_position(self, e):
        xmin, xmax, ymin, ymax = self.ax.get_extent()
        x, y = self.get_midpoint()
        xdata = e.xdata
        ydata = e.ydata
        if xdata is None:
            if e.x < x:
                xdata = 0
            else:
                xdata = xmax
        if ydata is None:
            if e.y < y:
                ydata = 0
            else:
                ydata = ymax
        return xdata, ydata

    def get_angle(self, e):
        xy, xdata, ydata = self.press
        v0 = np.array([xdata, ydata]) - np.array(self.center)
        v1 = np.array(self.mouse_position(e)) - np.array(self.center)
        v0_u = v0/np.linalg.norm(v0)
        v1_u = v1/np.linalg.norm(v1)
        angle = np.arctan2(np.linalg.det([v0_u, v1_u]), np.dot(v0_u, v1_u))
        return angle

    def on_rotate_release(self, event):
        if self.press is None:
            return
        angle = self.get_angle(event)
        self.total_rotation += angle
        y, x = self.center
        xy, xpress, ypress = self.press
        self.press = None
        self.rotate_template(xy, angle)
        self.redraw()
