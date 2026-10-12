"""Audit a support-reuse generation against its controlled baseline.

Only support selection, numerical stiffness/damping and numerical mass may
change. This checks declared physical controls and identity, not native motion.
"""
import argparse
import hashlib
import json
from pathlib import Path


def read(path): return json.loads(path.read_bytes())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(baseline,candidate):
    paths=[p/'manifest.json' for p in (baseline,candidate)]
    a,b=map(read,paths)
    if {n:v['position'] for n,v in a['nodes'].items()}!={n:v['position'] for n,v in b['nodes'].items()}:
        raise ValueError('Node geometry changed')
    if a['template_definition']['hardpoints']!=b['template_definition']['hardpoints']:
        raise ValueError('Authored hardpoints changed')
    controls=('spring_n_m','damper_ns_m','spring_preload_n','coilover_spring','brake_torque_nm','tire_contract')
    for corner in a['wheels']:
        for key in controls:
            if a['wheels'][corner].get(key)!=b['wheels'][corner].get(key):
                raise ValueError('Physical wheel setting changed: '+corner+' '+key)
    if a['component_roles']!=b['component_roles'] or a['cad_dry_mass_kg']!=b['cad_dry_mass_kg']:
        raise ValueError('Component ownership or CAD mass changed')
    old={j['id']:j for j in a['joints']};new={j['id']:j for j in b['joints']};changes=[]
    if len(old)!=len(a['joints']) or len(new)!=len(b['joints']) or old.keys()!=new.keys():
        raise ValueError('Joint identities changed or duplicated')
    for name,joint in new.items():
        original=old[name]
        if joint['kind']=='spherical':
            if ({k:v for k,v in joint.items() if k!='nodes'}!={k:v for k,v in original.items() if k!='nodes'}
                or joint['nodes'][-1]!=original['nodes'][-1]):
                raise ValueError('Joint owner, kind or center changed: '+name)
            if not set(joint['nodes'][:-1])<=set(b['mass_allocations'].get(joint['parent'],{})):
                raise ValueError('Support nodes do not belong to declared parent: '+name)
            if joint['nodes']!=original['nodes']:
                changes.append(dict(joint=name,before=original['nodes'],after=joint['nodes']))
        elif joint!=original: raise ValueError('Other joint changed: '+name)
    minimum=min(b['nodes'][n]['mass_kg'] for n in b['numerical_mass']['nodes'])
    if minimum<2-1e-9: raise ValueError('Loaded node below retained 2kg floor')
    assets=[]
    for directory in (baseline,candidate):
        receipt=read(directory/'static_frame_build.json')
        for name,digest in receipt['component_files'].items():
            if sha(directory/name)!=digest:raise ValueError('Build file changed: '+name)
        assets.append({n:h for n,h in receipt['component_files'].items() if not n.endswith('.jbeam')})
    if assets[0]!=assets[1]:raise ValueError('Non-JBeam vehicle assets changed')
    return dict(status='passed',scope=__doc__,baseline=str(baseline),candidate=str(candidate),
        hashes={str(p):sha(p) for p in paths},all_node_positions_unchanged=True,
        hardpoints_and_physical_suspension_coefficients_unchanged=True,
        non_jbeam_assets_unchanged=True,joint_kinds_centers_and_owners_unchanged=True,
        changed_supports=changes,minimum_loaded_mass_kg=minimum,
        loaded_nodes_before=len(a['numerical_mass']['nodes']),loaded_nodes_after=len(b['numerical_mass']['nodes']),
        mass_before_kg=a['expected_dry_mass_kg'],mass_after_kg=b['expected_dry_mass_kg'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=audit(a.baseline,a.candidate);a.output.write_text(json.dumps(r,indent=2)+'\n')
    print('Passed; changed support groups:',len(r['changed_supports']))
