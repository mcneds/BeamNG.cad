"""Explicit rigid-component representation: CAD moments, not a tessellated hull."""
import itertools
import numpy as np
from frame_harness.calibration import fit_masses
from rigid_bracing import reinforce


def generate(component, anchors, moments):
    if component.get('Template') not in ('bulk','auto'):
        raise ValueError('Rigid representation is for rigid bulk components, not flexible panels')
    if any(a.get('Status')!='resolved' for a in anchors):
        raise ValueError('Resolve every rigid component mounting point first')
    owner=component['Id'];names=[owner+'_mount_'+a['Id'] for a in anchors]
    if len(set(names))!=len(names):raise ValueError('Duplicate rigid mounting point')
    points=[a['Position'] for a in anchors]
    if points:
        from vehicle_templates import rigid_mass_points
        xyz,importance=rigid_mass_points(moments,points)
    else:
        mass,center,inertia=moments
        covariance=(np.trace(inertia)*.5*np.eye(3)-inertia)/mass
        eigen,axes=np.linalg.eigh(covariance)
        if mass<=0 or min(eigen)<=0:raise ValueError('Rigid component needs positive volumetric CAD mass properties')
        xyz=np.asarray(center)+np.vstack((np.eye(3),-np.eye(3)))*np.sqrt(3*eigen)@axes.T
        importance=np.full(6,mass/6)
    names.extend(owner+'_mass_'+str(i) for i in range(6))
    masses,fit=fit_masses(xyz,*moments,minimum_weights=importance)
    if not fit['accepted']:raise ValueError('Compact rigid representation cannot preserve CAD mass/COM/inertia')
    pairs=list(itertools.combinations(range(len(xyz)),2))
    springs,dampers,_=reinforce(xyz,pairs,masses,angular=False)
    group=owner+'_structure'
    part=dict(information=dict(name=component['Name'],authors='BeamNG CAD'),slotType=owner,
        nodes=[['id','posX','posY','posZ']]+[[n,*map(float,p),dict(nodeWeight=float(m),collision=False,staticCollision=False,selfCollision=False,group=[group])] for n,p,m in zip(names,xyz,masses)],
        beams=[['id1:','id2:']]+[[names[a],names[b],dict(beamSpring=float(k),beamDamp=float(d),beamDeform=1e30,beamStrength=1e30,beamType='|NORMAL',beamPrecompression=1,breakGroup='')] for (a,b),k,d in zip(pairs,springs,dampers)],
        triangles=[['id1:','id2:','id3:']],flexbodies=[['mesh','[group]:','nonFlexMaterials']])
    report=dict(settings=dict(method='rigid'),mass=fit,nodes=len(names),beams=len(pairs),collision_triangles=0,
        render_as_rigid_prop=True,qualification='provisional',
        limitations=['Rigid CAD mass/COM/inertia representation; no collision shell, deformation or steering-column animation. Existing mounts still determine attachment behavior.'])
    return part,report
