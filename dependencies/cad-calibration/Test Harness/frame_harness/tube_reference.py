"""Local hollow-section tracing for tubes that double back on global axes."""
from __future__ import annotations

import numpy as np
from matplotlib.path import Path as Polygon
from .cad import section_loops, polygon_properties, volume_properties


def basis_for(direction):
    x=np.asarray(direction,dtype=float); x=x/np.linalg.norm(x)
    y=np.eye(3)[np.argmin(abs(x))]; y-=x*np.dot(x,y); y/=np.linalg.norm(y)
    return np.array([x,y,np.cross(x,y)])


def rings(body,point,direction):
    basis=basis_for(direction)
    loops=section_loops(body,point,basis)
    result=[]
    for i,outer in enumerate(loops):
        holes=[p for j,p in enumerate(loops) if j!=i and Polygon(outer).contains_point(p[0])]
        if len(holes)!=1: continue
        area,offset,second=polygon_properties([outer,holes[0]])
        moments=np.linalg.eigvalsh(second)
        if moments[0]<=0 or moments[1]/moments[0]>1.6: continue
        roughness=[]; radii=[]
        for loop in [outer,holes[0]]:
            c=np.linalg.lstsq(np.column_stack((2*loop,np.ones(len(loop)))),np.sum(loop*loop,axis=1),rcond=None)[0][:2]
            r=np.linalg.norm(loop-c,axis=1)
            roughness.append(float(np.std(r)/np.mean(r))); radii.append(float(np.mean(r)))
        if max(roughness)>.1: continue
        result.append(dict(center=np.asarray(point)+offset@basis[1:],area=area,second=second,
                           radius=max(radii),roundness=max(roughness),anisotropy=moments[1]/moments[0]))
    return result


def nearest_ring(body,point,direction,radius):
    options=rings(body,point,direction)
    options=[r for r in options if np.linalg.norm(r['center']-point)<radius*.75
             and abs(r['radius']/radius-1)<.2]
    if not options: raise ValueError('No continuing local hollow section')
    return min(options,key=lambda r:np.linalg.norm(r['center']-point))


def local_section(body,point,direction,radius):
    direction=np.array(direction); point=np.array(point)
    for _ in range(12):
        ring=nearest_ring(body,point,direction,radius); center=ring['center']
        h=radius*.3
        before=nearest_ring(body,center-h*direction,direction,radius)['center']
        after=nearest_ring(body,center+h*direction,direction,radius)['center']
        tangent=after-before; tangent/=np.linalg.norm(tangent)
        error=np.linalg.norm(tangent-direction); direction=tangent; point=center
        if error<.002: break
    else: raise ValueError('Local tube tangent did not converge')
    ring=nearest_ring(body,point,direction,radius)
    if ring['roundness']>=.04 or ring['anisotropy']>=1.15:
        raise ValueError('Local tube section is not circular')
    return ring,direction


def terminal(body,point,direction,radius):
    triangles=body.vertices[body.faces]; centers=triangles.mean(axis=1)
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    area=np.linalg.norm(normals,axis=1); normals/=np.maximum(area[:,None],1e-30)
    delta=centers-point; along=delta@direction
    radial=np.linalg.norm(delta-along[:,None]*direction,axis=1)
    selected=(along>-radius)&(along<3*radius)&(radial<1.3*radius)&(normals@direction>.4)
    if not selected.any(): raise ValueError('Local tube end surface not found')
    normal=np.average(normals[selected],axis=0,weights=area[selected])
    origin=np.average(centers[selected],axis=0,weights=area[selected])
    distance=np.dot(origin-point,normal)/np.dot(direction,normal)
    if distance<0 or distance>3*radius: raise ValueError('Invalid local tube end extension')
    return point+direction*distance


def simplify(path,tolerance):
    if len(path)<=2:return path
    chord=path[-1]-path[0]; length=np.linalg.norm(chord)
    if length<1e-12: raise ValueError('Closed tube path requires an explicit loop reference')
    errors=np.linalg.norm(np.cross(path-path[0],chord),axis=1)/length
    i=int(np.argmax(errors))
    if errors[i]<=tolerance:return path[[0,-1]]
    return np.vstack((simplify(path[:i+1],tolerance)[:-1],simplify(path[i:],tolerance)))


