"""Optional passive two-stage coilover spring law, measured at the shock eyes."""
import math


def settings_for_corner(roles,corner,parameters):
    """Optional axle default only for an unspecified component, never an override."""
    owner=roles[corner.lower()+'_spring_damper'];settings=owner.get('CoiloverSpring')
    source=owner['Id']
    if settings is None and parameters.get('mirror_missing_coilover_settings',False):
        other=corner[0]+('R' if corner[1]=='L' else 'L')
        peer=roles[other.lower()+'_spring_damper']
        if peer.get('CoiloverSpring') is not None:settings=peer['CoiloverSpring'];source=peer['Id']
    return settings,dict(source_component=source,inherited=source!=owner['Id'],
        scope='Explicit axle-default assumption for unspecified spring settings' if source!=owner['Id'] else 'Component spring settings')


def rates(settings, length, bump_travel):
    settings=settings or {}
    mode=settings.get('Mode','auto')
    if mode=='auto':return None
    if mode!='dual_rate':raise ValueError('Unsupported coilover spring mode')
    values=[]
    for name in ('MainRateNPerM','TenderRateNPerM','CrossoverCompressionM'):
        value=settings.get(name)
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
            raise ValueError('Dual-rate coilover requires a positive finite '+name)
        values.append(float(value))
    main,tender,crossover=values
    if crossover>=min(length,bump_travel):raise ValueError('Coilover crossover must be within available bump travel, measured from the CAD ride position')
    combined=1/(1/main+1/tender)
    return dict(mode=mode,main_rate_n_m=main,tender_rate_n_m=tender,initial_rate_n_m=combined,
                final_rate_n_m=main,crossover_compression_m=crossover,design_length_m=float(length),
                crossover_reference='Compression from the CAD design ride position',
                preload_mode='Automatic support load at the CAD ride position',
                visual_scope='Both coils can share the spring slot; separate crossover-collar and tender lockup animation is not implemented')


def crossover_beam(law):
    """Extra stiffness after crossover; base spring keeps force continuous.

The compression-only helper's rest length is the eye distance at crossover.
It exerts no force at the ride position. Unlike a bounded stiffness switch,
its force depends only on travel beyond crossover, keeping force continuous.
"""
    return dict(beamType='|SUPPORT',beamSpring=law['final_rate_n_m']-law['initial_rate_n_m'],beamDamp=0,
                beamPrecompression=1-law['crossover_compression_m']/law['design_length_m'],beamLongBound=1)
