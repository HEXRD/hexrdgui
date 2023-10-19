from PySide6.QtWidgets import QDialog, QVBoxLayout

from hexrdgui.indexing.grains_table_model import GrainsTableModel
from hexrdgui.plot_grains import plot_grains
from hexrdgui.ui_loader import UiLoader


class GrainsViewerWidget:

    def __init__(self, grains_table, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('grains_viewer_widget.ui', parent)

        self.grains_table = grains_table

        # pull_spots is not allowed with this grains table view
        self.ui.table_view.pull_spots_allowed = False

        self.setup_connections()

    def setup_connections(self):
        self.ui.plot_grains.clicked.connect(self.plot_grains)

    @property
    def grains_table(self):
        return self.ui.table_view.grains_table

    @grains_table.setter
    def grains_table(self, v):
        # We make a new GrainsTableModel each time for now to save
        # dev time, since the model wasn't designed to be mutable.
        # FIXME: in the future, make GrainsTableModel grains mutable,
        # and then just set the grains table on it, rather than
        # creating a new one every time.
        view = self.ui.table_view
        if v is None:
            view.data_model = None
            return

        kwargs = {
            'grains_table': v,
            'excluded_columns': list(range(9, 15)),
            'parent': view,
        }
        view.data_model = GrainsTableModel(**kwargs)

    def plot_grains(self):
        plot_grains(self.grains_table, None, parent=self.ui)

    @property
    def plot_grains_visible(self):
        return self.ui.plot_grains.isVisible()

    @plot_grains_visible.setter
    def plot_grains_visible(self, b):
        self.ui.plot_grains.setVisible(b)


class GrainsViewerDialog(QDialog):
    def __init__(self, grains_table, parent=None):
        super().__init__(parent)
        self.widget = GrainsViewerWidget(grains_table, self)

        layout = QVBoxLayout()
        layout.addWidget(self.widget.ui)
        self.setLayout(layout)

        self.setWindowTitle('Grains Table Viewer')
        self.resize(800, 200)

        UiLoader().install_dialog_enter_key_filters(self)

    @property
    def plot_grains_visible(self):
        return self.widget.plot_grains_visible

    @plot_grains_visible.setter
    def plot_grains_visible(self, b):
        self.widget.plot_grains_visible = b
