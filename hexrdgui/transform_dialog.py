from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_load_manager import ImageLoadManager
from hexrdgui.ui_loader import UiLoader

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSpacerItem

class TransformDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('transforms_dialog.ui', parent)
        self.det_labels = []
        self.det_cboxes = []

        self.update_gui()
        self.setup_connections()

    def update_gui(self):
        options = [
            '(None)', 'Mirror about Vertical', 'Mirror about Horizontal',
            'Transpose', 'Rotate 90°', 'Rotate 180°', 'Rotate 270°']
        for i, det in enumerate(HexrdConfig().detector_names):
            hbox = QHBoxLayout()
            # Add label
            label = QLabel(det)
            hbox.addWidget(label)
            self.det_labels.append(label)
            # Add spacer
            hbox.addSpacerItem(QSpacerItem(40, 20))
            # Add combo box
            cb = QComboBox()
            hbox.addWidget(cb)
            self.det_cboxes.append(cb)
            cb.addItems(options)
            self.ui.dialog_layout.insertLayout(i + 2, hbox)
        for label, cbox in zip(self.det_labels, self.det_cboxes):
            label.setEnabled(False)
            cbox.setEnabled(False)

    def setup_connections(self):
        self.ui.update_all.clicked.connect(self.toggle_options)
        self.ui.update_each.clicked.connect(self.toggle_options)
        self.ui.accepted.connect(self.apply_transforms)

    def exec(self):
        return self.ui.exec()

    def toggle_options(self):
        enabled = self.ui.update_all.isChecked()
        self.ui.all_label.setEnabled(enabled)
        self.ui.transform_all_menu.setEnabled(enabled)
        for label, cbox in zip(self.det_labels, self.det_cboxes):
            label.setEnabled(not enabled)
            cbox.setEnabled(not enabled)

    def apply_transforms(self):
        num_dets = len(HexrdConfig().detector_names)
        trans = []
        if self.ui.update_all.isChecked():
            idx = self.ui.transform_all_menu.currentIndex()
            trans = [idx for x in range(num_dets)]
        else:
            for combo in self.det_cboxes:
                trans.append(combo.currentIndex())

        ilm = ImageLoadManager()
        state = HexrdConfig().load_panel_state
        state['trans'] = trans

        new_state = {
            'trans': trans,
            'agg': state.get('agg', 0),
        }

        ilm.read_data(ui_parent=self.ui, state=new_state, postprocess=True)
