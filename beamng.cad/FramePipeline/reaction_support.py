"""Moment-preserving internal support nodes for experimental rigid housings."""
import numpy as np


def allocate(moments, points, current, retained, axis=(1.,0.,0.), minimum=2.):
    mass,center,inertia=moments
    center=np.asarray(center,float);inertia=np.asarray(inertia,float)
    points=np.asarray(points,float);current=np.asarray(current,float)
    retained=np.asarray(retained,bool)
    axis=np.asarray(axis,float);axis/=np.linalg.norm(axis)
    if mass<=0 or minimum<=0 or not np.isfinite(minimum):raise ValueError('Invalid reaction support mass')
    kept=current*np.where(retained,1.,.1)
    offset=points-center
    remaining=mass-kept.sum()
    if remaining<=3*minimum:raise ValueError('CAD mass cannot support three reaction nodes at the requested minimum')
    residual_center=-(kept@offset)/remaining
    second=np.trace(inertia)*.5*np.eye(3)-inertia
    covariance=second-(offset.T*kept)@offset-remaining*np.outer(residual_center,residual_center)
    if np.linalg.eigvalsh(covariance)[0]<=0:raise ValueError('Retained mount masses exhaust the CAD moment budget')
    # A transverse support direction with the largest admissible rank-one
    # moment. Use conditional covariance, including all off-diagonal terms.
    seed=np.eye(3)[np.argmin(abs(axis))]
    first=seed-axis*(seed@axis);first/=np.linalg.norm(first)
    basis=np.column_stack((first,np.cross(axis,first)))
    inverse=np.linalg.inv(covariance)
    eigen,vectors=np.linalg.eigh(basis.T@inverse@basis)
    direction=basis@vectors[:,0]
    if direction[np.argmax(abs(direction))]<0:direction=-direction
    support_mass=max(minimum,remaining*.2)
    transverse=.9/eigen[0]
    h=np.sqrt(transverse/(6*support_mass))
    after_transverse=covariance-transverse*np.outer(direction,direction)
    axial=.6/(axis@np.linalg.solve(after_transverse,axis))
    width=np.sqrt(axial/(2*support_mass))
    origin=center+residual_center
    support=origin+np.array([-width*axis+h*direction,width*axis+h*direction,-2*h*direction])
    residual=covariance-transverse*np.outer(direction,direction)-axial*np.outer(axis,axis)
    leftover=remaining-3*support_mass
    eigen,vectors=np.linalg.eigh(residual)
    if leftover<=0 or min(eigen)<=0:raise ValueError('Reaction support exhausts positive residual CAD moments')
    pairs=np.vstack((np.eye(3),-np.eye(3)))
    extra=origin+(pairs*np.sqrt(3*eigen/leftover))@vectors.T
    added=np.vstack((support,extra))
    added_mass=np.r_[np.full(3,support_mass),np.full(6,leftover/6)]
    all_points=np.vstack((points,added));weights=np.r_[kept,added_mass]
    actual_center=weights@all_points/mass;relative=all_points-center
    actual_inertia=sum(w*(p@p*np.eye(3)-np.outer(p,p)) for w,p in zip(weights,relative))
    if (abs(weights.sum()-mass)>mass*1e-10 or
        np.linalg.norm(actual_center-center)>1e-10 or
        not np.allclose(actual_inertia,inertia,rtol=1e-9,atol=1e-12)):
        raise ValueError('Internal support changed CAD moments')
    report=dict(experimental=True,minimum_support_mass_kg=float(min(added_mass[:3])),
        support_mass_kg=float(support_mass),target_mass_kg=float(mass),
        center_error_m=float(np.linalg.norm(actual_center-center)),
        inertia_error_relative=float(np.linalg.norm(actual_inertia-inertia)/np.linalg.norm(inertia)),
        scope='Internal rigid-body mass quadrature; supplemental nodes may lie outside the mesh and never collide; material strength uncalibrated')
    return kept,added,added_mass,report
