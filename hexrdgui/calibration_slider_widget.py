from PySide6.QtCore import QObject

import numpy as np

from hexrd.rotations import angleAxisOfRotMat, rotMatOfExpMap

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, convert_angle_convention


class CalibrationSliderWidget(QObject):

    # Conversions from configuration value to slider value and back
    CONF_VAL_TO_SLIDER_VAL = 10
    SLIDER_VAL_TO_CONF_VAL = 0.1

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_slider_widget.ui', parent)

        self.update_gui_from_config()

        self.setup_connections()

    def setup_connections(self):
        self.ui.detector.currentIndexChanged.connect(
            self.update_gui_from_config)
        for widget in self.config_widgets:
            widget.valueChanged.connect(self.update_widget_counterpart)
            widget.valueChanged.connect(self.update_config_from_gui)

        self.ui.sb_translation_range.valueChanged.connect(self.update_ranges)
        self.ui.sb_tilt_range.valueChanged.connect(self.update_ranges)
        self.ui.sb_beam_range.valueChanged.connect(self.update_ranges)

        self.ui.push_reset_config.pressed.connect(self.reset_config)

        self.ui.roi_lock_group_transforms.toggled.connect(
            HexrdConfig().set_roi_lock_group_transforms)

        HexrdConfig().euler_angle_convention_changed.connect(
            self.update_labels)

    def update_ranges(self):
        r = self.ui.sb_translation_range.value()
        slider_r = r * self.CONF_VAL_TO_SLIDER_VAL
        for w in self.translation_widgets:
            v = w.value()
            r_val = slider_r if w.objectName().startswith('slider') else r
            w.setRange(v - r_val / 2.0, v + r_val / 2.0)

        r = self.ui.sb_tilt_range.value()
        slider_r = r * self.CONF_VAL_TO_SLIDER_VAL
        for w in self.tilt_widgets:
            v = w.value()
            r_val = slider_r if w.objectName().startswith('slider') else r
            w.setRange(v - r_val / 2.0, v + r_val / 2.0)

        r = self.ui.sb_beam_range.value()
        slider_r = r * self.CONF_VAL_TO_SLIDER_VAL
        for w in self.beam_widgets:
            v = w.value()
            r_val = slider_r if w.objectName().startswith('slider') else r
            w.setRange(v - r_val / 2.0, v + r_val / 2.0)

    def current_detector(self):
        return self.ui.detector.currentText()

    def current_detector_dict(self):
        return HexrdConfig().detector(self.current_detector())

    @property
    def translation_widgets(self):
        # Let's take advantage of the naming scheme
        prefixes = ['sb', 'slider']
        root = 'translation'
        suffixes = ['0', '1', '2']
        widget_names = [
            '_'.join([p, root, s])
            for p in prefixes
            for s in suffixes
        ]

        return [getattr(self.ui, x) for x in widget_names]

    @property
    def tilt_widgets(self):
        # Let's take advantage of the naming scheme
        prefixes = ['sb', 'slider']
        root = 'tilt'
        suffixes = ['0', '1', '2']
        widget_names = [
            '_'.join([p, root, s])
            for p in prefixes
            for s in suffixes
        ]

        return [getattr(self.ui, x) for x in widget_names]

    @property
    def transform_widgets(self):
        return self.translation_widgets + self.tilt_widgets

    @property
    def beam_widgets(self):
        # Let's take advantage of the naming scheme
        prefixes = ['sb', 'slider']
        roots = ['energy', 'azimuth', 'polar']
        suffixes = ['0']
        widget_names = [
            '_'.join([p, r, s])
            for p in prefixes
            for r in roots
            for s in suffixes
        ]

        return [getattr(self.ui, x) for x in widget_names]

    @property
    def config_widgets(self):
        return self.transform_widgets + self.beam_widgets

    @property
    def all_widgets(self):
        return self.config_widgets + [self.ui.detector]

    def on_detector_changed(self):
        self.update_gui_from_config()

    def update_widget_counterpart(self):
        sender = self.sender()
        name = sender.objectName()
        value = sender.value()

        prefix, root, ind = name.split('_')

        if prefix == 'slider':
            value *= self.SLIDER_VAL_TO_CONF_VAL
        else:
            value *= self.CONF_VAL_TO_SLIDER_VAL

        counter = 'slider' if prefix == 'sb' else 'sb'

        counter_widget_name = '_'.join([counter, root, ind])
        counter_widget = getattr(self.ui, counter_widget_name)

        blocked = counter_widget.blockSignals(True)
        try:
            counter_widget.setValue(value)
        finally:
            counter_widget.blockSignals(blocked)

    def update_gui_from_config(self):
        self.update_detectors_from_config()

        with block_signals(*self.config_widgets):
            for widget in self.config_widgets:
                self.update_widget_value(widget)

        self.ui.roi_lock_group_transforms.setChecked(
            HexrdConfig().roi_lock_group_transforms)

        self.update_ranges()
        self.update_labels()
        self.update_visibility_states()

    def update_visibility_states(self):
        self.ui.roi_lock_group_transforms.setVisible(
            HexrdConfig().instrument_has_roi)

    def update_detectors_from_config(self):
        widget = self.ui.detector

        old_detector = self.current_detector()
        old_detectors = [widget.itemText(x) for x in range(widget.count())]
        detectors = HexrdConfig().detector_names

        if old_detectors == detectors:
            # The detectors didn't change. Nothing to update
            return

        blocked = widget.blockSignals(True)
        try:
            widget.clear()
            widget.addItems(detectors)
            if old_detector in detectors:
                # Switch to the old detector if possible
                widget.setCurrentText(old_detector)

        finally:
            widget.blockSignals(blocked)

    def update_config_from_gui(self, val):
        """This function only updates the sender value"""
        sender = self.sender()
        name = sender.objectName()

        # Take advantage of the widget naming scheme
        prefix, key, ind = name.split('_')
        ind = int(ind)

        if prefix == 'slider':
            val *= self.SLIDER_VAL_TO_CONF_VAL

        if key in ['tilt', 'translation']:
            det = self.current_detector_dict()
            rme = HexrdConfig().rotation_matrix_euler()
            if key == 'tilt' and rme is not None:
                # Convert to radians, and to the native python type before save
                val = np.radians(val).item()

            if HexrdConfig().roi_lock_group_transforms:
                self._transform_locked_group(det, key, ind, val)
            else:
                det['transform'][key]['value'][ind] = val

                # Since we modify the value directly instead of letting the
                # HexrdConfig() do it, let's also emit the signal it would
                # have emitted.
                HexrdConfig().detector_transforms_modified.emit(
                    [self.current_detector()]
                )
        else:
            iconfig = HexrdConfig().config['instrument']
            if key == 'energy':
                iconfig['beam'][key]['value'] = val
                HexrdConfig().beam_energy_modified.emit()
            elif key == 'polar':
                iconfig['beam']['vector']['polar_angle']['value'] = val
                HexrdConfig().beam_vector_changed.emit()
            else:
                iconfig['beam']['vector'][key]['value'] = val
                HexrdConfig().beam_vector_changed.emit()

    def _transform_locked_group(self, det, key, ind, val):
        group = det.get('group', {}).get('value')
        if not group:
            raise Exception(f'Detector does not have a group: {det}')

        group_dets = {}
        for name in HexrdConfig().detector_names:
            if HexrdConfig().detector_group(name) == group:
                group_dets[name] = HexrdConfig().detector(name)

        if key == 'translation':
            # Compute the diff
            previous = det['transform']['translation']['value'][ind]
            diff = val - previous

            # Translate all detectors in the same group by the same difference
            for detector in group_dets.values():
                detector['transform']['translation']['value'][ind] += diff
        else:
            # It is tilt. Compute the center of rotation first.
            detector_centers = np.array([x['transform']['translation']['value']
                                        for x in group_dets.values()])
            center_of_rotation = detector_centers.mean(axis=0)

            # Gather the old tilt and the new tilt to compute a difference.
            old_tilt = det['transform']['tilt']['value']
            new_tilt = old_tilt.copy()
            # Apply the changed value
            new_tilt[ind] = val

            # Convert them to rotation matrices and compute the diff
            old_rmat = _tilt_to_rmat(old_tilt)
            new_rmat = _tilt_to_rmat(new_tilt)

            # Compute the rmat used to convert from old to new
            rmat_diff = new_rmat @ old_rmat.T

            # Rotate each detector using the rmat_diff
            for det_key, detector in group_dets.items():
                transform = detector['transform']

                # Compute current rmat
                rmat = _tilt_to_rmat(transform['tilt']['value'])

                # Apply rmat diff
                new_rmat = rmat_diff @ rmat

                # Convert back to tilt (using our convention) and set it
                transform['tilt']['value'] = _rmat_to_tilt(new_rmat)

                # Compute change in translation
                translation = np.asarray(transform['translation']['value'])

                # Translate to center and apply rmat diff
                translation -= center_of_rotation
                translation = rmat_diff @ translation + center_of_rotation

                transform['translation']['value'] = translation.tolist()

        HexrdConfig().detector_transforms_modified.emit(list(group_dets))

        # Since we modified potentially all translations and tilts, we
        # must update the GUI too.
        with block_signals(*self.transform_widgets):
            for w in self.transform_widgets:
                self.update_widget_value(w)

    def update_widget_value(self, widget):
        name = widget.objectName()

        # Take advantage of the widget naming scheme
        prefix, key, ind = name.split('_')
        ind = int(ind)

        if key in ['tilt', 'translation']:
            det = self.current_detector_dict()
            val = det['transform'][key]['value'][ind]
        else:
            iconfig = HexrdConfig().config['instrument']
            if key == 'energy':
                val = iconfig['beam'][key]['value']
            elif key == 'polar':
                val = iconfig['beam']['vector']['polar_angle']['value']
            else:
                val = iconfig['beam']['vector'][key]['value']

        if key == 'tilt':
            if HexrdConfig().rotation_matrix_euler() is None:
                suffix = ''
            else:
                # Convert to degrees, and to the native python type
                val = np.degrees(val).item()
                suffix = '°'

            if prefix == 'sb':
                widget.setSuffix(suffix)

        if prefix == 'slider':
            val *= self.CONF_VAL_TO_SLIDER_VAL

        # Make sure the widget's range will accept the value
        if val < widget.minimum():
            widget.setMinimum(val)
        elif val > widget.maximum():
            widget.setMaximum(val)

        widget.setValue(val)

    def reset_config(self):
        HexrdConfig().restore_instrument_config_backup()
        self.update_gui_from_config()

    def update_labels(self):
        # Make sure tilt labels reflect current euler convention
        if HexrdConfig().euler_angle_convention is None:
            a, b, c = 'xyz'
        else:
            a, b, c = HexrdConfig().euler_angle_convention['axes_order']
        self.ui.label_tilt_2.setText(str.upper(a + ':'))
        self.ui.label_tilt_0.setText(str.upper(b + ':'))
        self.ui.label_tilt_1.setText(str.upper(c + ':'))


def _tilt_to_rmat(tilt):
    # Convert the tilt to exponential map parameters, and then
    # to the rotation matrix, and return.
    convention = HexrdConfig().euler_angle_convention
    return rotMatOfExpMap(np.asarray(
        convert_angle_convention(tilt, convention, None)
    ))


def _rmat_to_tilt(rmat):
    # Convert the rotation matrix to exponential map parameters,
    # and then to the tilt, and return.
    convention = HexrdConfig().euler_angle_convention

    # Compute tilt
    phi, n = angleAxisOfRotMat(rmat)
    tilt = phi * n.flatten()

    # Convert back to convention
    return convert_angle_convention(tilt, None, convention)
