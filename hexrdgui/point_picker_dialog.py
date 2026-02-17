from typing import Any

from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
import matplotlib.pyplot as plt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from hexrdgui.utils.matplotlib import remove_artist


class PointPickerDialog(QDialog):
    def __init__(
        self,
        canvas: Any,
        window_title: str = 'Pick Points',
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        if len(canvas.figure.get_axes()) != 1:
            raise NotImplementedError('Only one axis is currently supported')

        self.setWindowTitle(window_title)

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        label = QLabel('Left-click to add points, right-click to remove points')
        layout.addWidget(label)
        layout.setAlignment(label, Qt.AlignmentFlag.AlignHCenter)

        self.canvas = canvas
        layout.addWidget(canvas)

        self.toolbar = NavigationToolbar2QT(canvas, self)
        layout.addWidget(self.toolbar)
        layout.setAlignment(self.toolbar, Qt.AlignmentFlag.AlignHCenter)

        # Add a button box for accept/cancel
        buttons = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        self.button_box = QDialogButtonBox(buttons, self)
        layout.addWidget(self.button_box)

        self.points: list[Any] = []
        self.scatter_artist = self.axis.scatter([], [], c='r', marker='x')

        # Default size
        self.resize(800, 600)

        self.setup_connections()

    def setup_connections(self) -> None:
        self.pick_event_id = self.canvas.mpl_connect(
            'button_press_event', self.point_picked
        )

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.finished.connect(self.on_finished)

    def on_finished(self) -> None:
        # Perform any needed cleanup
        self.disconnect_all()

        if self.scatter_artist is not None:
            remove_artist(self.scatter_artist)
            self.scatter_artist = None

    def disconnect_all(self) -> None:
        self.canvas.mpl_disconnect(self.pick_event_id)

    @property
    def figure(self) -> Any:
        return self.canvas.figure

    @property
    def axis(self) -> Any:
        # We currently assume only one axis
        return self.figure.get_axes()[0]

    def point_picked(self, event: Any) -> None:
        if event.button == 3:
            # Right-click removes points
            self.undo_point()
            return

        if event.button != 1:
            # Ignore anything other than left-click at this point.
            return

        if event.inaxes is None:
            # The axis was not clicked. Ignore.
            return

        if self.axis.get_navigate_mode() is not None:
            # Zooming or panning is active. Ignore this point.
            return

        self.points.append((event.xdata, event.ydata))
        self.update_scatter_plot()

    def undo_point(self) -> None:
        if not self.points:
            return

        self.points.pop()
        self.update_scatter_plot()

    def update_scatter_plot(self) -> None:
        # We unfortunately cannot set an empty list. So do nans instead.
        points = self.points if self.points else [np.nan, np.nan]
        self.scatter_artist.set_offsets(points)
        self.canvas.draw_idle()


if __name__ == '__main__':
    import sys

    import numpy as np

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # spectrum = np.load('spectrum.npy')

    # Generate 4 sine waves for a test
    length = np.pi * 2 * 4
    num_points = 1000
    spectrum = np.vstack(
        (
            np.arange(num_points),
            np.sin(np.arange(0, length, length / num_points)) * 50 + 50,
        )
    ).T

    fig, ax = plt.subplots()
    ax.plot(*spectrum.T, '-k')

    ax.set_xlabel(r'2$\theta$')
    ax.set_ylabel(r'intensity (a.u.)')

    dialog = PointPickerDialog(fig.canvas)
    dialog.show()
    dialog.accepted.connect(lambda: print('Accepted:', dialog.points))
    app.exec()
