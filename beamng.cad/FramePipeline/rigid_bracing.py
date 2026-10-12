"""Angular reinforcement for provisional rigid CAD mechanisms.

Normal beams alone poorly restrain thin plates at practical node masses. Native
torsion bars resist the out-of-plane angle without inventing thick CAD geometry.
All springs are jointly limited by the mass-normalized tangent spectrum.
"""
import itertools,math
import numpy as np
from scipy.optimize import nnls
from frame_harness.projection import axial_columns,reduced_mass_damping


def budget_connections(part,nodes,connections,limit=3.2):
    """Bound the assembled explicit tangent while preserving sealed/body blocks.

    Pressure-wheel-generated beams are absent here and still require a native
    audit. Bounded stops and filtered coilover damping are nonlinear dynamics,
    not represented by this rest-state tangent screening.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import eigsh
    names=list(nodes);index={n:i for i,n in enumerate(names)}
    masses=np.array([nodes[n]['options']['nodeWeight'] for n in names])
    selected={id(o) for o in connections};rows=[];cols=[];values=[];base=[];added=[];options_by_column={};dt=.0005
    def column(ids,vectors,spring,damp,adjustable=False):
        col=len(base);value=dt*dt*spring+2*dt*damp
        base.append(0 if adjustable else value);added.append(value if adjustable else 0)
        for name,vector in zip(ids,vectors):
            i=index[name]
            for axis,v in enumerate(vector):rows.append(i*3+axis);cols.append(col);values.append(v/np.sqrt(masses[i]))
    for section in ('beams','hydros'):
        defaults={}
        for row in part.get(section,[])[1:]:
            if isinstance(row,dict):defaults.update(row);continue
            a,b=row[:2];options=defaults|(row[-1] if isinstance(row[-1],dict) else {})
            if options.get('beamType')=='|LBEAM':
                raise ValueError('L-beam angular force tangent is not an axial spring; assembled stability screening does not support it')
            delta=np.array(nodes[b]['position'],dtype=float)-nodes[a]['position'];delta/=np.linalg.norm(delta)
            bounded=options.get('beamType')=='|BOUNDED'
            if not bounded and options.get('dampCutoffHz',0):
                raise ValueError('Assembled tangent requires unfiltered damping on normal beams; a cutoff adds unmodelled state')
            column([a,b],[-delta,delta],float(options.get('beamSpring',0)),
                   0 if bounded and options.get('dampCutoffHz') else float(options.get('beamDamp',0)),id(row[-1]) in selected)
            if id(row[-1]) in selected:options_by_column[len(base)-1]=row[-1]
    for row in part.get('torsionbars',[])[1:]:
        if not isinstance(row,list):continue
        adjustable=id(row[4]) in selected
        column(row[:4],gradient(np.array([nodes[n]['position'] for n in row[:4]])),row[4]['spring'],row[4]['damp'],adjustable)
        if adjustable:options_by_column[len(base)-1]=row[4]
    # Rail normal restraints and capped axial end stops share one spring.
    # Include all three directions conservatively, including the end-stop
    # tangent, even though translation is free within the stroke.
    for row in part.get('slidenodes',[])[1:]:
        if not isinstance(row,list):continue
        name,rail,options=row;links=part['rails'][rail]['links:']
        if len(links)!=2:raise ValueError('Tangent audit requires straight two-node rails')
        a,b=links;pa,pb,pc=[np.array(nodes[n]['position']) for n in (a,b,name)]
        d=pb-pa;t=float((pc-pa)@d/(d@d))
        if not 0<=t<=1 or np.linalg.norm(pc-(pa+t*d))>1e-7:raise ValueError('Slider does not start on its rail')
        for direction in np.eye(3):
            column([name,a,b],[direction,-(1-t)*direction,-t*direction],options['spring'],0,True)
            options_by_column[len(base)-1]=options
    A=coo_matrix((values,(rows,cols)),shape=(3*len(names),len(base))).tocsr()
    added=np.array(added);fixed=A.multiply(base)@A.T;variable=A.multiply(added)@A.T
    start=np.random.default_rng(0).normal(size=fixed.shape[0])
    def dominant(matrix):
        if not np.any(matrix.data):return np.zeros(1),np.zeros((matrix.shape[0],1))
        if matrix.shape[0]<48:
            eigen,modes=np.linalg.eigh(matrix.toarray());return eigen[-1:],modes[:,-1:]
        return eigsh(matrix,k=1,which='LA',tol=1e-7,v0=start)
    def largest(matrix):return float(dominant(matrix)[0][0])
    def excessive_modes(matrix):
        # A repeated eigenvalue has no unique eigenvector. Its entire spectral
        # subspace is needed so mirrored/repeated mechanisms cannot receive
        # different spring reductions due to the eigensolver's arbitrary basis.
        size=matrix.shape[0]
        if not np.any(matrix.data):return np.empty(0),np.empty((size,0))
        count=min(8,size-1)
        while True:
            if size<128 or count>=size-1 or (count>=64 and size<=6500):
                # Asking ARPACK for hundreds of eigenvectors repeatedly is
                # slower than a direct interval solve at this assembly size.
                # Both paths return the complete excessive subspace.
                from scipy.linalg import eigh
                eigen,modes=eigh(matrix.toarray(order='F'),subset_by_value=(limit,np.inf),
                                 check_finite=False,overwrite_a=True)
                break
            eigen,modes=eigsh(matrix,k=count,which='LA',tol=1e-11,v0=start,
                              ncv=min(size,max(4*count+1,40)))
            if eigen[0]<limit-1e-7:break
            count=min(size-1,count*2)
        keep=eigen>limit
        return eigen[keep],modes[:,keep]
    baseline=largest(fixed)
    if baseline>=limit:raise ValueError('Sealed frame/rigid blocks exceed the assembled tangent budget: '+str(baseline))
    before=largest(fixed+variable);scales=np.ones(len(base));iterations=0
    # Every positive rank-one constraint is bounded by the complete operator.
    # A coefficient whose own eigenvalue exceeds the limit must be reduced in
    # every feasible solution. Apply this necessary bound before repeatedly
    # finding hundreds of excessive modes on a large native CAD assembly.
    isolated=added*np.asarray(A.multiply(A).sum(axis=0)).ravel()
    np.divide(limit-1e-6,isolated,out=scales,where=isolated>limit)
    initially_limited=int(np.count_nonzero(scales<1))
    # A single global factor lets one light accessory soften every suspension
    # mount. Reduce constraints participating in excessive modes instead.
    # The final eigenvalue is independently checked; no local count substitutes
    # for the coupled system bound.
    for iterations in range(160):
        matrix=fixed+A.multiply(added*scales)@A.T
        eigen,modes=excessive_modes(matrix)
        from frame_harness.progress import emit
        emit('Assembled stability',completed=iterations,total=160,
             detail=f'{len(names)} nodes; {len(eigen)} excessive modes'+(f'; largest step eigenvalue {eigen[-1]:.3g}' if len(eigen) else '; within budget'))
        if not len(eigen):break
        # Summing the complete excessive subspace is invariant to rotations of
        # a degenerate eigenbasis, reflection, and node/constraint enumeration.
        participation=np.square(A.T@modes)
        total=np.sum(participation,axis=1)
        contribution=total*added*scales
        affected=contribution>np.max(contribution)*.05
        # Apply each constraint's own weighted relative excess. A single scalar
        # summed over all excessive modes lets a very stiff unrelated mechanism
        # halve one which only needs a few percent reduction. Functions of the
        # eigenvalues over the complete subspace remain invariant to a rotated
        # basis of repeated modes. Fixed blocks are untouched; their contribution
        # makes this conservative update converge over successive iterations.
        relative=(eigen-limit+1e-6)/eigen
        change=np.divide(participation@relative,total,out=np.zeros_like(total),where=total>0)
        scales[affected]*=1-np.minimum(.99,change[affected])
    variable=A.multiply(added*scales)@A.T
    if largest(fixed+variable)>limit:
        low=0.;high=1.
        for _ in range(20):
            mid=(low+high)/2
            if largest(fixed+variable*mid)>limit:high=mid
            else:low=mid
        scales*=low
    grouped={}
    for col,options in options_by_column.items():grouped.setdefault(id(options),[]).append(col)
    coupled_seen=set()
    for group in part.get('cadConstraintGroups',{}).values():
        members=[]
        for section,pairs in group.items():
            if section not in ('beams','hydros'):raise ValueError('Unsupported coupled constraint section')
            for pair in pairs:
                found=[row[-1] for row in part.get(section,[])[1:] if isinstance(row,list) and set(row[:2])==set(pair)]
                if len(pair)!=2 or len(found)!=1 or id(found[0]) not in grouped:
                    raise ValueError('Coupled constraint must identify one adjustable beam')
                if id(found[0]) in coupled_seen:raise ValueError('Overlapping coupled constraint groups')
                coupled_seen.add(id(found[0]))
                members.extend(grouped[id(found[0])])
        if not members:raise ValueError('Empty coupled constraint group')
        scales[members]=min(scales[members])
    for columns in grouped.values():scales[columns]=min(scales[columns])
    for columns in grouped.values():
        col=columns[0];options=options_by_column[col]
        spring,damp=('beamSpring','beamDamp') if 'beamSpring' in options else ('spring','damp')
        options[spring]*=scales[col]
        if damp in options:options[damp]*=scales[col]
    factors=[float(scales[col]) for col in options_by_column]
    return dict(step_seconds=dt,step_limit=limit,baseline_step_eigenvalue=baseline,
                requested_step_eigenvalue=before,connection_scale=min(factors,default=1),maximum_connection_scale=max(factors,default=1),
                limited_connections=sum(v<1 for v in factors),iterations=iterations,
                isolated_constraint_caps=initially_limited,
                strategy='Reduce each connection by its relative excess over the complete excessive spectral subspace',
                final_step_eigenvalue=largest(fixed+A.multiply(added*scales)@A.T))


def angle(points):
    a,b,c,d=points;axis=c-b;axis/=np.linalg.norm(axis)
    left=a-b;right=d-c
    left-=axis*np.dot(left,axis);right-=axis*np.dot(right,axis)
    return math.atan2(np.dot(axis,np.cross(left,right)),np.dot(left,right))


def gradient(points):
    h=max(np.linalg.norm(np.ptp(points,axis=0))*1e-6,1e-8);result=np.zeros((4,3))
    for i,j in itertools.product(range(4),range(3)):
        plus=points.copy();minus=points.copy();plus[i,j]+=h;minus[i,j]-=h
        difference=angle(plus)-angle(minus)
        result[i,j]=math.atan2(math.sin(difference),math.cos(difference))/(2*h)
    return result


def point_constraint(xyz,masses,frequency=250):
    """Restrain a ball's normal displacement relative to three parent points.

    Only one point belongs to the child body, so the child remains free to rotate
    about it. Choose broad torque arms rather than nearly singular local edges.
    """
    xyz=np.asarray(xyz,float);masses=np.asarray(masses,float);last=len(xyz)-1
    candidates=[]
    for a,b,c in itertools.permutations(range(last),3):
        axis=xyz[c]-xyz[b];u=xyz[a]-xyz[b];w=xyz[last]-xyz[c]
        if min(np.linalg.norm(axis),np.linalg.norm(u),np.linalg.norm(w))<1e-6:continue
        arm1=np.linalg.norm(np.cross(u,axis))/np.linalg.norm(axis)
        arm2=np.linalg.norm(np.cross(w,axis))/np.linalg.norm(axis)
        candidates.append((min(arm1,arm2),[a,b,c,last]))
    if not candidates:raise ValueError('Spherical point constraint lacks separated parent points')
    lever,ids=max(candidates,key=lambda v:v[0])
    if lever<.01:raise ValueError('Spherical point constraint torque arm is too short')
    g=gradient(xyz[ids]);inverse=float(np.sum(g*g/masses[ids,None]))
    spring=(2*math.pi*frequency)**2/inverse
    damping=.2*math.sqrt(spring/inverse)
    return ids,spring,damping


def reinforce(xyz,edges,masses,frequency=400,angular=True,damping_budget=2.,priority_nodes=(),priority=1.):
    if not math.isfinite(priority) or not 1<=priority<=16:
        raise ValueError('Rigid loaded-node priority must be finite and between 1 and 16')
    if any(i<0 or i>=len(xyz) for i in priority_nodes):raise ValueError('Invalid rigid priority node')
    if not math.isfinite(damping_budget) or not 2<=damping_budget<=3.2:
        raise ValueError('Internal rigidity timestep budget must be finite and between 2 and 3.2')
    # A broad reference triangle avoids using adjacent tessellation vertices.
    pairs=np.array(list(itertools.combinations(range(len(xyz)),2)))
    def maximum(values):
        values=np.asarray(values)
        return np.flatnonzero(np.isclose(values,values.max(),rtol=1e-8,atol=1e-12))
    bases=[];basis_keys=set();bars=[];vectors=[];seen=set()
    def add_basis(first,second):
        line=xyz[second]-xyz[first]
        for third in maximum(np.linalg.norm(np.cross(line,xyz-xyz[first]),axis=1)):
            key=tuple(sorted((int(first),int(second),int(third))))
            if len(set(key))==3 and key not in basis_keys:basis_keys.add(key);bases.append(list(key))
    for i in maximum(np.linalg.norm(xyz[pairs[:,0]]-xyz[pairs[:,1]],axis=1)):add_basis(*pairs[i])
    for axis in range(3):
        for first,second in itertools.product(maximum(-xyz[:,axis]),maximum(xyz[:,axis])):
            if first!=second:add_basis(first,second)
    minimum_lever=np.linalg.norm(np.ptp(xyz,axis=0))*.04
    # Small mechanisms admit all four-point candidates cheaply. Three broad
    # reference planes alone left weak deformation modes around 100 Hz while
    # consuming the full 400 Hz maximum. Diverse angular load paths can stiffen
    # those modes without raising the maximum or changing the CAD mass moments.
    candidates_by_group=(itertools.permutations(ids) for ids in itertools.combinations(range(len(xyz)),4)) if len(xyz)<=12 else (
        ([first,second,third,d] for first,second,third in itertools.permutations(basis))
        for basis,d in itertools.product(bases,range(len(xyz))) if d not in basis)
    for group in candidates_by_group if angular else ():
        candidates=[]
        for first,second,third,d in group:
            u=xyz[first]-xyz[second];axis=xyz[third]-xyz[second];w=xyz[d]-xyz[third]
            lu=np.linalg.norm(u);la=np.linalg.norm(axis);lw=np.linalg.norm(w)
            if min(lu,la,lw)<1e-7:continue
            s1=np.linalg.norm(np.cross(u,axis))/(lu*la);s2=np.linalg.norm(np.cross(w,axis))/(lw*la)
            if min(lu*s1,lw*s2)<minimum_lever:continue
            candidates.append((min(s1,s2),[first,second,third,d]))
        if not candidates:continue
        quality=max(v[0] for v in candidates)
        if quality<.4:continue
        # Equivalent lever choices must not depend on node/triangulator order.
        # Retain tied hinges; swapping either endpoint pair only changes the
        # gradient sign, so keep one representative of each angular energy.
        for score,(a,b,c,d) in candidates:
            if not np.isclose(score,quality,rtol=1e-8,atol=1e-12):continue
            key=min((a,b,c,d),(d,b,c,a),(a,c,b,d),(d,c,b,a))
            if key in seen:continue
            # Canonicalize the energy only for deduplication. Its canonical
            # ordering can put a lever almost parallel to the axis, undoing
            # the geometry screening above. Emit the screened ordering.
            seen.add(key);ids=[a,b,c,d]
            col=np.zeros((len(xyz),3));col[ids]=gradient(xyz[ids])
            bars.append(ids);vectors.append(col.ravel())
    axial,_,_=axial_columns(xyz,edges)
    if not angular and np.linalg.matrix_rank(axial,tol=1e-8)!=3*len(xyz)-6:
        raise ValueError('Axial rigid solid has an internal mechanism; use angular reinforcement for flat structures')
    angular=np.array(vectors).T if vectors else np.zeros((3*len(xyz),0))
    columns=np.hstack((axial,angular));weighted=columns/np.repeat(np.sqrt(masses),3)[:,None]
    inverse_inertia=np.sum(weighted**2,axis=0)
    # Equal spring constants over-stiffen some modes while leaving a thin
    # upright's weak directions compliant. Fit a positive combination of the
    # actual axial/angular constraints to an isotropic deformational operator,
    # excluding the six rigid motions. This is a rigid-template approximation,
    # not a material-modulus calibration.
    u,s,_=np.linalg.svd(weighted,full_matrices=False)
    retained=u[:,s>s[0]*1e-6];target=retained@retained.T
    if priority!=1 and len(priority_nodes):
        # Project the external-site objective into the same deformational
        # subspace. Rigid translations/rotations remain unpenalized. This only
        # reallocates the existing positive stiffness budget; geometry, masses
        # and available internal constraints are unchanged.
        weights=np.ones(len(xyz));weights[list(priority_nodes)]=priority
        target=(target*np.repeat(weights,3))@target
    unit=weighted/np.sqrt(inverse_inertia)
    design=(unit[:,None,:]*unit[None,:,:]).reshape((len(weighted)**2,-1))
    # The operator fit alone can have many coefficient solutions. A small
    # strictly convex penalty gives one solution, including damping derived
    # from those coefficients, independent of the order of equivalent columns.
    penalty=1e-4
    coefficients,_=nnls(np.vstack((design,np.sqrt(penalty)*np.eye(design.shape[1]))),
                       np.r_[target.ravel(),np.zeros(design.shape[1])],maxiter=20*design.shape[1])
    # Zero NNLS columns add cost and redundant damping without useful rigidity.
    # Keep every axial edge; retain only angular columns used by the positive fit.
    active=np.r_[np.ones(len(edges),dtype=bool),coefficients[len(edges):]>1e-3]
    bars=[ids for ids,keep in zip(bars,active[len(edges):]) if keep]
    weighted=weighted[:,active];inverse_inertia=inverse_inertia[active];coefficients=coefficients[active]
    springs=np.maximum(coefficients,1e-3)*(2*math.pi*frequency)**2/inverse_inertia
    high=np.linalg.eigvalsh((weighted*springs)@weighted.T)[-1]
    springs*=min(1,(2*math.pi*frequency)**2/high)
    damping=reduced_mass_damping(springs[:len(edges)],masses,edges,.5)
    torque_damping=.25*np.sqrt(springs[len(edges):]/inverse_inertia[len(edges):])
    # A stiffness-only cap can still be unstable when many individually damped
    # constraints meet at a small node. Budget stiffness AND damping at the
    # standard 0.5 ms physics step; reserve half the explicit stability bound
    # for joints and the generated pressure-wheel graph attached later.
    dt=.0005;combined=np.r_[damping,torque_damping]
    stiffness_bound=dt*dt*np.linalg.eigvalsh((weighted*springs)@weighted.T)[-1]
    damping_bound=2*dt*np.linalg.eigvalsh((weighted*combined)@weighted.T)[-1]
    factor=min(1,max(0,damping_budget-stiffness_bound)/max(damping_bound,1e-12))
    damping*=factor;torque_damping*=factor
    return springs[:len(edges)],damping,[(ids,float(k),float(c)) for ids,k,c in zip(bars,springs[len(edges):],torque_damping)]
