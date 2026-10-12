"""Explicit representation and mass policy; visual mass belongs to one host."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import numpy as np


def visual(component):
    return component.get('Representation') == 'visual_only'


def acknowledgement(component):
    root = Path(component['GeometryDirectory'])
    geometry = json.loads((root/'geometry.json').read_text(encoding='utf-8-sig'))
    files = ['geometry.json'] + [m['File'] for m in geometry['Meshes']]
    hashes = {}
    for name in files:
        path = (root/name).resolve()
        if path.parent != root.resolve():
            raise ValueError('Geometry path escapes component directory')
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = {k: component.get(k) for k in ('Representation','MassPolicy','CustomMassKg','VisualParentId','VisualParentMemberId','SurfaceMassMode','Thickness')}
    return hashlib.sha256(json.dumps([settings,hashes],sort_keys=True).encode()).hexdigest()


def combine(moments):
    mass = sum(m for m,_,_ in moments)
    center = sum(m*np.asarray(p) for m,p,_ in moments)/mass if mass else np.asarray(moments[0][1])
    inertia = np.zeros((3,3))
    for m,p,i in moments:
        r = np.asarray(p)-center
        inertia += np.asarray(i)+m*(r@r*np.eye(3)-np.outer(r,r))
    return mass,center,inertia


def validate(project, read_geometry):
    owners = {c['Id']:c for c in project['Components']}
    members = {m['Id']:m for m in (project.get('JointWorkspace') or {}).get('Members',[])}
    reports = []
    for c in owners.values():
        mode = c.get('Representation') or 'physical'
        policy = c.get('MassPolicy') or 'cad'
        if mode not in ('physical','visual_only') or policy not in ('cad','custom','exclude'):
            raise ValueError(c['Name']+': unknown representation or mass policy')
        mass = read_geometry(c)[1][0]
        if not visual(c):
            if mass <= 0:raise ValueError(c['Name']+': zero mass. Supply mass or explicitly choose Visual only and acknowledge excluded mass.')
        else:
            if c.get('MvpRole') not in ('','accessory') and not c.get('MvpRole','').startswith('panel'):
                raise ValueError(c['Name']+': a required mechanical role cannot be visual only')
            parent = owners.get(c.get('VisualParentId'))
            if parent is None or parent is c or visual(parent):
                raise ValueError(c['Name']+': choose a physical visual parent; visual-parent chains are not supported')
            member_id = c.get('VisualParentMemberId')
            parent_members = [m for m in members.values() if m['ComponentId']==parent['Id']]
            if parent_members and (member_id not in members or members[member_id]['ComponentId']!=parent['Id']):
                raise ValueError(c['Name']+': select the moving parent member')
            if member_id and not parent_members:raise ValueError(c['Name']+': stale visual member selection')
            if any(a['ComponentId']==c['Id'] for a in project.get('Anchors',[])):
                raise ValueError(c['Name']+': visual-only parts cannot own physical anchors or fasteners')
            if mass == 0 and c.get('MassAcknowledgement') != acknowledgement(c):
                raise ValueError(c['Name']+': acknowledge Visual only — mass excluded for the current geometry')
        reports.append(dict(component=c['Id'],representation=mode,mass_policy=policy,mass_kg=mass,
                            parent=c.get('VisualParentId') if visual(c) else None,member=c.get('VisualParentMemberId') if visual(c) else None))
    return reports


def physical_project(project, read_geometry):
    """A build-local copy. Aggregate before physical mass fitting, never add twice."""
    reports = validate(project,read_geometry)
    result = copy.deepcopy(project)
    owners = {c['Id']:c for c in result['Components']}
    members = {m['Id']:m for m in (result.get('JointWorkspace') or {}).get('Members',[])}
    contributions = []
    for c in project['Components']:
        if not visual(c):continue
        moment = read_geometry(c)[1]
        if moment[0] == 0:continue
        parent = owners[c['VisualParentId']]
        member_id = c.get('VisualParentMemberId')
        # Endpoint-only wheel/shaft/coilover fits cannot preserve an arbitrary
        # added inertia tensor. Do not silently drop those moments.
        role = parent.get('MvpRole','')
        if any(role.endswith(s) for s in ('_wheel','_halfshaft','_spring_damper','_tie_rod','_toe_link','_radius_rod')) or role in ('front_propshaft','cvt_output_shaft'):
            raise ValueError(c['Name']+': this parent uses an endpoint mass approximation; choose a rigid physical host for positive visual mass')
        item = dict(source=c['Id'],mass=float(moment[0]),center=np.asarray(moment[1]).tolist(),inertia=np.asarray(moment[2]).tolist())
        parent.setdefault('_VisualMass',[]).append(item)
        if member_id:members[member_id].setdefault('_VisualMass',[]).append(item)
        contributions.append(item|dict(parent=parent['Id'],member=member_id))
    result['Components'] = [c for c in result['Components'] if not visual(c)]
    result['_VisualComponentIds'] = [c['Id'] for c in project['Components'] if visual(c)]
    return result,dict(components=reports,contributions=contributions)


def refit_existing_part(part,moments,contributions=None):
    from frame_harness.build import node_table
    from frame_harness.calibration import fit_masses
    table=node_table(part);ids=list(table);xyz=np.array([table[n]['position'] for n in ids])
    target=combine([(v['mass'],v['center'],v['inertia']) for v in contributions]) if contributions else moments
    masses,report=fit_masses(xyz,*target)
    if not report['accepted']:raise ValueError('Visual mass cannot fit the existing host graph; choose another physical parent')
    if contributions:
        masses+=np.array([table[n]['options']['nodeWeight'] for n in ids])
        report['scope']='Added visual mass fit independently; original host node masses and springs preserved'
        report['combined_mass_kg']=float(masses.sum())
    part['nodes']=[['id','posX','posY','posZ']]+[[n,*table[n]['position'],table[n]['options']|dict(nodeWeight=float(m))] for n,m in zip(ids,masses)]
    return report
