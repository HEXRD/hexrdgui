from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui import constants, enter_key_filter


class WorkflowSelectionDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('workflow_selection_dialog.ui', parent)
        self.ui.installEventFilter(enter_key_filter)
        self.init_gui()
        self.update_gui_from_config()
        self.setup_connections()

    def init_gui(self):
        for w in constants.WORKFLOWS:
            self.ui.workflowComboBox.addItem(w)

    def setup_connections(self):
        self.ui.accepted.connect(self.accepted)
        self.ui.rejected.connect(self.rejected)

    def update_gui_from_config(self):
        self.ui.workflowComboBox.setCurrentText(HexrdConfig().workflow)

    def accepted(self):
        HexrdConfig().set_workflow(self.ui.workflowComboBox.currentText())

    def rejected(self):
        # If the user cancels this by accident the first time they start the
        # program, they will be running without a workflow!
        # Avoid this by ensuring a workflow gets set.
        if HexrdConfig().workflow is None:
            HexrdConfig().set_workflow(self.ui.workflowComboBox.currentText())

    def show(self):
        self.update_gui_from_config()
        self.ui.show()
