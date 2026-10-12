"""Independently verify that a mass-plan revision changed only declared inputs."""
import argparse,copy,hashlib,json
from pathlib import Path


def audit(baseline,candidate):
    def load(folder):
        receipt=json.loads((folder/'static_frame_build.json').read_bytes())
        names=[n for n in receipt['component_files'] if n.endswith('.jbeam')]
        if len(names)!=1:raise ValueError('One assembled JBeam required')
        for name,expected in receipt['component_files'].items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('Changed asset: '+name)
        return receipt,json.loads((folder/names[0]).read_bytes()),json.loads((folder/'manifest.json').read_bytes())
    before,source,old_manifest=load(baseline);after,revision,manifest=load(candidate)
    if set(source)!=set(revision) or len(source)!=1:raise ValueError('Part identities changed')
    plan=manifest['rigidity_mass_plan']['plan'];restored=copy.deepcopy(revision)
    part=next(iter(restored.values()));original=next(iter(source.values()))
    nodes={row[0]:row for row in part['nodes'][1:] if isinstance(row,list)}
    for row in plan['nodes']:
        if nodes[row['name']][-1]['nodeWeight']!=row['after_kg']:raise ValueError('Planned mass missing')
        nodes[row['name']][-1]['nodeWeight']=row['before_kg']
    for row in plan['changed_constraints']:
        options=part[row['section']][row['index']][-1]
        if options[row['key']]!=row['after']:raise ValueError('Planned stiffness missing')
        options[row['key']]=row['before']
    if source!=restored:raise ValueError('Unplanned JBeam changes')
    assets=lambda receipt:{n:h for n,h in receipt['component_files'].items() if not n.endswith('.jbeam')}
    if assets(before)!=assets(after):raise ValueError('Other assets changed')
    return dict(status='passed',baseline=str(baseline),candidate=str(candidate),
        physical_coefficients_geometry_graph_unchanged=True,non_jbeam_assets_unchanged=True,
        baseline_mass_kg=old_manifest['expected_dry_mass_kg'],candidate_mass_kg=manifest['expected_dry_mass_kg'],
        added_mass_kg=manifest['rigidity_mass_plan']['added_mass_kg'],
        changed_constraints=len(plan['changed_constraints']),changed_node_masses=len(plan['nodes']),
        receipt_sha256={str(p):hashlib.sha256((p/'static_frame_build.json').read_bytes()).hexdigest() for p in (baseline,candidate)})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.baseline,a.candidate);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