def trace_member(body):
    center=body.vertices.mean(axis=0)
    _,_,axes=np.linalg.svd(body.vertices-center,full_matrices=False)
    seeds=[]
    for axis in axes:
        extent=(body.vertices-center)@axis
        for fraction in (.25,.5,.75):
            point=center+axis*(extent.min()+fraction*np.ptp(extent))
            try:
                seeds.extend((r,axis) for r in rings(body,point,axis)
                             if r['roundness']<.04 and r['anisotropy']<1.15)
            except ValueError: pass
    if not seeds:raise ValueError('No reliable hollow-section seed for local tracing')
    seed,direction=min(seeds,key=lambda r:r[0]['roundness'])
    radius=seed['radius']; seed,direction=local_section(body,seed['center'],direction,radius)
    halves=[]; samples=[]
    for sign in (-1,1):
        point=seed['center']; tangent=direction*sign; path=[point]; measured=[seed]
        # Length budget comes from actual material volume and measured section, not a global axis.
        max_steps=int(3*volume_properties(body)['volume_m3']/seed['area']/(radius*.5))+20
        for step in range(max_steps):
            predicted=point+tangent*radius*.5
            try: ring,new_tangent=local_section(body,predicted,tangent,radius)
            except ValueError:
                path.append(terminal(body,point,tangent,radius));measured.append(measured[-1]);break
            point=ring['center']; tangent=new_tangent
            if len(path)>10 and min(np.linalg.norm(np.array(path[:-8])-point,axis=1))<radius*.5:
                raise ValueError('Tube tracing revisited a branch or loop')
            path.append(point);measured.append(ring)
        else:raise ValueError('Tube trace exceeded CAD material length budget')
        halves.append(path);samples.append(measured)
    path=np.array(halves[0][::-1]+halves[1][1:])
    measured=samples[0][::-1]+samples[1][1:]
    area=float(np.median([r['area'] for r in measured]))
    lengths=np.linalg.norm(np.diff(path,axis=0),axis=1)
    areas=np.array([r['area'] for r in measured])
    integrated_volume=float(lengths@((areas[:-1]+areas[1:])*.5))
    discrepancy=abs(integrated_volume/volume_properties(body)['volume_m3']-1)
    if discrepancy>.05:raise ValueError(f'Locally traced tube volume differs from CAD by {discrepancy:.1%} (limit 5%)')
    distance=np.full(len(body.vertices),np.inf)
    for index,(a,b) in enumerate(zip(path,path[1:])):
        delta=b-a; length=np.linalg.norm(delta)
        # Coped tips can overhang the mean terminal section; this does not extend
        # the structural member or its volume integral.
        low=-2*radius/length if index==0 else 0
        high=1+2*radius/length if index==len(path)-2 else 1
        t=np.clip((body.vertices-a)@delta/np.dot(delta,delta),low,high)
        distance=np.minimum(distance,np.linalg.norm(body.vertices-a-t[:,None]*delta,axis=1))
    if distance.max()>1.3*max(r['radius'] for r in measured):
        raise ValueError('Tube trace does not cover all CAD branches')
    second=np.median([r['second'] for r in measured],axis=0)
    reduced=simplify(path,radius*.01)
    indices=[int(np.argmin(np.linalg.norm(path-p,axis=1))) for p in reduced]
    # Keep actual local section changes; never substitute one seed's area for a combined body.
    for first,last in zip(indices.copy(),indices[1:].copy()):
        anchor=first
        for i in range(first+1,last):
            if abs(areas[i]/areas[anchor]-1)>.03:
                indices.append(i);anchor=i
    indices=sorted(set(indices));segments=[]
    for first,last in zip(indices,indices[1:]):
        weights=lengths[first:last]; stations=measured[first:last+1]
        def average(values):return float(weights@((np.array(values[:-1])+values[1:])*.5)/weights.sum())
        section_area=average([r['area'] for r in stations])
        polar=average([np.trace(r['second']) for r in stations])
        segments.append(dict(a=path[first].tolist(),b=path[last].tolist(),area_m2=section_area,
                             Iy_m4=polar/2,Iz_m4=polar/2,J_m4=polar,radius_m=max(r['radius'] for r in stations)))
    reduced=path[indices]
    return dict(a=path[0].tolist(),b=path[-1].tolist(),path=reduced.tolist(),segments=segments,axes=basis_for(direction).tolist(),
                area_m2=area,Iy_m4=float(second[1,1]),Iz_m4=float(second[0,0]),J_m4=float(np.trace(second)),
                radius_m=radius,method='CAD local hollow-section continuation',section_volume_discrepancy=discrepancy,
                extraction=dict(stations=len(measured),maximum_roundness=max(r['roundness'] for r in measured),
                                integrated_volume_m3=integrated_volume,maximum_surface_distance_m=float(distance.max()),
                                section_area_range_m2=[float(areas.min()),float(areas.max())]))
