"""Separate applied-load evidence, material proxies and structural separation."""
from __future__ import annotations
import html
import json
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from .build import write_json
from .report import load_csv


def component_count(node_count, edges):
    if not edges:
        return node_count
    a,b=np.asarray(edges,dtype=int).T
    graph=coo_matrix((np.ones(2*len(a)),(np.r_[a,b],np.r_[b,a])),shape=(node_count,node_count)).tocsr()
    return int(connected_components(graph,directed=False,return_labels=False))


def cut_separating_force(nodes, beams, cut_edges, load_vectors, distance_m):
    """Move the severed components apart by one requested distance in a 10 s cut.

    The 3 s settle / 2 s ramp / 2 s hold waveform has a displacement integral
    of 41/3 s^2. Use component masses and net loads: total vehicle mass would
    throw a small detached piece far away and make the evidence unreadable.
    """
    names=list(nodes);indices={name:i for i,name in enumerate(names)}
    removed={tuple(sorted(edge)) for edge in cut_edges}
    edges=[(indices[b['a']],indices[b['b']]) for b in beams if tuple(sorted((b['a'],b['b']))) not in removed]
    row=[];col=[]
    for a,b in edges:row.extend((a,b));col.extend((b,a))
    graph=coo_matrix((np.ones(len(row)),(row,col)),shape=(len(names),len(names))).tocsr()
    count,labels=connected_components(graph,directed=False)
    masses=np.zeros(count);loads=np.zeros((count,3))
    for i,name in enumerate(names):
        masses[labels[i]]+=nodes[name]['mass']
        loads[labels[i]]+=load_vectors.get(name,[0,0,0])
    if count<2 or np.any(masses<=0) or distance_m<=0:
        raise ValueError('Controlled cut requires separate positive-mass components and a positive inspection distance')
    acceleration=loads/masses[:,None]
    relative=max(np.linalg.norm(a-b) for a in acceleration for b in acceleration)
    if not np.isfinite(relative) or relative<=0:
        raise ValueError('Controlled cut loads do not separate its components')
    return float(distance_m/((41/3)*relative))


def association_components(metadata, manifest, broken):
    nodes=metadata['nodes']; indices={n['cid']:i for i,n in enumerate(nodes)}
    edges=[(indices[b['id1']],indices[b['id2']]) for b,cut in zip(metadata['beams'],broken) if not cut]
    row=[];col=[]
    for a,b in edges: row.extend((a,b));col.extend((b,a))
    graph=coo_matrix((np.ones(len(row)),(row,col)),shape=(len(nodes),len(nodes))).tocsr()
    _,labels=connected_components(graph,directed=False)
    groups={}
    for i,node in enumerate(nodes):
        membership=manifest['nodes'][node['name']]['options'].get('group',[])
        if isinstance(membership,str):membership=[membership]
        for group in membership:
            if group.startswith('cad_'):
                counts=groups.setdefault(group,{})
                component=str(int(labels[i]));counts[component]=counts.get(component,0)+1
    return {'mesh_support_components':groups,
            'groups_spanning_separated_components':sum(len(g)>1 for g in groups.values()),
            'note':'Group-level support audit; engine per-vertex bindings and polygon culling still require rendered-image review.'}


def damage_report(run, *, render=True):
    experiment=json.loads((run/'experiment.json').read_text()); scenario=experiment['scenario']
    if not scenario.get('expected_damage'):
        return {}
    telemetry=run/json.loads((run/'telemetry_location.json').read_text())['directory']
    metadata=json.loads((telemetry/'metadata.json').read_text())
    events=json.loads((telemetry/'events.json').read_text()) if (telemetry/'events.json').exists() else []
    loads=load_csv(telemetry/'loads.csv'); raw=load_csv(telemetry/'beams.csv')
    count=len(metadata['beams']); data=raw[:len(raw)//count*count].reshape(-1,count,6)
    node_indices={n['cid']:i for i,n in enumerate(metadata['nodes'])}
    endpoints=[(node_indices[b['id1']],node_indices[b['id2']]) for b in metadata['beams']]
    initial=component_count(len(node_indices),endpoints); separation=None; last_mask=None; final_components=initial
    for sample in data:
        mask=sample[:,5]>0
        if last_mask is not None and np.array_equal(mask,last_mask):
            continue
        last_mask=mask.copy()
        components=component_count(len(node_indices),[e for e,broken in zip(endpoints,mask) if not broken])
        final_components=components
        if components>initial and separation is None:
            time=float(sample[0,0]); force=float(np.interp(time,loads[:,0],loads[:,1]))
            separation={'time':time,'external_force_n':force,'components':components}
    yielding=next((e for e in events if e['type']=='persistent_deformation'),None)
    breaking=next((e for e in events if e['type']=='beam_broke' and not e.get('controlled')),None)
    report={'first_persistent_deformation':yielding,'first_natural_beam_break':breaking,'first_structural_separation':separation,
            'initial_components':initial,'final_components':final_components,'peak_applied_force_n':float(loads[:,1].max()),
            'controlled_cut':bool(scenario.get('cut_edges')),'events':events,
            'capture_files':[p.name for p in sorted(telemetry.glob('*.png'))],
            'force_note':'External actuator load is distinct from signed native force in an individual beam. Ultimate thresholds are material-capacity proxies, not validated rupture predictions.'}
    report['mesh_association_audit']=association_components(metadata,json.loads((run/'build_manifest.json').read_text()),data[-1,:,5]>0)
    skin_path=telemetry/'skin_state.json'
    if skin_path.exists():
        skin=json.loads(skin_path.read_text())
        hidden={'cad_'+n for n in skin.get('removed',[]) if skin.get('visibility_results',{}).get(n) is True}
        groups=report['mesh_association_audit']['mesh_support_components']
        report['mesh_association_audit']['visible_groups_spanning_separated_components']=sum(len(v)>1 and k not in hidden for k,v in groups.items())
        report['mesh_association_audit']['confirmed_removed_regions']=len(hidden)
    report['threshold_observations']={
        'yield':{'observed':yielding is not None,'right_censored_at_n':None if yielding else report['peak_applied_force_n']},
        'break':{'observed':breaking is not None,'right_censored_at_n':None if breaking else report['peak_applied_force_n']}}
    for key,event in (('first_yield_external_force_n',yielding),('first_break_external_force_n',breaking),('separation_external_force_n',separation)):
        report[key]=event.get('external_force_n') if event else None
    write_json(run/'damage.json',report)
    if not render:
        return {k:v for k,v in report.items() if k not in ('events','capture_files')}
    lines=['<!doctype html><meta charset="utf-8"><title>Damage evidence</title>',
           '<style>body{font:16px system-ui;max-width:1200px;margin:2rem auto}img{width:48%;margin:.5%}pre{white-space:pre-wrap}</style>',
           '<h1>Damage and mesh evidence</h1><p>'+html.escape(report['force_note'])+'</p>',
           '<p><a href="report.html">Trajectory replay</a> · <a href="damage.json">Event data</a></p>']
    for name in report['capture_files']:
        lines.append(f'<a href="{telemetry.name}/{name}"><img alt="{html.escape(name)}" src="{telemetry.name}/{name}"></a>')
    lines.append('<pre>'+html.escape(json.dumps({k:v for k,v in report.items() if k!='events'},indent=2))+'</pre>')
    (run/'damage_report.html').write_text('\n'.join(lines),encoding='utf-8')
    return {k:v for k,v in report.items() if k not in ('events','capture_files')}
