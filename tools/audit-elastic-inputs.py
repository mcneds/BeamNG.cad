"""Audit prerequisites for an independent CAD elastic reference; never infer stiffness from JBeam.

Open surface bodies can be valid shell inputs, but a mass-thickness setting is
not evidence of a midsurface or its physical wall thickness. Closed tessellation
is also insufficient to establish joints, contact or mesh convergence.
"""
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from frame_harness.cad import Body,welded,section_loops,polygon_properties
from components import read_geometry


def topology(triangles,tolerance):
    triangles=np.asarray(triangles,float)
    if triangles.ndim!=3 or triangles.shape[1:]!=(3,3) or not len(triangles) or not np.isfinite(triangles).all():
        raise ValueError('Finite triangle geometry required')
    b=welded(Body('audit',triangles.reshape(-1,3),np.arange(triangles.size//3).reshape(-1,3)),tolerance)
    f=b.faces
    directed=np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]])
    _,inverse,counts=np.unique(np.sort(directed,axis=1),axis=0,return_inverse=True,return_counts=True)
    balance=np.bincount(inverse,weights=np.where(directed[:,0]<directed[:,1],1,-1))
    _,duplicate_counts=np.unique(np.sort(f,axis=1),axis=0,return_counts=True)
    return dict(weld_tolerance_m=tolerance,vertices=len(b.vertices),triangles=len(f),
        removed_degenerate_triangles=len(triangles)-len(f),boundary_edges=int(np.sum(counts==1)),
        nonmanifold_edges=int(np.sum(counts>2)),inconsistent_oriented_edges=int(np.sum((counts==2)&(balance!=0))),
        duplicate_triangles=int(np.sum(duplicate_counts-1)),
        closed_oriented_surface=bool(len(f) and np.all(counts==2) and np.all(balance==0) and np.all(duplicate_counts==1)))


def section_probe(triangles):
    """Record transverse contours of a slender surface, without inventing a bore."""
    t=np.asarray(triangles,float)
    b=welded(Body('section',t.reshape(-1,3),np.arange(t.size//3).reshape(-1,3)),1e-7)
    center=b.vertices.mean(0);_,singular,axes=np.linalg.svd(b.vertices-center,full_matrices=False)
    if singular[1]<=1e-12 or singular[0]<3*singular[1]:return dict(status='not_a_clear_slender_member')
    along=(b.vertices-center)@axes[0];length=float(np.ptp(along));samples=[]
    for fraction in (.35,.5,.65):
        try:
            loops=section_loops(b,center+axes[0]*(along.min()+fraction*length),axes)
            samples.append(dict(fraction=fraction,contours=len(loops),
                enclosed_contour_areas_m2=[float(polygon_properties([p])[0]) for p in loops]))
        except ValueError as exc:samples.append(dict(fraction=fraction,error=str(exc)))
    return dict(status='measured_contours_only',projected_length_m=length,samples=samples,
        scope='A single contour does not distinguish an outer skin, midsurface or solid. No inferred wall thickness, material area or stiffness.')


def audit(project_path,roles):
    project=json.loads(project_path.read_bytes());report=dict(scope=__doc__,project=str(project_path.resolve()),
        project_sha256=hashlib.sha256(project_path.read_bytes()).hexdigest(),qualified=False,components={})
    for role in roles:
        selected=[c for c in project['Components'] if c.get('MvpRole')==role]
        if len(selected)!=1:raise ValueError('One component required for '+role)
        component=selected[0];folder=Path(component['GeometryDirectory']);meshes,moments,_=read_geometry(component)
        material_path=folder/'material-snapshot.json';material=json.loads(material_path.read_bytes())
        materials=material['bodies'];materials=materials if isinstance(materials,list) else list(materials.values())
        body_material={r['body_id']:r for r in materials};rows=[];sheets=[];inputs={}
        for name in ('geometry.json','material-snapshot.json'):
            inputs[name]=hashlib.sha256((folder/name).read_bytes()).hexdigest()
        for r,t in meshes:
            inputs[r['File']]=hashlib.sha256((folder/r['File']).read_bytes()).hexdigest()
            mat=body_material[r['Id']]
            row=dict(id=r['Id'],name=r['Body'],kind=r['BodyKind'],mass_contribution=r['mass_contribution'],
                elastic_material={k:mat.get(k) for k in ('name','model','young_pa','poisson','shear_pa','density_kg_m3','entry_sha256')},
                topology=topology(t,1e-7))
            rows.append(row)
            if r['BodyKind']=='surface':
                sheets.append(t);row['section_probe']=section_probe(t)
        reasons=['CAD hardpoints describe mechanism connections; internal body-to-body bonding/contact and an independently converged elastic solution are not established by these exports.']
        if sheets:
            reasons.append('Surface thickness is an assigned mass input; shell midsurface, wall thickness and connections require independent validation.')
        report['components'][role]=dict(name=component['Name'],geometry_directory=str(folder),source_hashes=inputs,
            allocated_cad_mass_kg=moments[0],surface_thickness_setting_m=component.get('Thickness'),bodies=rows,
            surface_union_topology=[topology(np.concatenate(sheets),tol) for tol in (1e-7,5e-5)] if sheets else [],
            physical_reference_status='not_established',reasons=reasons)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project',type=Path)
    p.add_argument('--roles',nargs='+',default=['fl_upper_wishbone','fr_upper_wishbone'])
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(a.project,a.roles)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
    for role,c in r['components'].items():print(role,c['physical_reference_status'],len(c['bodies']),'bodies')
