"""Pressure-wheel discretization, separate from suspension and tire material laws.

Recipes and CAD mass allocation are evaluated at the reference resolution before
resampling. This avoids applying the low-mass carcass budget a second time just
because a user requests more contact nodes. Ring mass, centre and analytic
inertia are preserved. A refined discrete carcass still requires native tests;
unchanged per-beam coefficients do not prove identical effective tire stiffness.
"""
import math

REFERENCE_RAYS=16
DEFAULT_RAYS=24

def validate_rays(rays):
    if type(rays) is not int or not 12<=rays<=32:
        raise ValueError('Tire rays must be an integer between 12 and 32')
    return rays

def refine(options,rays):
    rays=validate_rays(rays);previous=validate_rays(options['numRays'])
    result=dict(options)
    for key in ('nodeWeight','hubNodeWeight','radius','hubRadius','tireWidth','hubWidth'):
        value=options[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('Invalid pressure-wheel '+key)
    factor=previous/rays
    result.update(numRays=rays,nodeWeight=options['nodeWeight']*factor,hubNodeWeight=options['hubNodeWeight']*factor)
    def moments(o):
        hub=2*o['numRays']*o['hubNodeWeight'];tread=2*o['numRays']*o['nodeWeight']
        spin=hub*o['hubRadius']**2+tread*o['radius']**2
        transverse=spin/2+hub*(o['hubWidth']/2)**2+tread*(o['tireWidth']/2)**2
        return [hub+tread,spin,transverse]
    before,after=moments(options),moments(result)
    if any(not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12) for a,b in zip(before,after)):
        raise ValueError('Tire refinement changed mass or inertia')
    return result,dict(reference_rays=previous,rays=rays,ring_mass_kg=after[0],spin_inertia_kg_m2=after[1],
        transverse_inertia_kg_m2=after[2],extra_native_nodes=4*(rays-previous),
        polygon_sagitta_m=options['radius']*(1-math.cos(math.pi/rays)),
        scope='Contact resolution; ring mass/inertia and authored coefficients preserved. Discrete carcass compliance remains provisional and requires native verification.')
