import sys


def macos_fix_app_name() -> None:
    # This fixes the bundle name to be "HEXRD"
    # Otherwise, it is displayed as "Python" in the top-left corner
    # of the OSX menu bar.
    # pyobjc-framework-Cocoa is required for this to work.
    if not sys.platform.startswith('darwin'):
        return

    try:
        from Foundation import NSBundle
    except ImportError:
        return

    bundle = NSBundle.mainBundle()
    if not bundle:
        return

    app_info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    if app_info is None:
        return

    app_info['CFBundleName'] = 'HEXRD'
