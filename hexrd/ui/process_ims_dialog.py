import copy
import fabio

from PySide2.QtWidgets import QDialog, QRadioButton

from hexrd import imageseries

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class ProcessIMSDialog(QDialog):

    def __init__(self, parent=None):
        self.parent = parent
        super(ProcessIMSDialog, self).__init__(parent.ui)

        self.names = list(HexrdConfig().imageseries().keys())
        self.ims = HexrdConfig().imageseries()
        self.original_ims = copy.deepcopy(self.ims)
        self.tabs = []
        self.oplists = {}
        self.prev_tab = None
        self.frame_list = None
        self.dark_img = None

        loader = UiLoader()
        self.ui = loader.load_file('process_ims_dialog.ui', parent.ui)

        self.set_defaults()
        self.create_tabs(loader)
        self.ui.show()

        self.setup_connections()

    def setup_connections(self):
        self.ui.buttonBox.accepted.connect(self.apply_to_one)
        self.ui.buttonBox.rejected.connect(self.cancel)
        self.ui.apply.clicked.connect(self.apply_to_one)
        self.ui.detectors.currentChanged.connect(self.set_data)
        self.ui.detectors.currentChanged.connect(self.set_prev_tab)
        self.ui.offset.valueChanged.connect(self.create_frame_list)
        self.ui.max_total.valueChanged.connect(self.create_frame_list)

    def setup_tab_connections(self, i):
        self.tabs[i].dark_combo.currentIndexChanged.connect(self.set_dark)
        self.tabs[i].upload_dark.clicked.connect(self.load_image)
        self.tabs[i].apply_to_all.clicked.connect(self.apply_to_all)

    def create_tabs(self, loader):
        for i in range(len(self.names)):
            tab_ui = loader.load_file('tab_frame.ui', self.ui)
            self.ui.detectors.addTab(tab_ui, self.names[i])
            self.tabs.append(tab_ui)
            self.setup_tab_connections(i)

        self.set_prev_tab()

    def set_defaults(self, max_frames=0, min_frames=0):
        if not max_frames:
            max_frames = len(self.ims[self.names[0]])

        self.ui.offset.setMinimum(min_frames)
        self.ui.max_total.setMinimum(min_frames)

        self.ui.offset.setMaximum(max_frames)
        self.ui.max_total.setMaximum(max_frames)

        self.ui.offset.setValue(min_frames)
        self.ui.max_total.setValue(max_frames)

        self.frame_list = range(min_frames, max_frames)

    def set_prev_tab(self):
        self.prev_tab = self.ui.detectors.tabText(
          self.ui.detectors.currentIndex())

    def get_current_index(self):
        # Offset because tab array does not include first
        # tab but currentIndex does
        return self.ui.detectors.currentIndex() - 1

    def set_dark(self, index):
        self.dark_img = index
        idx = self.get_current_index()
        self.tabs[idx].percentile.setEnabled(index == 2)

    def load_image(self):
        f = self.parent.open_image_file()[0]
        self.dark_img = fabio.open(f).data
        idx = self.get_current_index()
        fileName = f.split('/')[-1]
        self.tabs[idx].upload_dark.setText(fileName)

    def set_data(self):
        if self.prev_tab == 'General':
            self.create_frame_list()
        else:
            self.create_oplists()
            self.create_dark()

    def create_frame_list(self):
        start = self.ui.offset.value()
        end = self.ui.max_total.value()
        self.frame_list = range(start, end)

        # Make sure all the detectors are updated even
        # if there are no operations performed on them
        if self.oplists == {}:
            for name in self.names:
                self.oplists[name] = []

    def create_oplists(self):
        name = self.prev_tab
        for tab in self.tabs:
            for child in tab.children():
                if isinstance(child, QRadioButton) and child.isChecked():
                    num = [int(w)
                            for w in child.objectName().split('_')
                            if w.isdigit()]
                    if num:
                        key = 'r' + str(num[0])
                    else:
                        key = child.objectName()[0]
                    self.oplists[name] = [['flip', key]]

    def create_dark(self):
        if not self.dark_img:
            return

        name = self.prev_tab
        if isinstance(self.dark_img, int):
            frames = len(self.frame_list)
            if self.dark_img == 1:
                dark = imageseries.stats.median(self.ims[name], frames)
            elif self.dark_img == 2:
                idx = self.get_current_index()
                dark = imageseries.stats.percentile(
                  self.ims[name], self.tabs[idx].percentile.value(), frames)
            elif self.dark_img == 3:
                dark = imageseries.stats.max(self.ims[name], frames)
            else:
                dark = imageseries.stats.average(self.ims[name], frames)
        else:
            dark = self.dark_img

        if name in self.oplists.keys():
            self.oplists[name].insert(0, ['dark', dark])
        else:
            self.oplists[name] = [['dark', dark]]

        self.dark_img = None

    def reset_values(self):
        max_ = self.ui.max_total.value() - self.ui.offset.value()
        if max_ > 0:
            self.set_defaults(max_)
        else:
            self.set_defaults()

        for tab in self.tabs:
            for child in tab.children():
                if isinstance(child, QRadioButton) and child.isChecked():
                    child.setAutoExclusive(False)
                    child.setChecked(False)
                    child.setAutoExclusive(True)
                tab.upload_dark.setText('Upload Image')
                tab.dark_combo.setCurrentIndex(0)
                tab.percentile.setValue(0)

    def apply_to_all(self):
        self.set_prev_tab()
        self.set_data()

        for name in self.names:
            self.oplists[name] = self.oplists[self.prev_tab]

        self.apply_ops()

    def apply_to_one(self):
        self.set_prev_tab()
        self.set_data()
        self.apply_ops()

    def apply_ops(self):
        self.reset_values()

        for key in self.oplists.keys():
            self.ims[key] = imageseries.process.ProcessedImageSeries(
                self.ims[key], self.oplists[key], frame_list=self.frame_list)

        self.parent.ui.image_tab_widget.load_images()
        self.parent.ui.image_tab_widget.update_ims_toolbar()
        self.oplists = {}

    def cancel(self):
        for name in self.names:
            self.ims[name] = self.original_ims[name]
        self.parent.ui.image_tab_widget.load_images()
        self.parent.ui.image_tab_widget.update_ims_toolbar()
