import numpy as np

from PySide6.QtCore import QItemSelectionModel, QObject, Qt, Signal
from PySide6.QtWidgets import QTableWidgetItem

from hexrd.rotations import quatOfExpMap

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.fiber_pick_utils import _angles_from_orientation, _pick_to_fiber
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class HandPickedFibersWidget(QObject):

    fiber_step_modified = Signal(float)

    def __init__(self, data, canvas, ax, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('hand_picked_fibers_widget.ui', parent)

        self.data = data
        self.canvas = canvas
        self.ax = ax

        self._active = True

        self.cached_picked_spots = {}
        self.generated = np.empty((0,))
        self.picked = np.empty((0, 3))

        self.current_hkl_index = 0
        self.current_spots = np.empty((0,))
        self.last_eta = None
        self.last_ome = None
        self.last_hkl_index = None

        self.setup_connections()

    def setup_connections(self):
        self.ui.current_slider.valueChanged.connect(
            self.current_slider_value_changed)

        self.ui.current_angle.valueChanged.connect(
            self.current_angle_value_changed)

        self.ui.add_button.clicked.connect(self.add_current)

        self.ui.picked_table.selectionModel().selectionChanged.connect(
            self.picked_table_selection_changed)

        self.ui.delete_selected.clicked.connect(self.deleted_selected_rows)

        self.ui.fiber_step.valueChanged.connect(self.fiber_step_value_changed)

        self.canvas.mpl_connect('button_press_event', self.plot_clicked)

    def update_gui(self):
        self.ui.current_slider.setRange(0, self.num_picked - 1)
        self.ui.current_angle.setSingleStep(self.fiber_step)

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, v):
        if self._active == v:
            return

        self._active = v

        self.clear_generated()
        self.clear_selected_artists()
        self.select_rows([])

    def clear_generated(self):
        # Reset the latest picks to None
        self.last_eta = None
        self.last_ome = None
        self.last_hkl_index = None

        self.generated = np.empty((0,))
        self.ui.current_slider.setValue(0)
        # In case the value didn't change. This shouldn't be expensive,
        # so it's okay to run it twice.
        self.update_current()

    def plot_clicked(self, event):
        if not self.active:
            # If this widget is inactive, just return
            return

        if not event.button == 3:
            # We only hand pick on right-click
            return

        self.last_eta = event.xdata
        self.last_ome = event.ydata
        self.last_hkl_index = self.current_hkl_index

        self.recreate_generated()

    def recreate_generated(self):
        pick_coords = (self.last_eta, self.last_ome)
        if any(x is None for x in pick_coords):
            # No picked coords. Just return.
            return

        hkl_index = self.last_hkl_index
        if hkl_index is None or hkl_index >= len(self.data.dataStore):
            # Invalid hkl index. Return.
            return

        instr = create_hedm_instrument()

        kwargs = {
            'pick_coords': pick_coords,
            'eta_ome_maps': self.data,
            'map_index': hkl_index,
            'step': self.fiber_step,
            'beam_vec': instr.beam_vector,
            'chi': instr.chi,
            'as_expmap': True,
        }
        self.generated = _pick_to_fiber(**kwargs)

        self.ui.current_slider.setValue(0)
        # In case the value didn't change. This shouldn't be expensive,
        # so it's okay to run it twice.
        self.update_current()

    def update_current(self):
        enable = len(self.generated) > 0

        enable_list = [
            self.ui.current_slider,
            self.ui.current_angle,
            self.ui.current_orientation_0,
            self.ui.current_orientation_1,
            self.ui.current_orientation_2,
            self.ui.add_button,
        ]
        for w in enable_list:
            w.setEnabled(enable)

        for i, v in enumerate(self.current_orientation):
            w = getattr(self.ui, f'current_orientation_{i}')
            w.setValue(v)

        angle = self.current_index * self.fiber_step
        self.ui.current_angle.setValue(angle)

        self.generate_current_spots()
        self.update_current_plot()

    def generate_current_spots(self):
        if self.current_index >= len(self.generated):
            fibers = []
        else:
            fibers = self.generated[self.current_index]

        self.current_spots = self.general_spots(fibers)

    def general_spots(self, fibers):
        if len(fibers) == 0:
            return np.empty((0,))

        kwargs = {
            'instr': create_hedm_instrument(),
            'eta_ome_maps': self.data,
            'orientation': fibers,
        }
        return _angles_from_orientation(**kwargs)

    def clear_current_plot(self):
        if hasattr(self, '_current_lines'):
            self._current_lines.remove()
            del self._current_lines

    def update_current_plot(self):
        self.clear_current_plot()
        hkl_idx = self.current_hkl_index
        if len(self.current_spots) <= hkl_idx:
            self.draw()
            return

        current = self.current_spots[hkl_idx]
        if current.size:
            kwargs = {
                'x': current[:, 0],
                'y': current[:, 1],
                's': 36,
                'c': 'm',
                'marker': '+',
            }
            self._current_lines = self.ax.scatter(**kwargs)

        self.draw()

    @property
    def current_orientation(self):
        if len(self.generated) == 0:
            return np.array([0, 0, 0])

        return self.generated[self.current_index]

    @property
    def current_index(self):
        return self.ui.current_slider.value()

    def current_slider_value_changed(self):
        self.update_current()

    def current_angle_value_changed(self, v):
        new_slider_index = round(v / self.fiber_step)
        self.ui.current_slider.setValue(new_slider_index)

        # This usually already happens, but make sure the angle gets
        # updated to its new value (it may need to round to the nearest).
        angle = self.current_index * self.fiber_step
        self.ui.current_angle.setValue(angle)

    def add_current(self):
        to_stack = (self.picked, self.current_orientation)
        self.picked = np.vstack(to_stack)
        self.update_picked_table()

        self.clear_generated()

        table = self.ui.picked_table
        last_row = table.rowCount() - 1
        self.select_rows([last_row])

    def update_picked_table(self):
        table = self.ui.picked_table
        table.clearContents()
        table.setColumnCount(3)
        table.setRowCount(len(self.picked))
        for i, orientation in enumerate(self.picked):
            for j in range(3):
                item = QTableWidgetItem(f'{orientation[j]:.4f}')
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(i, j, item)

    @property
    def picked_quaternions(self):
        # We store these as 3D exp maps. Convert and return as quaternions.
        quats = quatOfExpMap(self.picked.T)
        if quats.ndim == 1:
            # quatOfExpMap() squeezes the output. We must reshape it.
            quats = np.atleast_2d(quats).T

        return quats

    @property
    def picked(self):
        return self._picked

    @picked.setter
    def picked(self, v):
        self._picked = v
        # Clear the cache for hand picked spots
        self.cached_picked_spots.clear()

    def clear_selected_artists(self):
        lines = getattr(self, '_selected_artists', [])
        while lines:
            lines.pop(0).remove()

    @property
    def selected_rows(self):
        selected = self.ui.picked_table.selectionModel().selectedRows()
        selected = [] if None else selected
        return [x.row() for x in selected]

    def picked_table_selection_changed(self):
        self.draw_selected()

        enable_delete = len(self.selected_rows) > 0
        self.ui.delete_selected.setEnabled(enable_delete)

    def spots_for_hand_picked_quaternion(self, i):
        if i >= len(self.picked):
            return None

        cache = self.cached_picked_spots

        # Check the cache first. If not present, add to the cache.
        if i not in cache:
            fiber = self.picked[i]
            if not fiber.size:
                return None

            cache[i] = self.general_spots(fiber)

        return cache[i][self.current_hkl_index]

    def draw_selected(self):
        self.clear_selected_artists()

        artists = []
        for i in self.selected_rows:
            spots = self.spots_for_hand_picked_quaternion(i)
            if spots is None or spots.size == 0:
                continue

            kwargs = {
                'x': spots[:, 0],
                'y': spots[:, 1],
                's': 36,
                'marker': 'o',
                'facecolors': 'none',
                'edgecolors': 'c',
                'linewidths': 1,
            }
            artists.append(self.ax.scatter(**kwargs))

        self._selected_artists = artists
        self.draw()

    def select_rows(self, rows):
        table = self.ui.picked_table
        selection_model = table.selectionModel()

        with block_signals(selection_model):
            selection_model.clearSelection()
            command = QItemSelectionModel.Select | QItemSelectionModel.Rows

            for i in rows:
                if i is None or i >= table.rowCount():
                    # Out of range. Don't do anything.
                    continue

                # Select the row
                model_index = selection_model.model().index(i, 0)
                selection_model.select(model_index, command)

        self.picked_table_selection_changed()

    def deleted_selected_rows(self):
        self.picked = np.delete(self.picked, self.selected_rows, 0)
        # There should be no selection now
        self.select_rows([])
        self.update_picked_table()

    def fiber_step_value_changed(self, v):
        prev_angle = self.ui.current_angle.value()

        self.ui.current_slider.setRange(0, self.num_picked - 1)
        self.ui.current_angle.setSingleStep(self.fiber_step)

        if self.active:
            # Re-create the generated fibers
            # Restore the closest value to the previous angle
            self.recreate_generated()
            self.ui.current_angle.setValue(prev_angle)

        self.fiber_step_modified.emit(v)

    @property
    def fiber_step(self):
        return self.ui.fiber_step.value()

    @fiber_step.setter
    def fiber_step(self, v):
        self.ui.fiber_step.setValue(v)

    @property
    def num_picked(self):
        return round(360 / self.fiber_step)

    def draw(self):
        self.canvas.draw()
