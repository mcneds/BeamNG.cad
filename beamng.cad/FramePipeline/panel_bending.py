"""Provisional thin-plate bending across neighboring collision triangles."""
import math
import numpy as np
from frame_harness.projection import axial_columns
from rigid_bracing import gradient


def hinges(points,faces,masses,rigidity,damping_ratio=.15):
    adjacent={}
    for face in faces:
        a,b,c=map(int,face)
        for opposite,edge in ((a,(b,c)),(b,(c,a)),(c,(a,b))):
            adjacent.setdefault(tuple(sorted(edge)),[]).append(opposite)
    result=[]
    for (b,c),opposite in sorted(adjacent.items()):
        if len(opposite)>2:raise ValueError('Panel has a nonmanifold bending edge')
        if len(opposite)!=2:continue
        a,d=opposite;ids=[a,b,c,d];xyz=points[ids];edge=xyz[2]-xyz[1];length=np.linalg.norm(edge)
        heights=[np.linalg.norm(np.cross(xyz[i]-xyz[1],edge))/length for i in (0,3)]
        if min(heights)<1e-8:raise ValueError('Degenerate panel bending triangle')
        spring=rigidity*length/(sum(heights)/3)
        g=gradient(xyz);inverse_inertia=float(np.sum(g*g/np.asarray(masses)[ids,None]))
        damping=2*damping_ratio*math.sqrt(spring/inverse_inertia)
        result.append((ids,dict(spring=float(spring),damp=float(damping),deform=1e30,strength=1e30)))
    return result


def screen(points,masses,edges,springs,damping,torsions,limit=2.5):
    columns,_,_=axial_columns(points,edges)
    extra=np.zeros((3*len(points),len(torsions)))
    for col,(ids,_) in enumerate(torsions):
        for index,g in zip(ids,gradient(points[ids])):extra[index*3:index*3+3,col]=g
    matrix=np.column_stack((columns,extra))/np.sqrt(np.repeat(masses,3))[:,None]
    stiffness=np.r_[springs,[v['spring'] for _,v in torsions]]
    dampers=np.r_[damping,[v['damp'] for _,v in torsions]];dt=.0005
    highest=float(np.linalg.eigvalsh((matrix*(dt*dt*stiffness+2*dt*dampers))@matrix.T)[-1])
    scale=min(1.,limit/highest)
    for _,options in torsions:options['spring']*=scale;options['damp']*=scale
    return springs*scale,damping*scale,dict(step_seconds=dt,requested_step_eigenvalue=highest,final_step_eigenvalue=highest*scale,retention=scale,
        highest_linear_frequency_hz=float(np.sqrt(np.linalg.eigvalsh((matrix*(stiffness*scale))@matrix.T)[-1])/(2*np.pi)))
