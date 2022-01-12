from PySide2.QtCore import Qt

from hexrd.ui.ui_loader import UiLoader


class MessageBox:
    def __init__(self, title, message, details='', parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('message_box.ui', parent)

        # Store this and use it for all detail text that is added
        self.details_alignment = self.ui.details.alignment()

        self.title = title
        self.message = message
        self.details = details

    def exec_(self):
        return self.ui.exec_()

    def show(self):
        return self.ui.show()

    @property
    def title(self):
        return self.ui.windowTitle()

    @title.setter
    def title(self, text):
        self.ui.setWindowTitle(text)

    @property
    def message(self):
        return self.ui.message.text()

    @message.setter
    def message(self, text):
        self.ui.message.setText(text)

    @property
    def details(self):
        return self.ui.details.toPlainText()

    @details.setter
    def details(self, text):
        self.ui.details.clear()
        self.ui.details.setAlignment(self.details_alignment)
        # Append the text so any formatting will stick
        for line in text.split('\n'):
            self.ui.details.append(line)
        self.ui.details.setVisible(bool(text))

    def align_details_hcenter(self):
        self.details_alignment = Qt.AlignHCenter
        # Reset details
        self.details = self.details


if __name__ == '__main__':
    import sys

    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    details = (
        '*** ruby rotation_series ***\n'
        '  1.21460907  =>   1.21499511\n'
        '  0.69398091  =>   0.69136234\n'
        '  0.76576534  =>   0.76291590\n'
        '*** ruby rotation_series 2 ***\n'
        '  1.41041435  =>   1.41032761\n'
        ' -0.14317809  =>  -0.14322503\n'
        ' -0.37254900  =>  -0.37260657\n'
        '*** ruby rotation_series 3 ***\n'
        '  0.34399581  =>   0.34379406\n'
        '  0.81699894  =>   0.81737957\n'
        ' -0.01688981  =>  -0.01693500'
    )

    kwargs = {
        'title': 'HEXRD',
        'message': 'Optimization successful!',
        'details': details,
    }
    dialog = MessageBox(**kwargs)
    dialog.align_details_hcenter()
    dialog.ui.show()
    app.exec_()
