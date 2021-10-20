import copy

import numpy as np

from hexrd.ui.constants import DEFAULT_CRYSTAL_PARAMS, OverlayType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.tree_views.multi_column_dict_tree_view import (
    MultiColumnDictTreeView)
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import convert_angle_convention


class RefinementsEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('refinements_editor.ui', parent)

        self.dict = {}
        self.reset_dict()

        columns = {
            'Value': '_value',
            'Refinable': '_refinable',
        }
        self.tree_view = MultiColumnDictTreeView(self.dict, columns, parent)
        self.ui.tree_view_layout.addWidget(self.tree_view)

        self.iconfig_values_modified = False
        self.material_values_modified = False

        self.setup_actions()
        self.setup_connections()

    def setup_connections(self):
        self.ui.apply_action.pressed.connect(self.apply_action)
        self.ui.reset.pressed.connect(self.reset_dict)

        self.ui.button_box.accepted.connect(self.update_config)
        self.ui.button_box.accepted.connect(self.ui.accept)
        self.ui.button_box.rejected.connect(self.ui.reject)

    def reset_dict(self):
        config = {}
        config['instrument'] = self.create_instrument_dict()
        config['materials'] = self.create_materials_dict()

        self.dict.clear()
        self.dict.update(config)

        self.update_tree_view()

    def update_tree_view(self):
        if not hasattr(self, 'tree_view'):
            return

        sb = self.tree_view.verticalScrollBar()
        prev_pos = sb.value()
        self.tree_view.reset_gui()
        sb.setValue(prev_pos)

    def create_instrument_dict(self):
        iconfig = HexrdConfig().config['instrument']

        # Recurse through it, setting all status keys and renaming them to
        # "_refinable".
        blacklisted = ['saturation_level', 'buffer', 'pixels', 'id']

        def recurse(cur, idict):
            if 'status' in cur:
                if isinstance(cur['status'], list):
                    for i, b in enumerate(cur['status']):
                        idict[i] = {}
                        idict[i]['_value'] = cur['value'][i]
                        idict[i]['_refinable'] = bool(b)
                else:
                    idict['_value'] = cur['value']
                    idict['_refinable'] = bool(cur['status'])
                return

            for key, v in cur.items():
                if key in blacklisted:
                    continue

                if (key == 'tilt' and
                        HexrdConfig().rotation_matrix_euler() is not None):
                    # Display tilts as degrees
                    v = copy.deepcopy(v)
                    v['value'] = [np.degrees(x).item() for x in v['value']]

                idict[key] = {}
                recurse(v, idict[key])

        idict = {}
        recurse(iconfig, idict)
        return idict

    def create_materials_dict(self):
        mdict = {}
        for overlay in self.overlays:
            name = unique_overlay_name(overlay)
            values = refinement_values(overlay)
            mdict[name] = {}
            for rname, b in overlay['refinements']:
                mdict[name][rname] = {}
                mdict[name][rname]['_refinable'] = b
                mdict[name][rname]['_value'] = values[rname]

        return mdict

    def update_config(self):
        self.update_instrument_config()
        self.update_materials_config()

    def update_instrument_config(self):
        iconfig = HexrdConfig().config['instrument']
        idict = self.dict['instrument']

        def recurse(cur, idict):
            if 'status' in cur:
                if isinstance(cur['status'], list):
                    for i in range(len(cur['status'])):
                        cur['status'][i] = int(idict[i]['_refinable'])
                        if not are_close(cur['value'][i], idict[i]['_value']):
                            self.iconfig_values_modified = True
                            cur['value'][i] = idict[i]['_value']
                else:
                    cur['status'] = int(idict['_refinable'])
                    if not are_close(cur['value'], idict['_value']):
                        self.iconfig_values_modified = True
                        cur['value'] = idict['_value']
                return

            for key, v in idict.items():
                if key not in cur:
                    continue

                if (key == 'tilt' and
                        HexrdConfig().rotation_matrix_euler() is not None):
                    # Store tilts as radians
                    v = copy.deepcopy(v)
                    for i in range(len(v)):
                        v[i]['_value'] = np.radians(v[i]['_value']).item()

                recurse(cur[key], v)

        recurse(iconfig, idict)

    def update_materials_config(self):
        mdict = self.dict['materials']
        for overlay in self.overlays:
            name = unique_overlay_name(overlay)
            values = []
            for i, ref in enumerate(overlay['refinements']):
                new = (ref[0], mdict[name][ref[0]]['_refinable'])
                overlay['refinements'][i] = new
                values.append(mdict[name][ref[0]]['_value'])
            any_modified = set_refinement_values(overlay, values)
            if any_modified:
                self.material_values_modified = True

    @property
    def overlays(self):
        return HexrdConfig().overlays

    def setup_actions(self):
        labels = list(self.actions.keys())
        self.ui.action.clear()
        self.ui.action.addItems(labels)

    def apply_action(self):
        action = self.ui.action.currentText()
        func = self.actions[action]
        func()

        # Update the tree view
        self.update_tree_view()

    @property
    def actions(self):
        return {
            'Clear refinements': self.clear_refinements,
            'Mirror first detector': self.mirror_first_detector,
        }

    # Refinement actions
    def clear_refinements(self):
        def recurse(x):
            if '_refinable' in x:
                x['_refinable'] = False

            for key in x:
                if isinstance(x[key], dict):
                    recurse(x[key])

        recurse(self.dict)

    def mirror_first_detector(self):
        detectors = self.dict['instrument']['detectors']
        first = next(iter(detectors.values()))

        def set_refinements(det):
            def recurse(cur1, cur2):
                if '_refinable' in cur1:
                    cur2['_refinable'] = cur1['_refinable']

                for key in cur1:
                    if isinstance(cur1[key], dict):
                        recurse(cur1[key], cur2[key])

            recurse(first, det)

        for key, det in detectors.items():
            if det is first:
                continue

            set_refinements(det)


