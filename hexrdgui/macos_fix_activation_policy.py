"""Register as a regular GUI app before QApplication is created.

Without a .app bundle, macOS does not recognize the process as a GUI
application, which causes TSM (Text Services Manager) errors when Qt
tries to connect to the window server for text input.
"""


def macos_fix_activation_policy() -> None:
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyRegular
    except ImportError:
        return

    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyRegular
    )
