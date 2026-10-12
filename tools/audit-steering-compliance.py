"""Separate measured tie stretch from total front toe error against ideal motion.

The remainder includes member/mount deformation and coupled mechanism effects.
This is a kinematic sensitivity diagnostic, not a material-compliance target.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import Predictor,angles,angle_error
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def audit(run,output):
    paths=[run/n for n in ('build_manifest.json','motion_comparison.json','result.json')]
    manifest,motion,result=[json.loads(p.read_bytes()) for p in paths]
    nominal=Predictor(manifest);stretched=Predictor(manifest);samples=[]
    for row in motion['samples']:
        if row['t']<4:continue
        item=dict(t=row['t'],corners={})
        for corner in ('FL','FR'):
            actual=row['corners'][corner]
            if not actual.get('reachable'):raise ValueError('Unreachable motion sample')
            mech=nominal.mechanisms[corner]
            if mech.translating_rack:raise ValueError('This diagnostic currently requires equivalent tie actuators')
            predicted=[]
            for predictor,extra in ((nominal,0.),(stretched,actual['tie_length_error_m'])):
                pose=predictor.solve(corner,actual['travel_m'],actual['actuator_extension_m']+extra)
                axis=pose['hub_axis']-pose['hub'];axis*=1 if mech.p['hub_axis'][0]>mech.p['hub'][0] else -1
                predicted.append(angles(axis))
            reference_error=float(max(abs(angle_error(predicted[0],np.array([actual['ideal_camber_deg'],actual['ideal_toe_deg']])))))
            if reference_error>1e-3:raise ValueError('Reconstructed ideal pose differs from recorded comparison')
            total=actual['toe_error_deg'];tie=float(angle_error(predicted[1],predicted[0])[1])
            item['corners'][corner]=dict(total_toe_error_deg=total,tie_stretch_toe_change_deg=tie,
                remaining_toe_error_deg=total-tie,tie_stretch_mm=actual['tie_length_error_m']*1000,
                reconstructed_reference_error_deg=reference_error)
        samples.append(item)
    if not samples:raise ValueError('Missing active motion samples')
    peak={c:max(samples,key=lambda r:abs(r['corners'][c]['total_toe_error_deg'])) for c in ('FL','FR')}
    report=dict(scope=__doc__,qualification_changed=False,original_status=result['status'],
        files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},samples=samples,peak_toe_samples=peak)
    fig,axes=plt.subplots(2,1,figsize=(10,7),sharex=True,layout='constrained')
    for ax,c in zip(axes,('FL','FR')):
        for key,label in [('total_toe_error_deg','Total toe error'),('tie_stretch_toe_change_deg','Predicted from measured tie stretch'),('remaining_toe_error_deg','Remaining error')]:
            ax.plot([r['t'] for r in samples],[r['corners'][c][key] for r in samples],label=label)
        ax.set(title=c,ylabel='Toe difference (degrees)');ax.grid(alpha=.2);ax.legend()
    axes[-1].set_xlabel('Simulation time (s)');fig.suptitle('Steering compliance diagnostic; ideal rigid linkage reference')
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=150);plt.close(fig)
    output.with_suffix('.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({c:r['corners'][c] for c,r in peak.items()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();audit(a.run,a.output)
