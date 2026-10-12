"""Numerical clutch compliance at current gearing, with passive state changes."""
import math


def current_budget(base,engine_inertia,gearing):
    if not math.isfinite(gearing) or gearing<=0 or gearing>base['maximum_gearing']*(1+1e-10):
        raise ValueError('Current gearing is outside the audited clutch budget')
    inverse_output=(1/base['effective_inertia_kg_m2']-1/engine_inertia)/base['maximum_gearing']**2
    effective=1/(1/engine_inertia+gearing**2*inverse_output)
    omega=2*math.pi*base['frequency_limit_hz']
    zeta=base['damping_nm_s_rad']/(2*base['effective_inertia_kg_m2']*omega)
    spring=effective*omega**2/2
    damp=2*zeta*effective*omega
    dt=base['step_seconds']
    return dict(spring=spring,damp=damp,effective_inertia=effective,
        step_eigenvalue=(dt*dt*2*spring+2*dt*damp)/effective)


def energy(angle,spring,freeplay=.125):
    displacement=max(abs(angle)-freeplay,0.)
    return spring*(displacement**3/3 if displacement<=1 else displacement**2/2-1/6)


def passive_angle(angle,old_spring,new_spring,freeplay=.125):
    if new_spring<=old_spring:return angle
    normalized=energy(angle,old_spring,freeplay)/new_spring
    displacement=(3*normalized)**(1/3) if normalized<=1/3 else math.sqrt(2*normalized+1/3)
    return math.copysign(displacement+freeplay,angle)
