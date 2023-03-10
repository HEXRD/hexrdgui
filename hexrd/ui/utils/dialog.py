from PySide2.QtGui import QDesktopServices
from PySide2.QtWidgets import QDialogButtonBox


def open_url(url):
    # Open the specified URL in a web browser
    return QDesktopServices.openUrl(url)


def add_help_url(button_box, url):
    # This connects "helpRequested" from the button box with opening a URL.
    # If the button box doesn't have a "Help" button, one will be added
    # automatically.
    if button_box.button(QDialogButtonBox.Help) is None:
        # If it doesn't have a help button, then add one
        button_box.addButton(QDialogButtonBox.Help)

    button_box.helpRequested.connect(lambda: open_url(url))
