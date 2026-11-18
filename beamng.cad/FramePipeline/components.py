"""CAD-owned component prototypes, named mounts and numerical screening.

Panel/bulk stiffness is explicitly provisional. Only the selected frame artifact
has CAD-reference calibration. No tube-centerline assumptions are used here.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
from scipy.spatial import ConvexHull, Delaunay, cKDTree
from scipy.optimize import linprog

HERE=Path(__file__).resolve().parent
for candidate in (HERE/'calibration/Test Harness', HERE.parents[1]/'dependencies/cad-calibration/Test Harness'):
    if candidate.is_dir(): sys.path.insert(0,str(candidate));break
from frame_harness.cad import Body, audit_body, volume_properties
from frame_harness.calibration import fit_masses
from frame_harness.projection import axial_columns, modal_frequencies, project_springs, reduced_mass_damping
from frame_harness.build import node_table, beam_table
from prepare_frame import read_stl, write_dae
from appearance_textures import mesh_uvs


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def fingerprint(value):
    # Re-exporting unchanged CAD to a fresh directory must not invalidate a
    # build. Its actual mesh/material contents are checked separately.
    model=copy.deepcopy({k:v for k,v in value.items() if k not in ('LastBuildReceipt','PhysicsBuildReceipt')})
    for component in model.get('Components',[]):
        for key in list(component):
            if key=='GeometryDirectory' or key.startswith('Appearance'):component.pop(key,None)
    workspace=model.get('JointWorkspace') or {}
    for key in ('ScanStamp','ScanHash'):workspace.pop(key,None)
    for member in workspace.get('Members',[]):member.pop('GeometryDirectory',None)
    return hashlib.sha256(json.dumps(model,sort_keys=True,allow_nan=False).encode()).hexdigest()


def sheet_moments(triangles,thickness,density,native_area=None):
    """Uniform lamina with symmetric physical thickness; independent of winding."""
    triangles=np.asarray(triangles,float)
    if not np.isfinite(triangles).all():raise ValueError('Surface contains nonfinite coordinates')
    cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);length=np.linalg.norm(cross,axis=1)
    if np.any(length<=1e-15):raise ValueError('Surface contains degenerate triangles')
    area=length.sum()/2;weights=length/length.sum();normal=cross/length[:,None]
    target=float(native_area) if native_area is not None else area
    if not math.isfinite(target) or target<=0 or abs(target/area-1)>.01:raise ValueError('Surface tessellation area differs from CAD by more than 1%')
    # Work about a nearby origin to avoid subtracting large world-coordinate moments.
    origin=triangles.reshape(-1,3).mean(axis=0);p=triangles-origin;total=p.sum(axis=1)
    center=weights@total/3
    second=np.einsum('n,nki,nkj->ij',weights,p,p)/12+np.einsum('n,ni,nj->ij',weights,total,total)/12
    covariance=second-np.outer(center,center)+thickness**2/12*np.einsum('n,ni,nj->ij',weights,normal,normal)
    mass=target*thickness*density;inertia=mass*(np.trace(covariance)*np.eye(3)-covariance)
    return mass,center+origin,inertia,target


def native_moments(record,mass,triangles):
    """Exact native CAD moments, transformed from part to BeamNG coordinates.

    SOLIDWORKS returns products of inertia; the inertia tensor uses their
    negatives. Display tessellation supplies appearance/collision geometry,
    and is never substituted for the native volume or material distribution.
    """
    raw=np.asarray(record['NativeUnitDensityProperties'],float)
    axes=np.asarray(record['NativeAxesAssembly'],float);center=np.asarray(record['NativeCenterAssembly'],float)
    if raw.shape!=(12,) or axes.shape!=(3,3) or center.shape!=(3,) or not np.isfinite(raw).all() or not np.isfinite(axes).all() or not np.isfinite(center).all():
        raise ValueError('Invalid native CAD mass properties')
    if raw[3]<=0 or raw[5]<=0 or not np.allclose(axes@axes.T,np.eye(3),atol=1e-7,rtol=0):raise ValueError('Invalid native volume/area or nonrigid component transform')
    conversion=np.array([[1,0,0],[0,0,-1],[0,1,0]]);rotation=conversion@axes.T;center=conversion@center
    tensor=np.array([[raw[6],-raw[9],-raw[10]],[-raw[9],raw[7],-raw[11]],[-raw[10],-raw[11],raw[8]]])
    tensor=rotation@tensor@rotation.T/raw[5]
    eigen=np.linalg.eigvalsh(tensor)
    if eigen[0]<=0 or eigen[-1]>sum(eigen[:2])+max(eigen[-1]*1e-7,1e-12):raise ValueError('Nonphysical native CAD inertia tensor')
    bounds=np.asarray(triangles).reshape(-1,3)
    if np.any(center<bounds.min(axis=0)-.001) or np.any(center>bounds.max(axis=0)+.001):raise ValueError('Native CAD COM differs from the exported mesh coordinate system')
    return center,tensor*mass


def read_geometry(component):
    policy=component.get('MassPolicy') or 'cad'
    if policy not in ('cad','custom','exclude'):raise ValueError('Unknown mass policy')
    root=Path(component['GeometryDirectory']).resolve()
    data=json.loads((root/'geometry.json').read_text(encoding='utf-8-sig'))
    meshes=[];moments=[]
    for record in data['Meshes']:
        path=(root/record['File']).resolve()
        if path.parent!=root:raise ValueError('Component mesh escapes geometry directory')
        triangles=np.asarray(read_stl(path,'X-ZY'))
        uvs=mesh_uvs(record,triangles)
        if uvs is not None:record=record | {'TextureCoordinates':uvs}
        if record.get('BodyKind')=='surface':
            mode=component.get('SurfaceMassMode') or 'thickness'
            if mode not in ('thickness','ignore'):raise ValueError('Choose how surface bodies contribute to weight')
            thickness=component.get('Thickness') or 0.;density=record.get('DensityKgM3') or 0.
            if mode=='thickness' and policy=='cad':
                if not math.isfinite(thickness) or thickness<=0:raise ValueError(record['Body']+': enter Surface thickness mm, or choose Exclude surface mass')
                if not math.isfinite(density) or density<=0:raise ValueError(record['Body']+': assign a SolidWorks material with positive density, or exclude surface mass')
            elif policy=='custom':thickness=max(float(thickness),1e-6);density=1.
            else:thickness=0.;density=0.
            if record.get('NativeUnitDensityProperties') is not None:
                area=float(record['NativeUnitDensityProperties'][3]);mass=area*thickness*density
                center,inertia=native_moments(record,mass,triangles)
                # Native sheet inertia is a lamina. Add symmetric thickness
                # about each surface normal, retaining exact native area/COM.
                cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);length=np.linalg.norm(cross,axis=1)
                valid=length>1e-15
                if not np.any(valid):raise ValueError('Surface contains no nondegenerate triangles')
                normal=cross[valid]/length[valid,None];weights=length[valid]/length[valid].sum()
                covariance=thickness**2/12*np.einsum('n,ni,nj->ij',weights,normal,normal)
                inertia+=mass*(np.trace(covariance)*np.eye(3)-covariance)
            else:
                mass,center,inertia,area=sheet_moments(triangles,thickness,density,record.get('SurfaceAreaM2') if mode=='thickness' else None)
            record=record|{'mass_contribution':dict(kind='surface',mode=mode,mass_kg=mass,area_m2=area,thickness_m=thickness,density_kg_m3=density)}
        else:
            if record.get('NativeUnitDensityProperties') is not None:
                mass=record.get('MassKg') if policy=='cad' else record['NativeUnitDensityProperties'][3] if policy=='custom' else 0.
                if policy!='exclude' and (not mass or not math.isfinite(mass) or mass<=0):raise ValueError(record['Body']+': assign a SolidWorks material and export again')
                center,inertia=native_moments(record,mass,triangles)
            else:
                body=Body(record['Id'],triangles.reshape(-1,3),np.arange(triangles.size//3).reshape(-1,3))
                _,audit=audit_body(body)
                if not audit.get('valid'):raise ValueError(record['Body']+': CAD volume is not closed and consistently oriented')
                mass=record.get('MassKg') if policy=='cad' else audit['volume_m3'] if policy=='custom' else 0.
                if policy!='exclude' and (not mass or not math.isfinite(mass) or mass<=0):raise ValueError(record['Body']+': assign a SolidWorks material and export again')
                center=np.array(audit['center_m']);inertia=mass/audit['volume_m3']*np.array(audit['inertia_per_density'])
            record=record|{'mass_contribution':dict(kind='solid',mass_kg=mass)}
        meshes.append((record,triangles));moments.append((mass,center,inertia))
    if not meshes:raise ValueError('Component has no bodies')
    mass=sum(m for m,_,_ in moments)
    center=sum(m*c for m,c,_ in moments)/mass if mass else np.concatenate([t.reshape(-1,3) for _,t in meshes]).mean(axis=0)
    inertia=np.zeros((3,3))
    for m,c,i in moments:
        r=c-center;inertia+=i+m*(np.dot(r,r)*np.eye(3)-np.outer(r,r))
    if policy=='custom':
        data=data|{'custom_mass_measure':mass}
        custom=float(component.get('CustomMassKg') or 0)
        if not math.isfinite(custom) or custom<=0 or mass<=0:raise ValueError('Custom mass must be positive and geometry must define a mass distribution')
        scale=custom/mass;mass=custom;inertia*=scale
        for record,_ in meshes:record['mass_contribution']['mass_kg']*=scale
    if component.get('_VisualMass'):
        from component_representation import combine
        mass,center,inertia=combine([(mass,center,inertia)]+[(v['mass'],v['center'],v['inertia']) for v in component['_VisualMass']])
    return meshes,(mass,center,inertia),data


def suggest(triangles,mass):
    points=np.unique(np.asarray(triangles).reshape(-1,3),axis=0)
    center=points.mean(axis=0);_,_,axes=np.linalg.svd(points-center,full_matrices=False)
    if np.linalg.det(axes)<0:axes[-1]*=-1
    local=(points-center)@axes.T;extent=np.ptp(local,axis=0);diagonal=float(np.linalg.norm(extent))
    if diagonal<1e-5:raise ValueError('Component is too small or degenerate')
    thin=extent[-1]<extent[1]*.08
    # Keep defaults modest; the editor exposes the physical spacing and alpha.
    spacing=max(float(extent[0]/6),.02)
    alpha=max(diagonal/3,spacing)
    area=float(np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1).sum()/2)
    return dict(version=1,classification='panel' if thin else 'bulk',method='panel_grid' if thin else 'alpha_wrap',
                spacing_m=spacing,alpha_m=alpha,offset_m=max(diagonal*.001,.0005),
                principal_extent_m=extent.tolist(),center_m=center.tolist(),axes=axes.tolist(),
                estimated_collision_triangles=int(max(2,area/(spacing**2)*2)),mass_kg=mass,
                assumptions=['Geometry-derived starting settings; preview before export.','Panel and bulk stiffness/damage remain provisional.'])


def write_off(path,points,faces):
    with Path(path).open('w',encoding='utf-8') as stream:
        stream.write(f'OFF\n{len(points)} {len(faces)} 0\n')
        for p in points:stream.write(' '.join(format(float(v),'.12g') for v in p)+'\n')
        for f in faces:stream.write(str(len(f))+' '+' '.join(map(str,f))+'\n')


def read_off(path):
    lines=[l.split('#')[0].strip() for l in Path(path).read_text().splitlines()];lines=[l for l in lines if l]
    if lines[0]!='OFF':raise ValueError('Invalid wrap output')
    nv,nf,_=map(int,lines[1].split());points=np.array([list(map(float,l.split())) for l in lines[2:2+nv]])
    faces=[]
    for line in lines[2+nv:2+nv+nf]:
        row=list(map(int,line.split()));faces.extend([row[1],row[i],row[i+1]] for i in range(2,row[0]))
    return points,np.array(faces,dtype=int)


def alpha_surface(triangles,alpha,offset,python,folder,automatic=False,automatic_offset=False):
    if not python or not Path(python).is_file():raise ValueError('Configure CGAL Python to generate bulk alpha wraps')
    points,inverse=np.unique(triangles.reshape(-1,3),axis=0,return_inverse=True)
    write_off(folder/'wrap-source.off',points,inverse.reshape(-1,3))
    # Reuse the exact bundled CGAL entry point without importing Blender.
    tree=ast.parse((HERE/'generation/AlphaWrap.py').read_text(encoding='utf-8-sig'))
    helper=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CGAL_HELPER' for t in n.targets))
    script=folder/'cgal-wrap.py';script.write_text(helper,encoding='utf-8')
    trials=[]
    for attempt in range(4 if automatic else 1):
        command=[str(python),str(script),str(folder/'wrap-source.off'),str(folder/'wrap.off'),str(alpha),str(offset)]
        subprocess.run(command,check=True,timeout=180)
        points,faces=read_off(folder/'wrap.off')
        trials.append(dict(alpha_m=alpha,offset_m=offset,nodes=len(points),triangles=len(faces)))
        if len(points)<=96 or not automatic:break
        if attempt<3:
            alpha*=1.5
            if automatic_offset:offset*=2
    write(folder/'wrap-estimation.json',dict(automatic=automatic,automatic_offset=automatic_offset,trials=trials,selected=trials[-1],target_surface_nodes=96,target_reached=len(points)<=96))
    if len(points)>240:raise ValueError(f'Wrap has {len(points)} nodes; increase alpha for a coarser bulk representation (limit 240)')
    return points,faces


def covered_triangle(triangle,source):
    """Subtract projected CAD triangles; any remaining area is a hole/outside.

    Centroid/edge sampling alone misses small openings inside a collider face.
    Pieces remain convex as each clip keeps one side of an edge.
    """
    def area(p):
        return abs(float(np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))))/2 if len(p)>2 else 0.
    def cross(a,b):return a[...,0]*b[...,1]-a[...,1]*b[...,0]
    def split(poly,a,b):
        distance=cross(b-a,poly-a);inside=[];outside=[]
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)];d=distance[i];e=distance[(i+1)%len(poly)]
            (inside if d>=0 else outside).append(p)
            if (d>=0)!=(e>=0):
                intersection=p+(q-p)*d/(d-e);inside.append(intersection);outside.append(intersection)
        return np.asarray(inside),np.asarray(outside)
    lo=triangle.min(axis=0);hi=triangle.max(axis=0)
    relevant=source[np.all(source.max(axis=1)>=lo,axis=1)&np.all(source.min(axis=1)<=hi,axis=1)]
    remaining=[triangle];tolerance=max(1e-14,area(triangle)*1e-9)
    for cover in relevant:
        if cross(cover[1]-cover[0],cover[2]-cover[0])<0:cover=cover[::-1]
        following=[]
        for piece in remaining:
            for i in range(3):
                if len(piece)<3:break
                piece,outside=split(piece,cover[i],cover[(i+1)%3])
                if area(outside)>tolerance:following.append(outside)
        remaining=following
        if not remaining:return True
        if len(remaining)>1000:raise ValueError('Panel outline is too complex for this spacing; split it into simpler components')
    return sum(area(p) for p in remaining)<=tolerance


def panel_surface(triangles,settings,spacing):
    center=np.array(settings['center_m']);axes=np.array(settings['axes'])
    local=(triangles-center)@axes.T;points=local.reshape(-1,3)
    lo=points.min(axis=0);hi=points.max(axis=0)
    if hi[2]-lo[2]>(hi[1]-lo[1])*.15:raise ValueError('This panel is too curved for the planar template; use the bulk template')
    outline=ConvexHull(points[:,:2]);boundary=points[outline.vertices,:2]
    xx=np.linspace(lo[0],hi[0],max(2,int(math.ceil((hi[0]-lo[0])/spacing))+1))
    yy=np.linspace(lo[1],hi[1],max(2,int(math.ceil((hi[1]-lo[1])/spacing))+1))
    if len(xx)*len(yy)>180:raise ValueError('Panel spacing is too fine (maximum 180 surface samples)')
    projected=local[:,:,:2]
    # Projected source triangles preserve holes; discard side faces of zero area.
    ab=projected[:,1]-projected[:,0];ac=projected[:,2]-projected[:,0]
    determinant=ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0];valid=abs(determinant)>1e-12
    projected=projected[valid];ab=ab[valid];ac=ac[valid];determinant=determinant[valid]
    def inside(p):
        ap=p-projected[:,0]
        u=(ap[:,0]*ac[:,1]-ap[:,1]*ac[:,0])/determinant
        v=(ab[:,0]*ap[:,1]-ab[:,1]*ap[:,0])/determinant
        return bool(np.any((u>=-1e-8)&(v>=-1e-8)&(u+v<=1+1e-8)))
    # PCA leaves grid corners a few ulps away from identical boundary points.
    # Exact np.unique retains both and Qhull drops one, leaving an unbound node.
    samples=[]
    for p in [*boundary,*itertools.product(xx,yy)]:
        if inside(p) and not any(np.linalg.norm(np.asarray(p)-q)<1e-8 for q in samples):samples.append(p)
    uv=np.asarray(samples)
    faces=[]
    for f in Delaunay(uv).simplices:
        q=uv[f]
        if inside(q.mean(axis=0)) and all(inside((q[i]+q[(i+1)%3])/2) for i in range(3)) and covered_triangle(q,projected):faces.append(f.tolist())
    if not faces:raise ValueError('No panel surface could be generated')
    p=np.column_stack((uv,np.full(len(uv),(lo[2]+hi[2])/2)))@axes+center
    # Separate sparse out-of-plane locators give the planar sheet a volumetric
    # graph. Their mass is fitted, not added to the CAD material mass.
    depth=max(spacing*.25,(hi[2]-lo[2])/2)
    helpers=np.array([p[f].mean(axis=0)+axes[2]*depth*side for f in faces[::max(1,len(faces)//4)] for side in (-1,1)])
    return np.vstack((p,helpers)),np.array(faces,dtype=int)


def expand(rows):
    defaults={}
    for row in rows[1:]:
        if isinstance(row,dict):defaults.update(row)
        else:
            options=defaults|(row[-1] if isinstance(row[-1],dict) else {})
            yield row[:-1] if isinstance(row[-1],dict) else row,options


def convex_surface(triangles):
    source=np.unique(np.asarray(triangles).reshape(-1,3),axis=0)
    hull=ConvexHull(source);points=source[hull.vertices];hull=ConvexHull(points);faces=hull.simplices.copy()
    normal=np.cross(points[faces[:,1]]-points[faces[:,0]],points[faces[:,2]]-points[faces[:,0]])
    flip=np.einsum('ij,ij->i',normal,hull.equations[:,:3])<0
    faces[flip]=faces[flip][:,[0,2,1]]
    return points,faces,float(hull.volume)


def exact_convex_solid(meshes):
    """An exact boundary shortcut, not a concavity-filling approximation."""
    if len(meshes)!=1 or meshes[0][0].get('BodyKind')=='surface':return None
    triangles=np.asarray(meshes[0][1]);points,faces,hull_volume=convex_surface(triangles)
    if len(points)>96:return None
    centered=triangles-triangles.reshape(-1,3).mean(axis=0)
    volume=abs(float(np.einsum('ij,ij->i',centered[:,0],np.cross(centered[:,1],centered[:,2])).sum()/6))
    if hull_volume<=0 or abs(volume/hull_volume-1)>1e-5:return None
    return points,faces


def component_masses(points,mass,center,inertia):
    masses,report=fit_masses(points,mass,center,inertia)
    if masses.min()>=mass/len(points)*.1:return masses,report
    # Thin CAD sheets cannot put substantial mass on their numerical depth
    # locators while matching every inertia entry exactly. Use a bounded 1%
    # tensor error, below the existing 5% acceptance limit, with exact mass/COM.
    # Maximize the least node weight instead of starving all surface/mount nodes.
    r=np.asarray(points)-center;x,y,z=r.T;count=len(points)
    moments=np.array([y*y+z*z,x*x+z*z,x*x+y*y,-x*y,-x*z,-y*z])
    target=np.r_[np.diag(inertia),inertia[0,1],inertia[0,2],inertia[1,2]]/mass
    tolerance=np.linalg.norm(inertia)/mass*.01/3
    result=linprog(np.r_[np.zeros(count),-1.],
        A_eq=np.column_stack((np.vstack((np.ones(count),r.T)),np.zeros(4))),b_eq=[1,0,0,0],
        A_ub=np.vstack((np.column_stack((-np.eye(count),np.ones(count))),np.column_stack((moments,np.zeros(6))),np.column_stack((-moments,np.zeros(6))))),
        b_ub=np.r_[np.zeros(count),target+tolerance,-target+tolerance],bounds=[(0,None)]*(count+1),method='highs')
    if not result.success or result.x[-1]*mass<=masses.min():return masses,report
    masses=result.x[:-1]*mass;actual_center=masses@points/mass;rr=points-actual_center
    actual=sum(m*(np.dot(p,p)*np.eye(3)-np.outer(p,p)) for m,p in zip(masses,rr))
    report.update(actual_mass_kg=float(sum(masses)),actual_center_m=actual_center.tolist(),center_error_m=float(np.linalg.norm(actual_center-center)),
                  actual_inertia_kg_m2=actual.tolist(),inertia_relative_error=float(np.linalg.norm(actual-inertia)/np.linalg.norm(inertia)),
                  minimum_node_mass_kg=float(masses.min()),maximum_minimum_mass_kg=float(masses.min()),
                  allocation_method='maximum minimum mass; exact mass/COM, bounded 1% inertia tensor error')
    report['accepted']=report['center_error_m']<=.005 and report['inertia_relative_error']<=.01+1e-9
    return masses,report


def generate_component(component,anchors,folder,cgal=None):
    if (component.get('SteeringAppearance') or {}).get('Enabled') and component.get('Method')!='rigid':
        raise ValueError('Steering animation preview requires the rigid representation')
    folder.mkdir(parents=True,exist_ok=False)
    meshes,moments,geometry=read_geometry(component);triangles=np.concatenate([t for _,t in meshes])
    settings=suggest(triangles,moments[0]);spacing=component.get('Spacing') or settings['spacing_m']
    contributions={r['Id']:r['mass_contribution'] for r,_ in meshes}
    from component_representation import visual,acknowledgement
    if moments[0]==0 and not visual(component):raise ValueError(component['Name']+': zero mass; explicitly select Visual only or supply mass')
    if visual(component):
        if moments[0]==0 and component.get('MassAcknowledgement')!=acknowledgement(component):raise ValueError('Acknowledge Visual only — mass excluded for this geometry')
        parent=component.get('VisualParentId')
        if not parent or parent==component['Id']:raise ValueError('Choose a physical parent for this visual-only component.')
        if anchors:raise ValueError('Visual-only parts follow their parent. Put mounting points on the physical parent, or choose Physical for independent mounts.')
        points,inverse=np.unique(triangles.reshape(-1,3),axis=0,return_inverse=True)
        write_off(folder/'preview.off',points,inverse.reshape(-1,3));write_dae(folder/'component.dae',meshes)
        part={'information':{'name':component['Name'],'authors':'BeamNG CAD'},'slotType':component['Id'],
              'nodes':[['id','posX','posY','posZ']],'beams':[['id1:','id2:']],
              'flexbodies':[['mesh','[group]:','nonFlexMaterials']]+[[r['Id'],[parent+'_visual_hosts'],[]] for r,_ in meshes]}
        report=dict(settings=settings,mass={'actual_mass_kg':moments[0],'accepted':True},mass_contributions=contributions,nodes=0,beams=0,collision_triangles=0,
                    visual_parent=parent,qualification='visual_only',limitations=['Skin follows its physical parent; no independent nodes, collision or breakaway. Any included mass belongs to that parent.'])
        write(folder/'report.json',report);write(folder/'component.jbeam',{component['Id']:part});return part,report
    if component.get('Method')=='rigid':
        from compact_rigid import generate
        from rigid_visuals import render
        part,report=generate(component,anchors,moments)
        allocation={row[0]:row[-1]['nodeWeight'] for row in part['nodes'][1:]}
        render_meshes,report['rigid_render']=render(component['Id'],part,{component['Id']:allocation},meshes,[r['Id'] for r,_ in meshes],component.get('SteeringAppearance'))
        write_dae(folder/'component.dae',render_meshes)
        write_off(folder/'preview.off',[r[1:4] for r in part['nodes'][1:]],[])
        report['mass_contributions']=contributions
        write(folder/'report.json',report);write(folder/'component.jbeam',{component['Id']:part})
        return part,report
    for value in (spacing,component.get('Alpha',0),component.get('WrapOffset',0)):
        if not math.isfinite(value) or value<0:raise ValueError('Geometry parameters must be finite and nonnegative')
    template=settings['classification'] if component['Template']=='auto' else component['Template']
    if template=='panel' and component.get('Method','auto')!='alpha_wrap':points,faces=panel_surface(triangles,settings,spacing)
    elif template=='bulk' or template=='panel':
        method=component.get('Method','auto')
        exact=exact_convex_solid(meshes) if method=='auto' else None
        if exact is not None:
            points,faces=exact
            settings['method']='exact_convex_solid'
            settings['wrap']=dict(selected_method='exact_convex_solid',reason='One closed CAD solid matches its convex volume within 0.001%; no alpha-wrap surface samples required',nodes=len(points),triangles=len(faces))
        elif method=='oriented_box':
            axes=np.asarray(settings['axes']);origin=np.asarray(settings['center_m']);local=(triangles.reshape(-1,3)-origin)@axes.T
            lo=local.min(axis=0);hi=local.max(axis=0)
            points=np.array(list(itertools.product(*zip(lo,hi))))@axes+origin
            hull=ConvexHull(points);faces=hull.simplices.copy()
            normals=np.cross(points[faces[:,1]]-points[faces[:,0]],points[faces[:,2]]-points[faces[:,0]])
            flip=np.einsum('ij,ij->i',normals,hull.equations[:,:3])<0;faces[flip]=faces[flip][:,[0,2,1]]
            settings['method']='oriented_box'
            settings['wrap']=dict(selected_method='oriented_box',reason='Explicit coarse collision envelope; CAD visual meshes and physical moments retained',nodes=8,triangles=12)
        elif method in ('auto','alpha_wrap'):
            points,faces=alpha_surface(triangles,component.get('Alpha') or settings['alpha_m'],component.get('WrapOffset') or settings['offset_m'],cgal,folder,automatic=not component.get('Alpha'),automatic_offset=not component.get('WrapOffset'))
            settings['wrap']=json.loads((folder/'wrap-estimation.json').read_text())
        elif method=='convex':
            points,faces,_=convex_surface(triangles)
            if len(points)>240:raise ValueError('Convex envelope has too many nodes; use alpha wrap')
        else:raise ValueError('Unsupported component generation method')
        # Interior samples allow matching inertia instead of placing all mass on
        # the wrap boundary. These remain non-colliding numerical structure.
        center=np.array(moments[1]);points=np.vstack((points,center))
        axes=np.array(settings['axes']);extent=np.array(settings['principal_extent_m'])
        points=np.vstack((points,[center+axis*length*.35*sign for axis,length in zip(axes,extent) for sign in (-1,1)]))
    else:raise ValueError('Choose panel or bulk; suspension templates are specified separately')
    collision_nodes=set(map(int,np.asarray(faces).reshape(-1)))
    base_count=len(points);names=[component['Id']+'_n'+str(i) for i in range(base_count)]
    for anchor in sorted(anchors,key=lambda a:a['Id']):
        if anchor.get('Status')!='resolved':raise ValueError(anchor['Name']+': mounting reference needs repair')
        p=np.asarray(anchor['Position'],float)
        # A dedicated anchor may be close to a surface node, but must not be coincident.
        if np.min(np.linalg.norm(points-p,axis=1))<1e-7:
            index=int(np.argmin(np.linalg.norm(points-p,axis=1)))
            if '_mount_' in names[index]:raise ValueError('Two anchors occupy the same point; reuse the existing anchor')
            names[index]=component['Id']+'_mount_'+anchor['Id']
        else:points=np.vstack((points,p));names.append(component['Id']+'_mount_'+anchor['Id'])
    mass,center,inertia=moments;masses,fit=component_masses(points,mass,center,inertia)
    if not fit['accepted']:raise ValueError(component['Name']+': graph cannot fit CAD mass/COM/inertia; adjust representation')
    edges=set()
    for cell in Delaunay(points).simplices:
        edges.update(tuple(sorted(pair)) for pair in itertools.combinations(map(int,cell),2))
    edges=sorted(e for e in edges if np.linalg.norm(points[e[0]]-points[e[1]])>1e-7)
    columns,_,_=axial_columns(points,edges)
    rank=int(np.linalg.matrix_rank(columns,tol=1e-8))
    if rank!=3*len(points)-6:raise ValueError(component['Name']+': unsupported internal mechanism')
    springs=project_springs(columns,edges,masses,np.full(len(edges),150000.),180,'local_capped')
    damping=reduced_mass_damping(springs,masses,edges,.6)
    torsions=[];bending=None
    material_path=Path(component['GeometryDirectory'])/'material-snapshot.json'
    provisional=component.get('ProvisionalElastic')
    if template=='panel' and (material_path.is_file() or provisional):
        from frame_harness.materials import load_snapshot
        from panel_bending import hinges,screen
        if provisional:
            young=float(provisional['young_pa']);poisson=float(provisional['poisson'])
            if not math.isfinite(young) or young<=0 or not math.isfinite(poisson) or not -1<poisson<.5 or not provisional.get('reason'):raise ValueError('Provisional panel elasticity needs valid properties and an explicit reason')
            properties=[dict(young_pa=young,poisson=poisson)]
        else:
            materials=load_snapshot(material_path,[r['Id'] for r,_ in meshes])
            properties=[materials[r['Id']] for r,_ in meshes]
        # This planar template represents one uniform sheet. Mixed stacks need
        # a laminate model, rather than silently averaging different stiffnesses.
        if len({(v['young_pa'],v['poisson']) for v in properties})!=1:raise ValueError('Split panels with different elastic materials into separate components')
        thickness=float(component.get('Thickness') or settings['principal_extent_m'][2])
        if thickness<=0:raise ValueError('Panel bending needs a positive physical thickness')
        young=properties[0]['young_pa'];poisson=properties[0]['poisson'];rigidity=young*thickness**3/(12*(1-poisson**2))
        torsions=hinges(points,faces,masses,rigidity)
        springs,damping,screening=screen(points,masses,edges,springs,damping,torsions)
        bending=dict(model='Discrete isotropic plate hinges; provisional, not a calibrated panel response',
                     young_pa=young,poisson=poisson,thickness_m=thickness,rigidity_nm=rigidity,hinges=len(torsions),**screening)
        if provisional:bending['provisional_material']=provisional
    group=component['Id']+'_structure'
    nodes=[['id','posX','posY','posZ']]+[[name,*p.tolist(),{'nodeWeight':float(m),'collision':i in collision_nodes,'selfCollision':False,'group':[group],'nodeMaterial':'|NM_METAL'}] for i,(name,p,m) in enumerate(zip(names,points,masses))]
    beams=[['id1:','id2:']]+[[names[a],names[b],{'beamSpring':float(k),'beamDamp':float(d),'beamDeform':1e30,'beamStrength':1e30,'breakGroup':'','beamPrecompression':1}] for (a,b),k,d in zip(edges,springs,damping)]
    part={'information':{'name':component['Name'],'authors':'BeamNG CAD'},'slotType':component['Id'],'nodes':nodes,'beams':beams,
          'triangles':[['id1:','id2:','id3:']]+[[names[i] for i in f] for f in faces],
          'flexbodies':[['mesh','[group]:','nonFlexMaterials']]+[[record['Id'],[group],[]] for record,_ in meshes]}
    if torsions:part['torsionbars']=[['id1:','id2:','id3:','id4:']]+[[*[names[i] for i in ids],options] for ids,options in torsions]
    write_dae(folder/'component.dae',meshes)
    write_off(folder/'preview.off',points,faces.tolist()+[[a,b] for a,b in edges])
    report=dict(settings=settings,mass=fit,mass_contributions=contributions,nodes=len(points),beams=len(edges),collision_triangles=len(faces),rank=rank,
                max_frequency_hz=float(modal_frequencies(columns,masses,springs)[-1]),qualification='provisional',
                limitations=['CAD mass fitted. Template stiffness and rupture are not material calibrated.'])
    if bending:report['bending']=bending;report['max_frequency_hz']=bending['highest_linear_frequency_hz']
    write(folder/'report.json',report);write(folder/'component.jbeam',{component['Id']:part})
    return part,report


def bind_weightless_visuals(parts,reports):
    groups=set()
    for owner,report in reports.items():
        if report.get('qualification')!='visual_only':continue
        parent=report['visual_parent']
        if parent not in parts or not node_table(parts[parent]):raise ValueError('Weightless visual '+owner+' needs a physical parent with nodes; visual-only chains are not supported')
        group=parent+'_visual_hosts';groups.add(group)
        rows=[['id','posX','posY','posZ']]
        for name,node in node_table(parts[parent]).items():
            options=copy.deepcopy(node['options']);existing=options.get('group',[])
            if isinstance(existing,str):existing=[existing]
            options['group']=list(dict.fromkeys([*existing,group]));rows.append([name,*node['position'],options])
        parts[parent]['nodes']=rows
    return groups


def attach(parts,anchors,connections,project_assembly=False):
    by_anchor={a['Id']:a for a in anchors};by_node={};owners={}
    for owner,part in parts.items():
        for name,node in node_table(part).items():
            if name in by_node:raise ValueError('Duplicate component node '+name)
            by_node[name]=node;owners[name]=owner
    groups=[]
    for connection in connections:
        a=by_anchor[connection['AnchorA']];b=by_anchor[connection['AnchorB']]
        if a['ComponentId']==b['ComponentId']:raise ValueError('Mount must connect different components')
        if a.get('Status')!='resolved' or b.get('Status')!='resolved':raise ValueError('Repair mounting references before building')
        pa=np.array(a['Position']);pb=np.array(b['Position'])
        target=a['ComponentId']+'_mount_'+a['Id']
        # Calibrated frame graphs are immutable. The mount patch selects a local
        # spanning support set there; child components own dedicated mount nodes.
        source=b['ComponentId']+'_mount_'+b['Id']
        if source not in by_node:
            a,b=b,a;pa,pb=pb,pa;source=b['ComponentId']+'_mount_'+b['Id']
        if source not in by_node:raise ValueError('One side of a mount needs a generated component anchor')
        candidates=sorted((n for n in by_node if owners[n]==a['ComponentId']),key=lambda n:np.linalg.norm(np.array(by_node[n]['position'])-pa))
        candidates=[n for n in candidates if np.linalg.norm(np.array(by_node[n]['position'])-pb)>1e-5][:16]
        supports=[];best=-1.;conditioning=0.
        # Three merely independent directions can be almost parallel and make
        # a nominally fixed accessory sway. Prefer a well-spread local support
        # patch; report its extent instead of hiding the geometric approximation.
        for trial in itertools.combinations(candidates,3):
            vectors=np.array([np.array(by_node[n]['position'])-pb for n in trial])
            unit=vectors/np.linalg.norm(vectors,axis=1)[:,None]
            smallest=float(np.linalg.svd(unit,compute_uv=False)[-1])
            distance=max(float(np.linalg.norm(np.array(by_node[n]['position'])-pa)) for n in trial)
            score=smallest/(1+distance/.2)
            if score>best:best=score;supports=list(trial);conditioning=smallest
        if conditioning<.05:raise ValueError(connection['Name']+': no well-conditioned local support patch; revise the mounting point or frame representation')
        spring=float(connection['Spring']);damping=float(connection['Damping']);strength=float(connection['Strength'])
        if not all(math.isfinite(v) and v>=0 for v in (spring,damping,strength)) or strength==0:raise ValueError('Mount parameters must be finite, with positive strength (zero stiffness/damping selects automatic)')
        kind=connection['Template']
        if kind not in ('fixed','breakable_fastener'):raise ValueError('Unsupported connection template')
        from attachment_contract import release_group
        group=release_group(connection,b['ComponentId'])
        edges=[]
        for n in supports:
            ma=by_node[n]['options']['nodeWeight'];mb=by_node[source]['options']['nodeWeight'];reduced=ma*mb/(ma+mb)
            stiffness=spring or min(120000.,min(ma,mb)*(2*math.pi*120)**2/6)
            damp=damping or 1.2*math.sqrt(stiffness*reduced)
            options={'beamSpring':stiffness,'beamDamp':damp,'beamDeform':1e30,'beamStrength':strength if group else 1e30,
                     'breakGroup':group,'breakGroupType':0,'disableMeshBreaking':True,'disableTriangleBreaking':True,'beamPrecompression':1}
            parts[b['ComponentId']]['beams'].append([source,n,options]);edges.append([source,n])
        groups.append(dict(id=connection['Id'],name=connection['Name'],group=group,edges=edges,parent=a['ComponentId'],child=b['ComponentId'],support_direction_minimum_singular_value=conditioning,support_distance_m=max(float(np.linalg.norm(np.array(by_node[n]['position'])-pa)) for n in supports)))
    names=list(by_node);indices={n:i for i,n in enumerate(names)}
    all_beams=[b for part in parts.values() for b in beam_table(part)]
    endpoints=[[indices[b['a']],indices[b['b']]] for b in all_beams]
    xyz=np.array([by_node[n]['position'] for n in names]);masses=np.array([by_node[n]['options']['nodeWeight'] for n in names])
    columns,_,_=axial_columns(xyz,endpoints);rank=int(np.linalg.matrix_rank(columns,tol=1e-8))
    if rank!=3*len(xyz)-6:raise ValueError('Mounted assembly has unconstrained motion; use separated mounting points')
    frequencies=modal_frequencies(columns,masses,[b['spring'] for b in all_beams])
    scale=min(1.,(350/frequencies[-1])**2)
    if frequencies[-1]>350.01:
        # Adding a spring to a frame already at its spectral cap necessarily
        # raises the cap. A *reported* <=1% numerical projection belongs to the
        # new, diagnostic assembly, never to the original calibrated artifact.
        if not project_assembly or scale<.99:
            raise ValueError(f'Mounts exceed the 350 Hz numerical limit ({frequencies[-1]:.1f} Hz); reduce connection stiffness or revise the layout')
        for part in parts.values():
            rows=[]
            for row,options in expand(part['beams']):
                rows.append([*row[:2],options|{'beamSpring':options['beamSpring']*scale,'beamDamp':options['beamDamp']*math.sqrt(scale)}])
            part['beams']=[['id1:','id2:']]+rows
        frequencies=modal_frequencies(columns,masses,[b['spring']*scale for b in all_beams])
    else:scale=1.
    return groups,dict(rank=rank,expected_rank=3*len(xyz)-6,maximum_frequency_hz=float(frequencies[-1]),assembly_spring_scale=scale,
                       qualification='diagnostic assembly; source frame calibration does not qualify attached components')
