"""Declared crank axes, or opt-in CAD belt-plane inference with evidence limits."""
import numpy as np
import components as c


def unit(value):
    value=np.asarray(value,float)
    if value.shape!=(3,) or not np.isfinite(value).all() or np.linalg.norm(value)<1e-8:
        raise ValueError('Engine reaction axis must be a finite nonzero vector')
    return value/np.linalg.norm(value)


def plane_consensus(bodies):
    """Volume-weighted normals of broad, thin native CAD bodies.

    A CVT's pulley faces/belt envelope provide a common plane. This inference is
    only enabled for an explicitly requested belt-CVT assumption; it is not a
    general rule that a component's principal axis is its shaft axis.
    """
    total=sum(volume for volume,_ in bodies);candidates=[]
    for volume,tensor in bodies:
        covariance=np.trace(tensor)/2*np.eye(3)-tensor
        eigen,axes=np.linalg.eigh(covariance)
        if eigen[0]<.25*eigen[1] and eigen[1]>.08*eigen[2]:candidates.append((volume,axes[:,0]))
    if total<=0 or len(candidates)<2:raise ValueError('CVT CAD does not establish a common belt plane; declare the crank axis')
    def principal(rows):
        matrix=sum(volume*np.outer(axis,axis) for volume,axis in rows)
        eigen,axes=np.linalg.eigh(matrix)
        return axes[:,-1],float(eigen[-1]/sum(eigen))
    axis,agreement=principal(candidates)
    if agreement<.98:raise ValueError('CVT CAD plane normals disagree; declare the crank axis')
    retained=[(v,a) for v,a in candidates if abs(a@axis)>=np.cos(np.radians(5))]
    coverage=sum(v for v,_ in retained)/total
    if coverage<.7 or len(retained)<2:raise ValueError('Insufficient CVT body volume supports the inferred belt plane; declare the crank axis')
    axis,agreement=principal(retained)
    return axis,dict(method='cad_cvt_plane_consensus',body_count=len(retained),volume_coverage=coverage,
        directional_agreement=agreement,scope='Assumes engine crank is parallel to the inferred belt-CVT pulley axes; confirm against actual hardware')


def resolve(engine,cvt,parameters):
    keys=['engine_axis_'+a for a in 'xyz'];present=[k in parameters for k in keys]
    if any(present):
        if not all(present):raise ValueError('Declare all three engine axis coordinates')
        axis=unit([parameters[k] for k in keys]);report=dict(method='declared',scope='Template-declared engine crank axis')
    else:
        meshes,cvt_moments,_=c.read_geometry(cvt);toward=cvt_moments[1]-c.read_geometry(engine)[1][1]
        if parameters.get('engine_axis_from_cvt_planes',False):
            bodies=[]
            for record,triangles in meshes:
                if record.get('BodyKind')=='surface' or record.get('NativeUnitDensityProperties') is None:
                    raise ValueError('CVT plane inference requires native solid-body mass properties')
                _,tensor=c.native_moments(record,1.,triangles)
                bodies.append((float(record['NativeUnitDensityProperties'][3]),tensor))
            axis,report=plane_consensus(bodies)
            if abs(axis@unit(toward))<.2:raise ValueError('Engine/CVT placement does not establish inferred crank-axis orientation')
            if axis@toward<0:axis=-axis
        else:
            axis=unit(toward);report=dict(method='provisional_com_line',scope='Provisional crank axis follows engine COM toward CVT COM; actual shaft axis unconfirmed')
    report['axis']=axis.tolist()
    return axis,report
