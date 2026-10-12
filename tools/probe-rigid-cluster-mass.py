"""Bound ballast savings from treating permanently fixed bodies as one mass cluster.

Offline feasibility only. No vehicle is changed or qualified. Moving bodies and
breakaway mounts stay separate. Per-component moments inside the fixed cluster
are deliberately not constrained; only its combined rigid-body moments are.
"""
import argparse,copy,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from support_mass_fit import redistribute


def audit(path):
    m=json.loads(path.read_bytes());alloc=copy.deepcopy(m['mass_allocations'])
    for node,row in m['numerical_mass']['nodes'].items():
        for owner,extra in row['added_by_component_kg'].items():alloc[owner][node]-=extra
    frame=[o for o,r in m['component_roles'].items() if r=='frame']
    if len(frame)!=1:raise ValueError('One frame owner required')
    # Only components that the generator explicitly attached as fixed structures.
    frozen=set((m['numerical_mass'].get('redistribution') or {}).get('frozen_split_owners',[]))
    cluster=(set(m['fixed_attachment_contract'])|set(frame))-frozen
    if frame[0] not in cluster:raise ValueError('Frame cannot be a split moving owner')
    merged={}
    for owner in sorted(cluster):
        for node,mass in alloc.pop(owner).items():merged[node]=merged.get(node,0.)+mass
    alloc['fixed_cluster']=merged
    nodes={n:dict(position=v['position'],options={'nodeWeight':sum(a.get(n,0.) for a in alloc.values())}) for n,v in m['nodes'].items()}
    graph=SimpleNamespace(nodes=nodes,mass_allocations=alloc,
        rigid_member_allocations={o:{'owner':o} for o in frozen})
    targets={n:v['target_kg'] for n,v in m['numerical_mass']['nodes'].items()}
    before=sum(max(0,targets[n]-nodes[n]['options']['nodeWeight']) for n in targets)
    result=redistribute(graph,targets)
    after=sum(max(0,targets[n]-nodes[n]['options']['nodeWeight']) for n in targets)
    return dict(scope=__doc__,manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        cluster_roles={o:m['component_roles'][o] for o in sorted(cluster)},
        baseline_ballast_kg=before,cluster_ballast_kg=after,potential_saving_kg=before-after,
        combined_moment_residual=result['normalized_moment_residual'],qualification_status='offline_feasibility_only')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifest',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(args.manifest)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
