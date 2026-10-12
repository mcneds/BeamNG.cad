"""Independent 3-D Timoshenko frame reference. Strength outputs are elastic proxies."""
from __future__ import annotations
import numpy as np
from scipy.linalg import null_space


def element_matrix(length, area, iy, iz, torsion, young, poisson, shear=None):
    """Local [u,v,w,rx,ry,rz] DOFs at each end, circular-section shear factor .9."""
    shear = young/(2*(1+poisson)) if shear is None else shear; k = np.zeros((12, 12))
    def put(indices, values):
        k[np.ix_(indices, indices)] += values
    for indices, value in (([0, 6], young*area/length), ([3, 9], shear*torsion/length)):
        put(indices, value*np.array([[1., -1.], [-1., 1.]]))
    for indices, inertia, sign in (([1, 5, 7, 11], iz, 1), ([2, 4, 8, 10], iy, -1)):
        phi = 12*young*inertia/(.9*shear*area*length**2)
        a = 12*young*inertia/((1+phi)*length**3); b = sign*a*length/2
        c = (4+phi)*young*inertia/((1+phi)*length); d = (2-phi)*young*inertia/((1+phi)*length)
        put(indices, np.array([[a,b,-a,b],[b,c,-b,d],[-a,-b,a,-b],[b,d,-b,c]]))
    return k


def analytical_checks():
    """Persist the reference solver's independent cantilever formula checks."""
    length,area,iy,iz,j,e,nu=2.,.001,1e-6,2e-6,3e-6,205e9,.29
    free=element_matrix(length,area,iy,iz,j,e,nu)[6:,6:];shear=e/(2*(1+nu))
    result={}
    for name,axis,expected in (('axial',0,length/(e*area)),('bending_y',1,length**3/(3*e*iz)+length/(.9*shear*area)),
                               ('bending_z',2,length**3/(3*e*iy)+length/(.9*shear*area)),('torsion',3,length/(shear*j))):
        actual=float(np.linalg.solve(free,np.eye(6)[axis])[axis])
        result[name]={'expected':expected,'actual':actual,'relative_error':abs(actual/expected-1)}
    return {'accepted':all(r['relative_error']<=.02 for r in result.values()),'checks':result}


def closest_segments(a, b, c, d):
    # The bounded two-variable quadratic has an interior solution or a minimum
    # on one of four edges. Avoid thousands of iterative optimizer launches.
    u,v,w=b-a,d-c,a-c
    aa,bb,cc,dd,ee=np.dot(u,u),np.dot(u,v),np.dot(v,v),np.dot(u,w),np.dot(v,w)
    choices=[]; determinant=aa*cc-bb*bb
    if determinant>1e-14*max(aa*cc,1e-30):
        s,t=(bb*ee-cc*dd)/determinant,(aa*ee-bb*dd)/determinant
        if 0<=s<=1 and 0<=t<=1:choices.append((s,t))
    for s in (0.,1.):choices.append((s,float(np.clip((ee+bb*s)/cc,0,1)) if cc>1e-30 else 0.))
    for t in (0.,1.):choices.append((float(np.clip((bb*t-dd)/aa,0,1)) if aa>1e-30 else 0.,t))
    s,t=min(choices,key=lambda p:np.dot(w+p[0]*u-p[1]*v,w+p[0]*u-p[1]*v))
    return np.array([s,t]),a+s*u,c+t*v


