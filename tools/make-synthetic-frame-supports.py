"""Add native CAD mounting struts missing from the first synthetic frame.

Template hardpoints remain fixed. New tubes are real CAD inputs with independent
volume checks, not an artificial mass increase in an exported physics graph.
"""
import argparse,copy,hashlib,itertools,json,math
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser();p.add_argument('recipe',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
r=json.loads(a.recipe.read_text());out=copy.deepcopy(r);frame=next(v for v in out['components'] if v['id']=='frame')
original=copy.deepcopy(frame['primitives']);audit=[];existing=set()
for corner,points in r['hardpoints'].items():
    keys=['shock_top']+(['upper_inner_front','upper_inner_rear','lower_inner_front','lower_inner_rear','tie_inner'] if 'upper_ball' in points else ['hinge_inner','hinge_outer'])
    for name in keys:
        # Choose supports in the corner's outward coordinate system. Global-X
        # lexical tie breaking picked different braces on mirrored corners.
        # This also handles asymmetric input frames: candidates still come
        # exclusively from the actual tubes at this corner.
        mirror=np.array([1 if corner[1]=='L' else -1,1,1])
        point=np.array(points[name])*mirror;candidates=[]
        for shape in original:
            aa,bb=np.array(shape['a'])*mirror,np.array(shape['b'])*mirror;delta=bb-aa;length=np.linalg.norm(delta)
            closest=float(np.clip(np.dot(point-aa,delta)/length**2,0,1))
            for fraction in (closest,max(0,closest-.2/length),min(1,closest+.2/length)):
                candidates.append(aa+fraction*delta)
        candidates=np.unique(np.round(candidates,10),axis=0);distance=np.linalg.norm(candidates-point,axis=1)
        if min(distance)<.027:continue
        ids=np.argsort(distance)[:24];candidate=candidates[ids];distance=distance[ids]
        triples=np.array(list(itertools.combinations(range(len(candidate)),3)))
        unit=(candidate-point)/distance[:,None];direction=unit[triples]
        eigen=np.linalg.eigvalsh(np.einsum('nki,nkj->nij',direction,direction))
        score=eigen[:,0]/np.mean(distance[triples],axis=1)
        # Eigenvalue roundoff must not resolve physically equivalent triples
        # differently after reflection or reordering of the source tubes.
        best=int(np.flatnonzero(np.isclose(score,score.max(),rtol=1e-10,atol=1e-12))[0])
        roots=candidate[triples[best]]*mirror;point*=mirror
        if eigen[best,0]<.025:raise ValueError('Cannot triangulate CAD support for '+corner+'_'+name)
        for root in roots:
            key=tuple(sorted((tuple(point),tuple(root))))
            if key in existing:continue
            existing.add(key);length=float(np.linalg.norm(point-root));radius=.02;wall=.0025
            frame['primitives'].append(dict(kind='tube',center=None,size=None,a=root.tolist(),b=point.tolist(),radius=radius,wall=wall,
                analytic_volume_m3=math.pi*(radius**2-(radius-wall)**2)*length))
        audit.append(dict(mount=corner+'_'+name,initial_centerline_distance_m=float(min(distance)),roots=roots.tolist()))
frame['analytic_volume_m3']=sum(s['analytic_volume_m3'] for s in frame['primitives'])
out['components']=[frame];out['mount_supports']=audit
out['source']='Synthetic frame revision with physical CAD struts at unsupported suspension mounts; template hardpoints unchanged'
out.pop('recipe_sha256',None);out['recipe_sha256']=hashlib.sha256(json.dumps(out,sort_keys=True).encode()).hexdigest()
a.output.write_text(json.dumps(out,indent=2)+'\n')
print('Native frame primitives:',len(frame['primitives']),'supported mounting points:',len(audit))
