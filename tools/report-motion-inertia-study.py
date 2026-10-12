"""Compare native motion residuals and independent CAD member inertia audits.

This is a tradeoff report, never a qualification receipt. Operational spectra
and covered-member inertia do not establish full-vehicle transient fidelity.
"""
import argparse, hashlib, importlib.util, json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def checked_representation_controls(paths):
    verified={}
    for path in paths:
        saved=read(Path(path));spec=importlib.util.spec_from_file_location('shared_controls',Path(__file__).with_name('audit-shared-carrier-inputs.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        current=module.audit(Path(saved['baseline']),Path(saved['candidate']))
        if saved['manifest_sha256']!=current['manifest_sha256']:raise ValueError('Stale representation control audit')
        key=(current['manifest_sha256'][current['baseline']],current['manifest_sha256'][current['candidate']])
        if key in verified:raise ValueError('Duplicate representation control audit')
        verified[key]=current
    return verified


def recording_controls(reference,job,proof=None):
    if job['scenario']!=reference['scenario']:raise ValueError('Unmatched recording scenario')
    a,b=reference['frequency_capture'],job['frequency_capture']
    if proof is None:
        if a!=b:raise ValueError('Unmatched recording frequency_capture')
        return
    if {k:v for k,v in a.items() if k!='nodes'}!={k:v for k,v in b.items() if k!='nodes'}:
        raise ValueError('Representation trial changed recording cadence or scope')
    allowed=set(proof['removed_quadrature_nodes'])|{j['node'] for j in proof['shared_joints']}
    if (set(a['nodes'])^set(b['nodes']))-allowed:raise ValueError('Unrelated capture node changed')


def report(entries, output, representation_controls=()):
    result=dict(scope=__doc__,qualified=False,cases={}); jobs=[]
    for label,run,inertia in entries:
        run=Path(run);inertia=Path(inertia)
        freq=read(run/'frequency_analysis.json');audit=read(inertia);probe=read(run/'probe.json');job=read(run/'job.json')
        if not probe.get('sources_unchanged') or freq['qualification_status']!='diagnostic_only':
            raise ValueError('Invalid source identity or frequency recording')
        if not probe.get('telemetry',{}).get('finite') or not probe['telemetry'].get('increasing'):
            raise ValueError('Incomplete or invalid native telemetry')
        m=job['manifest']
        if audit['manifest_sha256']!=probe['manifest_sha256']:raise ValueError('Inertia audit describes a different build')
        jobs.append(job)
        item=dict(run=str(run),execution_mode=probe['mode'],deterministic=probe['deterministic'],
            total_mass_kg=m['expected_dry_mass_kg'],cad_mass_kg=m['cad_dry_mass_kg'],
            numerical_mass_kg=m['numerical_mass']['added_mass_kg'],corners={},
            hashes={n:sha(run/n) for n in ('frequency_analysis.json','probe.json','job.json','result.json')},
            inertia_audit_sha256=sha(inertia))
        for corner in ('FL','FR'):
            row=next(s for s in audit['corners'][corner]['samples'] if s['travel_from_reference_m']==0)
            channel=freq['channels'][corner+'_toe_error_deg']
            item['corners'][corner]=dict(cad_member_kinetic_mass_kg=row['cad_member_kinetic_mass_kg'],
                generated_member_kinetic_mass_kg=row['generated_member_kinetic_mass_kg'],
                peak_toe_error_deg=channel['peak'],ac_rms_toe_error_deg=channel['ac_rms'],mean_toe_error_deg=channel['mean'])
        result['cases'][label]=item
    reference=jobs[0];proofs=checked_representation_controls(representation_controls)
    hashes=[read(Path(run)/'probe.json')['manifest_sha256'] for _,run,_ in entries]
    for i,job in enumerate(jobs[1:],1):
        proof=proofs.get((hashes[0],hashes[i]));recording_controls(reference,job,proof)
        a,b=reference['manifest'],job['manifest']
        if proof is None and {n:r['position'] for n,r in a['nodes'].items()}!={n:r['position'] for n,r in b['nodes'].items()}:
            raise ValueError('Node geometry differs')
        if a['template_definition']['hardpoints']!=b['template_definition']['hardpoints']:raise ValueError('Hardpoints differ')
        for corner in ('FL','FR','RL','RR'):
            for key in ('spring_n_m','spring_preload_n','damper_ns_m','coilover_spring','brake_torque_nm'):
                if a['wheels'][corner].get(key)!=b['wheels'][corner].get(key):raise ValueError('Physical setting differs: '+key)
    if len({(r['execution_mode'],r['deterministic']) for r in result['cases'].values()})!=1:
        raise ValueError('Execution modes differ')
    result['controls_verified']=True
    result['representation_controls']=[dict(baseline=p['baseline'],candidate=p['candidate'],
        shared_joints=p['shared_joints'],removed_quadrature_nodes=p['removed_quadrature_nodes'],
        relocated_quadrature_nodes=p['relocated_quadrature_nodes'],
        brake_reaction_changes=p['brake_reaction_changes'],rebased_rigid_meshes=p['rebased_rigid_meshes']) for p in proofs.values()]
    fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
    for label,item in result['cases'].items():
        for corner,row in item['corners'].items():
            axes[0].scatter(row['generated_member_kinetic_mass_kg']/row['cad_member_kinetic_mass_kg'],
                            row['peak_toe_error_deg'],label=label+' '+corner)
        axes[1].bar(label,item['cad_mass_kg'],color='#8299aa')
        axes[1].bar(label,item['numerical_mass_kg'],bottom=item['cad_mass_kg'],color='#d48645')
    axes[0].set(xlabel='Covered front-member inertia / CAD reference',ylabel='Peak toe residual (degrees)',title='Both errors matter')
    axes[0].axvline(1,color='gray',linestyle='--');axes[0].legend(fontsize=8);axes[0].grid(alpha=.2)
    axes[1].set(ylabel='Vehicle mass (kg)',title='CAD mass (blue) + numerical mass (orange)')
    scenario=reference['scenario'].replace('_',' ')
    fig.suptitle(f'Controlled {scenario} study — diagnostic, not physical qualification',fontsize=11)
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output.with_suffix('.png'),dpi=140);plt.close(fig)
    output.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',nargs=3,action='append',required=True,metavar=('LABEL','RUN','INERTIA_AUDIT'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--representation-controls',type=Path,action='append',default=[]);a=p.parse_args()
    report(a.case,a.output,a.representation_controls);print('Saved comparison:',a.output)
