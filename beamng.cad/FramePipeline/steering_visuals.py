"""Appearance-only steering animation. Never defines a physical column or ratio."""
import hashlib
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation


def fingerprint(meshes):
    digest=hashlib.sha256()
    for _,triangles in meshes:
        data=np.asarray(triangles,dtype='<f8')
        digest.update(str(data.shape).encode());digest.update(data.tobytes())
    return digest.hexdigest()


def fit(meshes):
    """Fit the rim plane/circle for visual alignment; reject unclear geometry."""
    triangles=np.concatenate([t for _,t in meshes]);points=np.unique(triangles.reshape(-1,3),axis=0)
    center=points.mean(0);eigen,axes=np.linalg.eigh(np.cov(points.T))
    if eigen[0]>.12*eigen[1]:raise ValueError('Steering wheel has no clear rim plane; supply an explicit visual pivot and axis')
    axis=axes[:,0]
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);areas=np.linalg.norm(normals,axis=1)
    normals/=np.maximum(areas[:,None],1e-20)
    aligned=np.abs(normals@axis)>.99
    if aligned.any():
        _,basis=np.linalg.eigh((normals[aligned].T*areas[aligned])@normals[aligned]);axis=basis[:,-1]
    # BeamNG forward is -Y. Point the visual axis toward the driver.
    if axis[1]<0:axis=-axis
    up=np.array([0.,0.,1.]);up-=axis*(up@axis)
    if np.linalg.norm(up)<.1:raise ValueError('Steering rim faces vertically; supply an explicit visual orientation')
    up/=np.linalg.norm(up)
    right=np.cross(up,axis);basis=np.column_stack((right,up,axis))
    local=(points-center)@basis;xy=local[:,:2];rim=xy[ConvexHull(xy).vertices]
    rng=np.random.default_rng(0);best=None
    for _ in range(512):
        a,b,c=rim[rng.choice(len(rim),3,replace=False)]
        matrix=2*np.array([b-a,c-a])
        if abs(np.linalg.det(matrix))<1e-8:continue
        origin=np.linalg.solve(matrix,[b@b-a@a,c@c-a@a]);radius=np.linalg.norm(a-origin)
        error=np.abs(np.linalg.norm(rim-origin,axis=1)-radius);mask=error<.0015
        score=int(mask.sum())
        if best is None or score>best[0]:best=(score,mask,origin,radius)
    if best is None or best[0]<max(8,.6*len(rim)):raise ValueError('Steering rim circle is ambiguous; supply an explicit visual pivot')
    arc=rim[best[1]];matrix=np.column_stack((2*arc,np.ones(len(arc))))
    x,y,k=np.linalg.lstsq(matrix,(arc*arc).sum(1),rcond=None)[0];radius=float(np.sqrt(k+x*x+y*y))
    angles=np.sort(np.arctan2(arc[:,1]-y,arc[:,0]-x));coverage=2*np.pi-np.diff(np.r_[angles,angles[0]+2*np.pi]).max()
    if coverage<np.pi:raise ValueError('Steering rim fit covers less than half a circle')
    residual=float(np.max(np.abs(np.linalg.norm(arc-[x,y],axis=1)-radius)))
    if not np.isfinite(radius) or residual>.003:raise ValueError('Steering rim fit exceeds the visual alignment tolerance')
    pivot=center+basis@np.array([x,y,(local[:,2].min()+local[:,2].max())*.5])
    return dict(Enabled=True,Pivot=pivot.tolist(),Axis=axis.tolist(),Up=up.tolist(),
                SourceHash=fingerprint(meshes),FitMethod='CAD rim plane and robust outer-circle fit; visual only',
                Radius=radius,FitResidual=residual)


def transform(settings,meshes):
    if settings.get('SourceHash')!=fingerprint(meshes):raise ValueError('Steering appearance geometry changed; refit its visual pivot before exporting')
    pivot=np.asarray(settings['Pivot'],float);axis=np.asarray(settings['Axis'],float);up=np.asarray(settings['Up'],float)
    if any(v.shape!=(3,) or not np.isfinite(v).all() for v in (pivot,axis,up)):raise ValueError('Steering appearance requires finite three-dimensional coordinates')
    if np.linalg.norm(axis)<1e-8:raise ValueError('Steering appearance axis is zero')
    axis/=np.linalg.norm(axis);up-=axis*(up@axis)
    if np.linalg.norm(up)<1e-8:raise ValueError('Steering appearance up direction is parallel to its axis')
    up/=np.linalg.norm(up);basis=np.column_stack((np.cross(up,axis),up,axis))
    angles=Rotation.from_matrix(basis).as_euler('YZX',degrees=True)
    return pivot,basis,dict(x=float(angles[2]),y=float(angles[0]),z=float(angles[1]))
