from hexrd.xrdutil.phutil import (
    polar_tth_corr_map_rygg_pinhole, JHEPinholeDistortion,
    RyggPinholeDistortion, SampleLayerDistortion, tth_corr_map_pinhole,
    tth_corr_map_rygg_pinhole, tth_corr_map_sample_layer,
)


class PolarDistortionObject:
    """This is an object used for applying distortion to the polar view

    The PowderOverlay class inherits from this.
    """
    def __init__(self, pinhole_distortion_type, pinhole_distortion_kwargs,
                 name='[Custom]'):
        self.pinhole_distortion_type = pinhole_distortion_type
        self.pinhole_distortion_kwargs = pinhole_distortion_kwargs
        self.name = name

    @property
    def has_pinhole_distortion(self):
        return self.pinhole_distortion_type is not None

    @property
    def has_polar_pinhole_displacement_field(self):
        """
        Whether or not we can directly generate the polar tth displacement
        field by calling the `create_polar_tth_displacement_field()` function.

        If we can't, then we must perform self.tth_displacement_field first,
        and then warp the images to the polar view.
        """
        rets = {
            None: False,
            'JHEPinholeDistortion': False,
            'RyggPinholeDistortion': True,
            'SampleLayerDistortion': False,
        }

        if self.pinhole_distortion_type not in rets:
            raise NotImplementedError(self.pinhole_distortion_type)

        return rets[self.pinhole_distortion_type]

    def pinhole_displacement_field(self, instr):
        """
        This returns a dictionary of panel names where the values
        are the displacement fields for the panels.
        The displacement field will be the same size as the panel in pixels.
        This can be taken and warped into the polar view.
        Or, if there is a polar_tth_displacement_field available for this
        distortion type, that can be used to directly generate the polar
        tth displacement field.
        """
        funcs = {
            'JHEPinholeDistortion': tth_corr_map_pinhole,
            'RyggPinholeDistortion': tth_corr_map_rygg_pinhole,
            'SampleLayerDistortion': tth_corr_map_sample_layer,
        }

        if self.pinhole_distortion_type not in funcs:
            raise NotImplementedError(self.pinhole_distortion_type)

        f = funcs[self.pinhole_distortion_type]

        kwargs = {
            **self.pinhole_distortion_kwargs,
            'instrument': instr,
        }

        return f(**kwargs)

    def create_polar_pinhole_displacement_field(self, instr, tth, eta):
        """Directly create the polar tth displacement field.

        If we are trying to create a polar tth displacement field, this
        is more direct and more efficient than first obtaining the
        `self.tth_displacement_field` and then warping it to the polar view.

        For the Rygg pinhole distortion, this is significantly more efficient.
        """
        if self.pinhole_distortion_type == 'RyggPinholeDistortion':
            kwargs = {
                **self.pinhole_distortion_kwargs,
                'instrument': instr,
            }
            return polar_tth_corr_map_rygg_pinhole(tth, eta, **kwargs)

        raise NotImplementedError(self.pinhole_distortion_type)

    def pinhole_distortion_dict(self, instr):
        if not self.has_tth_distortion or instr is None:
            return None

        def tth_jhe_pinhole_distortion(panel):
            kwargs = {
                **self.pinhole_distortion_kwargs,
                'panel': panel,
            }
            return JHEPinholeDistortion(**kwargs)

        def tth_rygg_pinhole_distortion(panel):
            kwargs = {
                **self.pinhole_distortion_kwargs,
                'panel': panel,
            }
            return RyggPinholeDistortion(**kwargs)

        def tth_sample_layer_distortion(panel):
            kwargs = {
                **self.pinhole_distortion_kwargs,
                'panel': panel,
            }
            return SampleLayerDistortion(**kwargs)

        known_types = {
            'JHEPinholeDistortion': tth_jhe_pinhole_distortion,
            'RyggPinholeDistortion': tth_rygg_pinhole_distortion,
            'SampleLayerDistortion': tth_sample_layer_distortion,
        }

        if self.pinhole_distortion_type not in known_types:
            msg = f'Unhandled distortion type: {self.pinhole_distortion_type}'
            raise Exception(msg)

        f = known_types[self.pinhole_distortion_type]

        ret = {}
        for det_key, panel in instr.detectors.items():
            ret[det_key] = f(panel)

        return ret

    @property
    def _attrs_to_serialize(self):
        return [
            'pinhole_distortion_type',
            'pinhole_distortion_kwargs',
            'name',
        ]

    def serialize(self):
        return {k: getattr(self, k) for k in self._attrs_to_serialize}

    @classmethod
    def deserialize(cls, d):
        if d.get('pinhole_distortion_type') == 'SampleLayerDistortion':
            # We added pinhole_radius later. Set a default if it is missing.
            if 'pinhole_radius' not in d['pinhole_distortion_kwargs']:
                # Set to 0.15 mm for default
                d['pinhole_distortion_kwargs']['pinhole_radius'] = 0.15

        return cls(**d)
