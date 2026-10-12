"""Compact comparison of hash-verified, matched high-rate suspension captures."""
import argparse,hashlib,json
from pathlib import Path


def summarize(runs):
    results=[];identity=None;window=None
    for label,folder in runs:
        folder=Path(folder)
        frequency=json.loads((folder/'frequency_analysis.json').read_bytes())
        attribution=json.loads((folder/'constraint_attribution.json').read_bytes())
        manifest=json.loads((folder/'build_manifest.json').read_bytes())
        job=json.loads((folder/'job.json').read_bytes())
        if frequency.get('qualification_status')!='diagnostic_only':raise ValueError('Validated frequency analysis required')
        for report in (frequency,attribution):
            for name,expected in report['evidence_sha256'].items():
                if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:raise ValueError('Changed evidence: '+str(folder/name))
        physical={k:manifest[k] for k in ('nodes','mass_allocations','wheels','expected_dry_mass_kg')}
        physical_hash=hashlib.sha256(json.dumps(physical,sort_keys=True).encode()).hexdigest()
        capture={k:job['frequency_capture'][k] for k in ('start_s','duration_s','nodes','chassis_nodes')}
        capture['scenario']=job['scenario']
        if identity is not None and physical_hash!=identity:raise ValueError('Different geometry, mass or wheel configuration')
        if window is not None and capture!=window:raise ValueError('Different capture window or reference nodes')
        identity,window=physical_hash,capture
        corners={}
        for corner in ('FL','FR'):
            measured=frequency['channels'][corner+'_toe_error_deg'];item=attribution['corners'][corner]
            corners[corner]=dict(peak_toe_error_deg=measured['peak'],ac_rms_deg=measured['ac_rms'],
                peak_time_s=measured['peak_time_s'],contributions_deg=item['contributions_deg'],
                reconstructed_error_deg=item['reconstructed_error_deg'])
        results.append(dict(label=label,run=str(folder),corners=corners,
            requested_frame_frequency_hz=manifest['frame_reference']['requested_frequency_hz'],
            requested_arm_frequency_hz=manifest.get('wishbone_conditioning',{}).get('frequency_hz',400),
            source_hashes={n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ('frequency_analysis.json','constraint_attribution.json')}))
    return dict(status='diagnostic_only_not_qualified',scope='Matched launch captures; source geometry, masses, wheel inputs and capture window verified equal. Attribution is kinematic, not proof of causal loading.',
        physical_inputs_sha256=identity,capture=window,trials=results)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='append',required=True,help='LABEL=recording directory')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=summarize([r.split('=',1) for r in a.run]);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained',sharey=True);groups=('mounts','arms','tie','upright')
    labels=[r['label'] for r in report['trials']];x=np.arange(len(labels))
    for ax,corner in zip(axes,('FL','FR')):
        base=np.zeros(len(labels))
        for group in groups:
            values=np.array([r['corners'][corner]['contributions_deg'][group]*np.sign(r['corners'][corner]['reconstructed_error_deg']) for r in report['trials']])
            ax.bar(x,values,bottom=base,label=group);base+=values
        ax.axhline(2,color='black',linestyle='--',label='Existing 2-degree check')
        ax.set_xticks(x,labels,rotation=20);ax.set_ylabel('Peak toe error contribution (degrees)');ax.set_title(corner);ax.grid(axis='y',alpha=.2)
    fig.legend(*axes[1].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.5,1.04),ncol=5)
    fig.suptitle('Launch motion error against unchanged CAD linkage | diagnostic trials',y=1.1)
    fig.savefig(a.output.with_suffix('.png'),dpi=150,bbox_inches='tight');plt.close(fig)
    print(json.dumps({r['label']:{c:v['peak_toe_error_deg'] for c,v in r['corners'].items()} for r in report['trials']},indent=2))
