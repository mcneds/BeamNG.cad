"""Optional static alignment through existing adjustable tie/toe-link lengths.

No chassis hardpoint, joint, spring or node position is moved. The native car
settles onto these unloaded rod lengths; the independent motion reference uses
the measured native lengths. Positive target angles mean toe-in on either side.
"""
import math
import numpy as np
from scipy.optimize import brentq


def solve(model):
    from vehicle_wizard.kinematics import Mechanism
    parameters=model.data['parameters']; result={}
    for corner in model.data['corners']:
        axle='front' if corner[0]=='F' else 'rear'
        key=axle+'_alignment_toe_in_deg'
        if key not in parameters:continue
        target=float(parameters[key])
        if not math.isfinite(target) or abs(target)>3:
            raise ValueError('Static toe alignment must be finite and within +/-3 degrees')
        mechanism=Mechanism(model,corner);p=mechanism.p
        if mechanism.translating_rack:
            raise ValueError('Automatic toe alignment for a translating rack requires individual adjustable tie-rod declarations')
        if not (mechanism.wishbone or mechanism.radius_toe or mechanism.ball_radius_toe):
            raise ValueError(corner+': static toe adjustment requires an independent tie/toe link')
        if axle=='rear' and parameters.get('rear_toe_link_length_scale',1.)!=1.:
            raise ValueError('Choose a rear toe target or a length scale, not both')
        length=float(np.linalg.norm(p['tie_outer']-p['tie_inner']))
        from suspension_loads import axle_reference_height
        default_height=(axle_reference_height(model,corner) if parameters.get('level_axle_ride_height',True)
                        else np.mean([model.corner_points(c)['hub'][2] for c in model.data['corners'] if c[0]==corner[0]]))
        height=float(parameters.get(axle+'_alignment_hub_height_m',default_height))
        if not math.isfinite(height):raise ValueError('Alignment hub height must be finite')
        signed_target=math.radians(target)*(-1 if corner[1]=='L' else 1)
        def angle(extension):
            _,pose=mechanism.solve(height-p['hub'][2],extension)
            axis=pose['hub_axis']-pose['hub'];axis*=1 if axis[0]>=0 else -1
            return math.atan2(axis[1],axis[0])
        def residual(extension):
            value=angle(extension)-signed_target
            return math.atan2(math.sin(value),math.cos(value))
        bound=.02*length
        try:extension=brentq(residual,-bound,bound,xtol=1e-12)
        except ValueError as error:
            raise ValueError(corner+': requested toe alignment is unreachable within 2% tie-link adjustment') from error
        result[corner]=dict(target_toe_in_deg=target,reference_hub_height_m=height,
                            original_toe_in_deg=math.degrees(angle(0))*(-1 if corner[1]=='L' else 1),
                            original_length_m=length,reference_length_m=length+extension,
                            length_scale=1+extension/length,
                            scope='Static unloaded tie-link length adjustment; original CAD hardpoints and coilover laws retained')
    return result
