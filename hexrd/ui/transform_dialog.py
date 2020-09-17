from hexrd.ui import enter_key_filter

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.ui_loader import UiLoader

from PySide2.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSpacerItem

class TransformDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('transforms_dialog.ui', parent)
        self.ui.installEventFilter(enter_key_filter)
        self.det_labels = []
        self.det_cboxes = []

        self.update_gui()
        self.setup_connections()

    def update_gui(self):
        options = [
            '(None)', 'Flip about Vertical Axis', 'Flip about Horizontal Axis', 'Transpose',
            'Rotate 90°', 'Rotate 180°', 'Rotate 270°']
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

    def exec_(self):
        return self.ui.exec_()

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
        ilm.set_state({ 'trans': trans , 'agg': state.get('agg', 0) })
        ilm.begin_processing(postprocess=True)
