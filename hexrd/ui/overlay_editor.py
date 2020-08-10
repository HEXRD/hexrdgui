from hexrd.ui.laue_overlay_editor import LaueOverlayEditor
from hexrd.ui.ui_loader import UiLoader


class OverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('overlay_editor.ui', parent)

        self.laue_overlay_editor = LaueOverlayEditor(self.ui)

        self.ui.laue_overlay_editor_layout.addWidget(
            self.laue_overlay_editor.ui)

        self.ui.tab_widget.tabBar().hide()

        self.overlay = None

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.update_type_tab()

    @property
    def type(self):
        return self.overlay['type'] if self.overlay else None

    def update_type_tab(self):
        if self.type is None:
            w = getattr(self.ui, 'blank_tab')
        else:
            # Take advantage of the naming scheme...
            w = getattr(self.ui, self.type.value + '_tab')

        self.ui.tab_widget.setCurrentWidget(w)

        if self.active_widget is not None:
            self.active_widget.overlay = self.overlay

    @property
    def active_widget(self):
        widgets = {
            'powder': None,
            'laue': self.laue_overlay_editor,
            'mono_rotation_series': None
        }

        if self.type is None or self.type.value not in widgets:
            return None

        return widgets[self.type.value]