def unique_overlay_name(overlay):
    mat_name = overlay['material']
    all_overlays = HexrdConfig().overlays
    same_material = [x for x in all_overlays if x['material'] == mat_name]

    if len(same_material) == 1:
        return mat_name

    for i, o in enumerate(same_material, 1):
        if o is overlay:
            return f'{mat_name}_{i}'


def refinement_values(overlay):
    ret = {}
    refinements = overlay['refinements']

    def powder_values():
        material = HexrdConfig().material(overlay['material'])
        reduced_lparms = material.reduced_lattice_parameters

        # These params should be in the same order as the refinements
        for i, (rname, _) in enumerate(refinements):
            x = reduced_lparms[i]
            units = 'angstrom' if x.isLength() else 'degrees'
            ret[rname] = to_native(x.getVal(units))

        return ret

    def laue_values():
        options = overlay.setdefault('options', {})
        params = options.get('crystal_params', DEFAULT_CRYSTAL_PARAMS.copy())
        # These params should be in the same order as the refinements
        params = np.array(params)
        params[:3] = to_convention(params[:3])
        for i, (rname, _) in enumerate(refinements):
            ret[rname] = to_native(params[i])

        return ret

    func_dict = {
        OverlayType.powder: powder_values,
        OverlayType.laue: laue_values,
    }

    return func_dict[overlay['type']]()


def set_refinement_values(overlay, values):
    def set_powder():
        material = HexrdConfig().material(overlay['material'])
        prev_lparms = material.lparms
        material.latticeParameters = values
        lparms = material.lparms

        # Indicate whether the data was modified
        return any(not are_close(x, y) for x, y in zip(prev_lparms, lparms))

    def set_laue():
        nonlocal values
        options = overlay.setdefault('options', {})
        params = options.get('crystal_params', DEFAULT_CRYSTAL_PARAMS.copy())
        values = np.array(values)
        values[:3] = from_convention(values[:3])
        if any(not are_close(x, y) for x, y in zip(params, values)):
            options['crystal_params'] = values
            return True

        return False

    func_dict = {
        OverlayType.powder: set_powder,
        OverlayType.laue: set_laue,
    }

    return func_dict[overlay['type']]()


def to_native(x):
    if isinstance(x, np.generic):
        return x.item()

    return x


def are_close(v1, v2, tol=1.e-8):
    if isinstance(v1, (float, np.floating)):
        return abs(v1 - v2) < tol

    return v1 == v2


def from_convention(v):
    convention = HexrdConfig().euler_angle_convention
    if convention is not None:
        v = np.radians(v)
        v = convert_angle_convention(v, convention, None)

    return v


def to_convention(v):
    convention = HexrdConfig().euler_angle_convention
    if convention is not None:
        v = convert_angle_convention(v, None, convention)
        v = np.degrees(v)

    return v
