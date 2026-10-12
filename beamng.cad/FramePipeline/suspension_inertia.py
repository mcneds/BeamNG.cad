"""Rigid mechanism kinetic inertia per unit suspension travel.

This measures a contribution to generalized mass, not a complete vehicle mode.
CAD inertia is about its COM in the original assembly coordinates. Transforms
map that original geometry into each solved mechanism pose.
"""
import numpy as np


def rigid_kinetic_mass(mass,center,inertia,transform,derivative):
    center=np.asarray(center,float);inertia=np.asarray(inertia,float)
    transform=np.asarray(transform,float);derivative=np.asarray(derivative,float)
    if (not np.isfinite(mass) or mass<=0 or center.shape!=(3,) or inertia.shape!=(3,3)
        or transform.shape!=(4,4) or derivative.shape!=(4,4)
        or not all(np.isfinite(v).all() for v in (center,inertia,transform,derivative))):
        raise ValueError('Invalid rigid-body mass or motion data')
    if not np.allclose(inertia,inertia.T,atol=1e-10,rtol=1e-8):raise ValueError('Inertia must be symmetric')
    eigen=np.linalg.eigvalsh(inertia)
    if eigen[0]<-1e-10 or eigen[-1]>sum(eigen[:2])+1e-9:raise ValueError('Nonphysical rigid-body inertia')
    rotation=transform[:3,:3]
    if (not np.allclose(rotation@rotation.T,np.eye(3),atol=1e-7,rtol=0)
        or np.linalg.det(rotation)<0 or not np.allclose(transform[3],[0,0,0,1])
        or not np.allclose(derivative[3],0)):
        raise ValueError('Expected a proper rigid transform and its derivative')
    spin=derivative[:3,:3]@rotation.T
    if np.linalg.norm(spin+spin.T)>1e-5*max(1.,np.linalg.norm(spin)):
        raise ValueError('Motion derivative is not tangent to rigid rotation')
    spin=(spin-spin.T)/2
    omega=np.array([spin[2,1],spin[0,2],spin[1,0]])
    velocity=(derivative@np.r_[center,1.])[:3]
    translation=float(mass*(velocity@velocity))
    angular=float(omega@(rotation@inertia@rotation.T)@omega)
    return dict(kinetic_mass_kg=translation+angular,translation_kg=translation,rotation_kg=angular,
        com_velocity_per_unit_travel=velocity.tolist(),angular_velocity_per_unit_travel=omega.tolist())


def nodal_kinetic_mass(positions,masses,derivative):
    positions=np.asarray(positions,float);masses=np.asarray(masses,float);derivative=np.asarray(derivative,float)
    if (positions.shape!=(len(masses),3) or not len(masses) or derivative.shape!=(4,4)
        or not all(np.isfinite(v).all() for v in (positions,masses,derivative)) or np.any(masses<0) or sum(masses)<=0):
        raise ValueError('Invalid nodal mass allocation')
    velocities=np.c_[positions,np.ones(len(positions))]@derivative[:3].T
    return float(masses@np.sum(velocities**2,axis=1))


def rigid_kinetic_matrix(mass,center,inertia,transform,derivatives):
    """Generalized mass: kinetic energy is 0.5*qdot.T*M*qdot.

    Each derivative uses its stated coordinate unit; mixed units must not be
    collapsed into a scalar cost without an explicit normalization.
    """
    if not len(derivatives):raise ValueError('At least one motion coordinate required')
    rows=[rigid_kinetic_mass(mass,center,inertia,transform,d) for d in derivatives]
    velocity=np.array([r['com_velocity_per_unit_travel'] for r in rows]).T
    spin=np.array([r['angular_velocity_per_unit_travel'] for r in rows]).T
    rotation=np.asarray(transform)[:3,:3]
    return mass*velocity.T@velocity+spin.T@(rotation@inertia@rotation.T)@spin


def nodal_kinetic_matrix(positions,masses,derivatives):
    if not len(derivatives):raise ValueError('At least one motion coordinate required')
    for d in derivatives:nodal_kinetic_mass(positions,masses,d)
    points=np.c_[positions,np.ones(len(positions))]
    velocity=np.array([(points@np.asarray(d)[:3].T).ravel() for d in derivatives]).T
    return velocity.T@(np.repeat(masses,3)[:,None]*velocity)
