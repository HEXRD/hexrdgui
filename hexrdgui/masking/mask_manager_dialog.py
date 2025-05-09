import math
import os
import numpy as np
import h5py
from itertools import groupby
from operator import attrgetter
import re

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QMenu,
    QMessageBox, QPushButton, QTreeWidgetItem, QVBoxLayout, QColorDialog
)
from PySide6.QtGui import QCursor, QColor, QFont

from hexrdgui.constants import ViewType
from hexrdgui.utils import block_signals
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType, MaskStatus
from hexrdgui.masking.mask_border_style_picker import MaskBorderStylePicker
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url

import matplotlib.pyplot as plt


class MaskManagerDialog(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        loader = UiLoader()
        self.ui = loader.load_file('mask_manager_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.changed_masks = {}
        self.mask_tree_items = {}

        add_help_url(self.ui.button_box,
                     'configuration/masking/#managing-masks')

        self.create_tree()
        self.setup_connections()

    def show(self):
        self.create_tree()
        self.ui.show()

    def setup_connections(self):
        self.ui.masks_tree.itemChanged.connect(self.update_mask_name)
        self.ui.masks_tree.customContextMenuRequested.connect(
            self.context_menu_event)
        self.ui.export_masks.clicked.connect(MaskManager().write_masks)
        self.ui.import_masks.clicked.connect(self.import_masks)
        self.ui.panel_buffer.clicked.connect(self.masks_to_panel_buffer)
        self.ui.view_masks.clicked.connect(self.show_masks)
        self.ui.hide_all_masks.clicked.connect(self.hide_all_masks)
        self.ui.show_all_masks.clicked.connect(self.show_all_masks)
        MaskManager().mask_mgr_dialog_update.connect(self.update_tree)
        self.ui.hide_all_boundaries.clicked.connect(self.hide_all_boundaries)
        self.ui.show_all_boundaries.clicked.connect(self.show_all_boundaries)
        MaskManager().export_masks_to_file.connect(self.export_masks_to_file)
        self.ui.border_style.clicked.connect(self.edit_style)
        self.ui.apply_changes.clicked.connect(self.apply_changes)
        HexrdConfig().active_beam_switched.connect(self.update_collapsed)
        self.ui.masks_tree.itemSelectionChanged.connect(self.selected_changed)
        self.ui.presentation_selector.currentTextChanged.connect(self.change_presentation_for_selected)

    def create_mode_source_string(self, mode, source):
        if mode is None:
            return 'Global'
        mode_str = f'{mode.capitalize()} Mode'
        source_str = f' - {source}' if source else ''
        return f'{mode_str}{source_str}'

    def update_presentation_combo(self, item, mask):
        mask_type = MaskManager().masks[mask.name].type
        idx = MaskStatus.none
        if mask.name in MaskManager().visible_masks:
            idx = MaskStatus.visible
        if (mask_type == MaskType.region or
                mask_type == MaskType.polygon or
                mask_type == MaskType.pinhole):
            if mask.name in MaskManager().visible_boundaries:
                idx += MaskStatus.boundary
        self.ui.masks_tree.itemWidget(item, 1).setCurrentIndex(idx)

    def create_mode_item(self, mode, source):
        text = self.create_mode_source_string(mode, source)
        mode_item = QTreeWidgetItem([text])
        mode_item.setFlags(Qt.ItemIsEnabled)
        mode_item.setFont(0, QFont(
            mode_item.font(0).family(),
            mode_item.font(0).pointSize(),
            QFont.Bold
        ))
        self.ui.masks_tree.addTopLevelItem(mode_item)
        self.mask_tree_items[mode_item.text(0)] = mode_item
        self.ui.masks_tree.expandItem(mode_item)
        return mode_item

    def create_mask_item(self, parent_item, mask):
        mask_item = QTreeWidgetItem([mask.name])
        mask_item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        # Store the original mask name in the item's data
        mask_item.setData(0, Qt.UserRole, mask.name)
        parent_item.addChild(mask_item)
        self.mask_tree_items[mask.name] = mask_item

        # Add combo box to select mask presentation
        presentation_combo = QComboBox()
        presentation_combo.addItem('None')
        presentation_combo.addItem('Visible')
        mask_type = MaskManager().masks[mask.name].type
        if (mask_type == MaskType.region or
                mask_type == MaskType.polygon or
                mask_type == MaskType.pinhole):
            presentation_combo.addItem('Boundary Only')
            presentation_combo.addItem('Visible + Boundary')
        self.ui.masks_tree.setItemWidget(mask_item, 1, presentation_combo)
        self.update_presentation_combo(mask_item, mask)
        presentation_combo.currentIndexChanged.connect(
            lambda i, k=mask: self.track_mask_presentation_change(i, k))

        # Add push button to remove mask
        pb = QPushButton('Remove Mask')
        self.ui.masks_tree.setItemWidget(mask_item, 2, pb)
        pb.clicked.connect(
            lambda checked, k=mask.name: self.remove_mask_item(k))

    def update_mask_item(self, mask):
        item = self.mask_tree_items[mask.name]
        item.setText(0, mask.name)
        self.update_presentation_combo(item, mask)

    def remove_mask_item(self, name):
        if name not in MaskManager().mask_names:
            # Make sure it is a mask and not a mode item
            return

        scrollbar = self.ui.masks_tree.verticalScrollBar()
        scroll_value = scrollbar.value()
        item = self.mask_tree_items.pop(name)
        parent = item.parent()
        parent.removeChild(item)
        MaskManager().remove_mask(name)
        # If parent has no more children, remove it too
        if parent.childCount() == 0:
            self.ui.masks_tree.takeTopLevelItem(
                self.ui.masks_tree.indexOfTopLevelItem(parent))
            self.mask_tree_items.pop(parent.text(0))
        MaskManager().masks_changed()
        self.ui.masks_tree.verticalScrollBar().setValue(scroll_value)


    def _alphanumeric_sort(self, value):
        # Split the string into text and number parts so that we
        # sort by string value lexicographically and the number
        # value numerically
        vals = re.split('([0-9]+)', value)
        return [int(v) if v.isdigit() else v.lower() for v in vals]

    def update_tree(self):
        if self.ui.masks_tree.topLevelItemCount() == 0:
            self.create_tree()
            return

        with block_signals(self.ui.masks_tree):
            # Remove items for deleted masks
            current_masks = set(MaskManager().masks.keys())
            existing_items = set(self.mask_tree_items.keys())
            removed_masks = existing_items - current_masks
            for name in removed_masks:
                self.remove_mask_item(name)

            # Add new items and update existing ones
            for mask in MaskManager().masks.values():
                mode, source = [mask.creation_view_mode, mask.xray_source]
                if mask.name not in self.mask_tree_items:
                    # Create new mask item
                    parent = self.create_mode_source_string(mode, source)
                    if parent not in self.mask_tree_items:
                        self.create_mode_item(mode, source)
                    self.create_mask_item(self.mask_tree_items[parent], mask)
                else:
                    # Update existing mask item
                    self.update_mask_item(mask)

    def create_tree(self):
        with block_signals(self.ui.masks_tree):
            self.ui.masks_tree.clear()
            # Sort masks by creation view mode and xray source
            sorted_masks = sorted(
                MaskManager().masks.values(),
                key=lambda mask: (
                    mask.creation_view_mode or '',
                    mask.xray_source or ''
                )
            )

            # Group masks by creation view mode and xray source
            grouped = groupby(
                sorted_masks,
                key=attrgetter('creation_view_mode', 'xray_source')
            )
            for (mode, source), masks in grouped:
                # Create mode item
                mode_item = self.create_mode_item(mode, source)

                # Create items for each mask, sorted naturally by name
                for mask in sorted(masks,
                                   key=lambda x: self._alphanumeric_sort(x.name)):
                    self.create_mask_item(mode_item, mask)

        self.ui.masks_tree.expandAll()
        self.ui.masks_tree.resizeColumnToContents(0)
        self.ui.masks_tree.resizeColumnToContents(1)

    def track_mask_presentation_change(self, index, mask):
        self.changed_masks[mask.name] = index
        if not self.ui.apply_changes.isEnabled():
            self.ui.apply_changes.setEnabled(True)

    def change_mask_presentation(self, index, name):
        match index:
            case MaskStatus.visible:
                MaskManager().update_mask_visibility(name, True)
                MaskManager().update_border_visibility(name, False)
            case MaskStatus.boundary:
                MaskManager().update_mask_visibility(name, False)
                MaskManager().update_border_visibility(name, True)
            case MaskStatus.all:
                MaskManager().update_mask_visibility(name, True)
                MaskManager().update_border_visibility(name, True)
            case _:
                MaskManager().update_mask_visibility(name, False)
                MaskManager().update_border_visibility(name, False)
        MaskManager().masks_changed()

    def update_mask_name(self, item, column):
        if column != 0:
            # Only handle name changes (column 0)
            return

        if item.parent() is None:
            # This is a mode item, don't allow editing
            return

        new_name = item.text(0)
        # Get the old name from the mask item's data
        old_name = item.data(0, Qt.UserRole)
        if old_name != new_name:
            if not new_name or new_name in MaskManager().mask_names:
                # Prevent empty or duplicate mask names
                item.setText(0, old_name)
                return
            # Store the new name before updating the manager
            item.setData(0, Qt.UserRole, new_name)
            MaskManager().update_name(old_name, new_name)
            # Update our tracking dictionaries
            if old_name in self.changed_masks:
                self.changed_masks[new_name] = self.changed_masks.pop(old_name)
            self.mask_tree_items[new_name] = self.mask_tree_items.pop(old_name)

    def update_collapsed(self):
        mode = MaskManager().view_mode
        if not HexrdConfig().has_multi_xrs:
            return

        if mode != ViewType.polar:
            return

        for beam_name in HexrdConfig().beam_names:
            parent = self.create_mode_source_string(mode, beam_name)
            item = self.mask_tree_items.get(parent, None)
            if item is None:
                continue
            if beam_name == HexrdConfig().active_beam_name:
                self.ui.masks_tree.expandItem(item)
            else:
                self.ui.masks_tree.collapseItem(item)

    def context_menu_event(self, event):
        item = self.ui.masks_tree.itemAt(event)
        if item and item.parent():  # Only for mask items, not mode items
            menu = QMenu(self.ui.masks_tree)
            export = menu.addAction('Export Selected Masks')
            action = menu.exec(QCursor.pos())
            if action == export:
                selections = self.ui.masks_tree.selectedItems()
                MaskManager().write_masks([i.text(0) for i in selections])

    def export_masks_to_file(self, data):
        output_file, _ = QFileDialog.getSaveFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not output_file:
            return

        HexrdConfig().working_dir = os.path.dirname(output_file)
        # write to hdf5
        with h5py.File(output_file, 'w') as f:
            h5py_group = f.create_group('masks')
            MaskManager().write_masks_to_group(data, h5py_group)

    def import_masks(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Import Masks', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            return

        HexrdConfig().working_dir = os.path.dirname(selected_file)

        with h5py.File(selected_file, 'r') as f:
            MaskManager().load_masks(f['masks'])

    def masks_to_panel_buffer(self):
        show_dialog = False
        selection = 'Replace buffer'
        for det in HexrdConfig().detectors.values():
            buff_val = det.get('buffer', None)
            if isinstance(buff_val, np.ndarray) and buff_val.ndim == 2:
                show_dialog = True
                break

        if show_dialog:
            dialog = QDialog(self.ui)
            layout = QVBoxLayout()
            dialog.setLayout(layout)

            options = QComboBox(dialog)
            options.addItem('Replace buffer')
            options.addItem('Union of panel buffer and current masks')
            options.addItem('Intersection of panel buffer and current masks')
            layout.addWidget(options)

            buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            button_box = QDialogButtonBox(buttons, dialog)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)

            if not dialog.exec():
                # canceled
                return

            selection = options.currentText()

        MaskManager().masks_to_panel_buffer(selection)
        msg = 'Masks set as panel buffers.'
        QMessageBox.information(self.parent, 'HEXRD', msg)

    def show_masks(self):
        num_dets = len(HexrdConfig().detector_names)
        cols = 2 if num_dets > 1 else 1
        rows = math.ceil(num_dets / cols)

        fig = plt.figure()
        fig.canvas.manager.set_window_title('User Created Masks')
        for i, det in enumerate(HexrdConfig().detector_names):
            axis = fig.add_subplot(rows, cols, i + 1)
            axis.set_title(det)
            axis.imshow(HexrdConfig().raw_masks_dict[det])
        fig.canvas.draw_idle()
        fig.show()

    def update_presentation_selector(self):
        with block_signals(self.ui.masks_tree):
            for i in range(self.ui.masks_tree.topLevelItemCount()):
                mode_item = self.ui.masks_tree.topLevelItem(i)
                for j in range(mode_item.childCount()):
                    mask_item = mode_item.child(j)
                    name = mask_item.text(0)
                    cb = self.ui.masks_tree.itemWidget(mask_item, 1)
                    idx = MaskStatus.none
                    if name in MaskManager().visible_masks:
                        idx += MaskStatus.visible
                    if name in MaskManager().visible_boundaries:
                        idx += MaskStatus.boundary
                    with block_signals(cb):
                        cb.setCurrentIndex(idx)

    def change_mask_visibility(self, mask_names, visible):
        for name in mask_names:
            MaskManager().update_mask_visibility(name, visible)
        self.update_presentation_selector()

    def hide_all_masks(self):
        self.change_mask_visibility(MaskManager().mask_names, False)
        MaskManager().masks_changed()

    def show_all_masks(self):
        self.change_mask_visibility(MaskManager().mask_names, True)
        MaskManager().masks_changed()

    def change_mask_boundaries(self, mask_names, visible):
        for name in mask_names:
            MaskManager().update_border_visibility(name, visible)
        self.update_presentation_selector()

    def hide_all_boundaries(self):
        self.change_mask_boundaries(MaskManager().mask_names, False)
        MaskManager().masks_changed()

    def show_all_boundaries(self):
        self.change_mask_boundaries(MaskManager().mask_names, True)
        MaskManager().masks_changed()

    def edit_style(self):
        dialog = MaskBorderStylePicker(
            MaskManager().boundary_color,
            MaskManager().boundary_style,
            MaskManager().boundary_width
        )
        if dialog.exec():
            color, style, width = dialog.result()
            MaskManager().boundary_color = color
            MaskManager().boundary_style = style
            MaskManager().boundary_width = width
            MaskManager().masks_changed()

    def apply_changes(self):
        for name, index in self.changed_masks.items():
            self.change_mask_presentation(index, name)
        self.changed_masks = {}
        self.ui.apply_changes.setEnabled(False)

    def selected_changed(self):
        selected = self.ui.masks_tree.selectedItems()
        self.ui.presentation_selector.setEnabled(len(selected) > 1)
        self.ui.export_selected.setEnabled(len(selected) > 1)

        if len(selected) == 0:
            return

        boundary_masks = [MaskType.region, MaskType.polygon, MaskType.pinhole]
        masks_from_names = [MaskManager().get_mask_by_name(i.text(0)) for i in selected]
        vis_only = any(mask.type not in boundary_masks for mask in masks_from_names)
        self.ui.presentation_selector.clear()
        self.ui.presentation_selector.addItem('None')
        self.ui.presentation_selector.addItem('Visible')
        if not vis_only:
            self.ui.presentation_selector.addItem('Boundary Only')
            self.ui.presentation_selector.addItem('Visible + Boundary')

    def change_presentation_for_selected(self, text):
        mask_names = [i.text(0) for i in self.ui.masks_tree.selectedItems()]
        if 'Boundary' in text:
            self.change_mask_boundaries(mask_names, True)
        else:
            self.change_mask_boundaries(mask_names, False)

        if 'Visible' in text:
            self.change_mask_visibility(mask_names, True)
        else:
            self.change_mask_visibility(mask_names, False)
        MaskManager().masks_changed()
