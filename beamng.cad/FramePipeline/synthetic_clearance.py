"""Conservative fixture-only tube clearance against a swept wheel envelope.

This audits physical recipe geometry, not invisible JBeam constraints. Tubes are
bounded by solid capsules and wheels by an annular cylinder from rim to tread.
Sampling subtracts half a segment step: distance to a closed set is 1-Lipschitz,
so the returned lower bound also covers points between samples. A negative bound
means clearance is not established; it is not a precise penetration depth.
"""
import numpy as np


def tube_wheel_clearance(shape, hub, axis, radius=.28, rim_radius=.16, width=.168,
                         transform=lambda p:p, max_step=.001):
    if shape['kind'] not in ('tube','cylinder'):
        raise ValueError('Clearance audit expects a cylindrical primitive')
    if not 0 < rim_radius < radius or width <= 0 or max_step <= 0:
        raise ValueError('Invalid wheel envelope or sampling step')
    hub=np.asarray(hub,float);axis=np.asarray(axis,float)
    length=np.linalg.norm(axis)
    if not np.isfinite(length) or length<=1e-12:raise ValueError('Invalid wheel axis')
    axis=axis/length
    a=np.asarray(transform(np.asarray(shape['a'],float)))
    b=np.asarray(transform(np.asarray(shape['b'],float)))
    length=np.linalg.norm(b-a);count=max(1,int(np.ceil(length/max_step)))
    points=np.linspace(a,b,count+1)-hub
    axial=points@axis;radial=np.linalg.norm(points-axial[:,None]*axis,axis=1)
    dx=np.maximum(abs(axial)-width/2,0)
    dr=np.maximum(np.maximum(rim_radius-radial,radial-radius),0)
    return float(np.min(np.hypot(dx,dr))-float(shape['radius'])-length/(2*count))
