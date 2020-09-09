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
        HexrdConfig().workflow = self.ui.workflowComboBox.currentText()
        HexrdConfig().save_workflow()

    def rejected(self):
        pass

    def show(self):
        self.ui.show()
