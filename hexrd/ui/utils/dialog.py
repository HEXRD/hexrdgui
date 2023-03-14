from PySide2.QtGui import QDesktopServices
from PySide2.QtWidgets import QDialogButtonBox


def open_url(url):
    # Open the specified URL in a web browser
    if not url.startswith('http'):
        # Assume that this is a relative path for the HEXRDGUI docs
        url = f'https://hexrdgui.readthedocs.io/en/latest/{url}'

    return QDesktopServices.openUrl(url)


def add_help_url(button_box, url):
    # This connects "helpRequested" from the button box with opening a URL.
    # If the button box doesn't have a "Help" button, one will be added
    # automatically.
    if button_box.button(QDialogButtonBox.Help) is None:
        # If it doesn't have a help button, then add one
        button_box.addButton(QDialogButtonBox.Help)

    button_box.helpRequested.connect(lambda: open_url(url))
