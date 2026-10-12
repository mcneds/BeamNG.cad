"""Native single-L-beam model with unique ordinary parent beams.

The tangent is generally nonsymmetric: never pass it off as an axial spring or
feed it into the positive symmetric budget. Force-driven native coupons validate
one angular child with normal parents; overlapping angular references do not.
"""
import math
import numpy as np


def validate_references(part):
    rows=[];defaults={}
    for row in part.get('beams',[])[1:]:
        if isinstance(row,dict):defaults.update(row);continue
        rows.append((row[:2],defaults|(row[-1] if isinstance(row[-1],dict) else {})))
    angular=[]
    for ids,options in rows:
        if options.get('beamType')!='|LBEAM':continue
        a,b=ids;c=options.get('id3:')
        if c is None or len({a,b,c})!=3:raise ValueError('L-beam requires three distinct node names')
        for pair in ({a,c},{b,c}):
            matches=[o for endpoints,o in rows if set(endpoints)==pair]
            if len(matches)!=1 or matches[0].get('beamType','|NORMAL')!='|NORMAL':
                raise ValueError('L-beam parents must be unique normal beams; angular/duplicate references are unvalidated')
            if matches[0].get('beamPrecompression',1)!=1:raise ValueError('Precompressed angular parents are unvalidated')
        if options.get('beamPrecompression',1)!=1 or options.get('beamDamp',0)!=0 or options.get('dampCutoffHz',0)!=0:
            raise ValueError('Only undamped, unprecompressed angular children are validated')
        angular.append((a,b,c))
    return angular


def tangent(points,spring):
    """Rest-position 9x9 force derivative K, for force = -K @ displacement."""
    p=np.asarray(points,float)
    if p.shape!=(3,3) or not np.isfinite(p).all() or not math.isfinite(spring) or spring<=0:raise ValueError('Invalid angular geometry or stiffness')
    lengths=[];columns=[]
    for a,b in ((0,1),(0,2),(1,2)):
        vector=p[b]-p[a];length=float(np.linalg.norm(vector))
        if length<1e-7:raise ValueError('Coincident angular nodes')
        col=np.zeros((3,3));col[a]=-vector/length;col[b]=vector/length;columns.append(col.ravel());lengths.append(length)
    x,y,z=lengths;ca=(x*x+y*y-z*z)/(2*x*y);cb=(x*x+z*z-y*y)/(2*x*z)
    if max(abs(ca),abs(cb))>1-1e-8:raise ValueError('Collinear angular nodes')
    return spring*np.outer(columns[0],columns[0]-ca*columns[1]-cb*columns[2])


def force(points,reference,spring):
    """Geometric extension model for a child with unprecompressed normal parents."""
    tangent(reference,spring)  # Validate geometry and coefficient.
    p=np.asarray(points,float);r=np.asarray(reference,float)
    x,y,z=[np.linalg.norm(r[b]-r[a]) for a,b in ((0,1),(0,2),(1,2))]
    cosine=(y*y+z*z-x*x)/(2*y*z)
    delta=p[1]-p[0];length=np.linalg.norm(delta);left=np.linalg.norm(p[0]-p[2]);right=np.linalg.norm(p[1]-p[2])
    if length<1e-7:raise ValueError('Collapsed angular child')
    target=math.sqrt(max(0,left*left+right*right-2*left*right*cosine))
    pair=spring*(length-target)*delta/length
    return np.array([pair,-pair,np.zeros(3)])