def build_frame(sections, young=205e9, poisson=.29, materials=None):
    expanded={}
    for name,s in sections.items():
        path=s.get('path',[s['a'],s['b']])
        segments=s.get('segments',[dict(a=a,b=b) for a,b in zip(path,path[1:])])
        for i,segment in enumerate(segments):
            expanded[f'{name}:{i}']=s|segment|{'source_member':name,'segment_index':i}
    sections=expanded
    names = sorted(sections); points = []; stations = {}; joint_pairs = []; continuous_pairs=[]
    def add(point):
        points.append(np.asarray(point)); return len(points)-1
    for name in names:
        s = sections[name]; stations[name] = [(0., add(s['a'])), (1., add(s['b']))]
    for i, name in enumerate(names):
        s = sections[name]; a, b = np.array(s['a']), np.array(s['b'])
        for other in names[i+1:]:
            z = sections[other]; c, d = np.array(z['a']), np.array(z['b'])
            if s['source_member']==z['source_member']:
                # Consecutive measured segments are continuous, not overlapping welded tubes.
                for f,p in ((0.,a),(1.,b)):
                    for g,q in ((0.,c),(1.,d)):
                        if np.linalg.norm(p-q)<1e-7:
                            ix,iy=add(p),add(q)
                            stations[name].append((f,ix));stations[other].append((g,iy));continuous_pairs.append((ix,iy))
                continue
            reach=(s['radius_m']+z['radius_m'])*1.05
            if np.any(np.maximum(np.minimum(a,b),np.minimum(c,d))-np.minimum(np.maximum(a,b),np.maximum(c,d))>reach):
                continue
            fractions, x, y = closest_segments(a, b, c, d)
            # A welded contact is inferred only near an end of at least one member.
            length1, length2 = np.linalg.norm(b-a), np.linalg.norm(d-c)
            near_end = min(fractions[0], 1-fractions[0])*length1 < 2*z['radius_m'] or min(fractions[1], 1-fractions[1])*length2 < 2*s['radius_m']
            if near_end and np.linalg.norm(x-y) <= (s['radius_m']+z['radius_m'])*1.05:
                ix, iy = add(x), add(y)
                stations[name].append((float(fractions[0]), ix)); stations[other].append((float(fractions[1]), iy))
                joint_pairs.append((ix, iy))
    parent = list(range(len(points)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def join(i, j):
        parent[root(j)] = root(i)
    for i, j in joint_pairs+continuous_pairs:
        join(i, j)
    for entries in stations.values():
        entries.sort()
        for (f, i), (g, j) in zip(entries, entries[1:]):
            if g-f < 1e-4:
                join(i, j)
    roots = sorted({root(i) for i in range(len(points))}); indices = {r:i for i,r in enumerate(roots)}
    xyz = np.array([np.mean([p for i,p in enumerate(points) if root(i)==r], axis=0) for r in roots])
    size = len(xyz)*6; matrix = np.zeros((size, size)); elements = []
    for name, entries in stations.items():
        nodes = [indices[root(i)] for _, i in entries]
        nodes = [n for i,n in enumerate(nodes) if i == 0 or n != nodes[i-1]]
        s = sections[name]
        for a,b in zip(nodes, nodes[1:]):
            delta = xyz[b]-xyz[a]; length = np.linalg.norm(delta)
            if length < 1e-6:
                continue
            x = delta/length; y = np.eye(3)[np.argmin(abs(x))]; y -= x*np.dot(x,y); y /= np.linalg.norm(y)
            rotation = np.array([x,y,np.cross(x,y)]); transform = np.kron(np.eye(4), rotation)
            material=materials[s['source_member']] if materials is not None else {}
            local = element_matrix(length, s['area_m2'], s['Iy_m4'], s['Iz_m4'], s['J_m4'],
                                   material.get('young_pa',young),material.get('poisson',poisson),material.get('shear_pa'))
            dofs = np.r_[np.arange(6*a,6*a+6), np.arange(6*b,6*b+6)]
            matrix[np.ix_(dofs,dofs)] += transform.T @ local @ transform
            elements.append({'member':s['source_member'],'a':a,'b':b,'dofs':dofs,'local':local,'transform':transform,'section':s})
    return {'positions':xyz,'matrix':matrix,'elements':elements,'inferred_welds':len(joint_pairs),
            'continuous_segment_joints':len(continuous_pairs)}


def transfer(position, xyz):
    i = int(np.argmin(np.linalg.norm(xyz-position,axis=1))); r = np.asarray(position)-xyz[i]
    skew = np.array([[0,-r[2],r[1]],[r[2],0,-r[0]],[-r[1],r[0],0]])
    mapping = np.zeros((3,6*len(xyz))); mapping[:,6*i:6*i+3] = np.eye(3); mapping[:,6*i+3:6*i+6] = -skew
    return mapping


def solve_frame(frame, node_positions, scenario, yield_stress):
    from scipy.linalg import cho_factor,cho_solve
    xyz, k = frame['positions'], frame['matrix']
    constraints = np.vstack([transfer(node_positions[n],xyz) for n in scenario.fixed_nodes])
    # Hundreds of mounting loads share one frame and support fixture. Cache
    # only the load-independent constrained operator; forces and yield checks
    # are still evaluated independently for every scenario.
    key=(constraints.shape,constraints.tobytes())
    cache=frame.setdefault('_constraint_solutions',{})
    if key not in cache:
        basis = null_space(constraints)
        reduced = basis.T @ k @ basis
        scale=np.sqrt(np.maximum(np.diag(reduced),1e-30))
        normalized=reduced/scale[:,None]/scale[None,:]
        eigen = np.linalg.eigvalsh(normalized)
        if eigen[0] < 1e-11:
            raise ValueError('CAD reference has disconnected members or unconstrained mechanisms')
        cache[key]=(basis,scale,cho_factor(normalized,lower=True))
    basis,scale,factor=cache[key]
    load = np.zeros(len(k))
    for n,v in scenario.resolved_load_vectors().items():
        load += transfer(node_positions[n],xyz).T @ np.asarray(v)
    u = basis @ (cho_solve(factor,(basis.T@load)/scale)/scale)
    utilization = []
    for e in frame['elements']:
        force = e['local'] @ e['transform'] @ u[e['dofs']]; s = e['section']
        axial = max(abs(force[0]),abs(force[6]))/s['area_m2']
        bend = max(np.hypot(force[4]/s['Iy_m4'],force[5]/s['Iz_m4']),np.hypot(force[10]/s['Iy_m4'],force[11]/s['Iz_m4']))*s['radius_m']
        tau = max(abs(force[3]),abs(force[9]))*s['radius_m']/s['J_m4']
        strength=yield_stress[e['member']] if isinstance(yield_stress,dict) else yield_stress
        utilization.append((float(np.sqrt((axial+bend)**2+3*tau*tau)/strength),e['member']))
    worst, member = max(utilization)
    return {'compliance_m_n':float(load@u),'first_yield_force_n':1/worst,'first_yield_member':member,
            'model':'linear Timoshenko frame; fully welded inferred contacts; elastic first-yield estimate',
            'welds':frame['inferred_welds'],'reference_nodes':len(xyz)}
