from contextlib import contextmanager

from _pytest.monkeypatch import MonkeyPatch

from PySide6.QtWidgets import QFileDialog

monkeypatch = MonkeyPatch()


@contextmanager
def select_files_when_asked(filenames, filters=None):
    if not isinstance(filenames, (list, tuple)):
        filenames = [filenames]

    if not isinstance(filters, (list, tuple)):
        filters = [filters]

    # Make sure they are strings
    filenames = list(map(str, filenames))

    def get_file_name(*args, **kwargs):
        return filenames[0], filters[0]

    def get_file_names(*args, **kwargs):
        return filenames, filters

    def get_dir_name(*args, **kwargs):
        return filenames[0]

    # Patch everything we need to in order to catch all types of
    # file dialogs.
    patches = {
        'getOpenFileName': get_file_name,
        'getOpenFileNames': get_file_names,
        'getSaveFileName': get_file_name,
        'getExistingDirectory': get_dir_name,
    }

    originals = {name: getattr(QFileDialog, name) for name in patches}

    for name, func in patches.items():
        monkeypatch.setattr(QFileDialog, name, func)

    try:
        yield
    finally:
        for name, func in originals.items():
            monkeypatch.setattr(QFileDialog, name, func)
