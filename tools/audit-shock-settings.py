"""Audit exported coilover laws and recorded travel without fitting hardware values."""
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np

def beam_rows(part):
    defaults={}
    for row in part.get('beams',[])[1:]:
        if isinstance(row,dict):defaults.update(row)
        elif isinstance(row,list):yield row[0],row[1],defaults|(row[2] if len(row)>2 and isinstance(row[2],dict) else {})

def spring_force(wheel,compression):
    """Positive tensile-force convention, matching native getBeamStressDamp."""
    x=np.asarray(compression);force=-wheel['spring_preload_n']-wheel['spring_n_m']*x
    law=wheel.get('coilover_spring')
    if law:force=force-(law['final_rate_n_m']-law['initial_rate_n_m'])*np.maximum(x-law['crossover_compression_m'],0)
    return force

def audit(manifest,runs):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
    from frame_harness.vehicle import intake
    m,folder=intake(manifest)
    rows=[];files={str(manifest):hashlib.sha256(manifest.read_bytes()).hexdigest()}
    for file in folder.glob('*.jbeam'):
        digest=hashlib.sha256(file.read_bytes()).hexdigest();files[str(file)]=digest
        for part in json.loads(file.read_bytes()).values():rows.extend(beam_rows(part))
    corners={}
    for c,w in m['wheels'].items():
        nodes={w['nodes']['shock_top'],w['nodes']['shock_bottom']}
        beams=[o for a,b,o in rows if {a,b}==nodes]
        springs=[b for b in beams if b.get('beamSpring')==w['spring_n_m'] and b.get('beamType')=='|BOUNDED']
        dampers=[b for b in beams if b.get('beamDamp')==w['damper_ns_m'] and b.get('beamSpring')==0]
        if len(springs)!=1 or len(dampers)!=1:raise ValueError(c+': shock export does not match recorded settings')
        ratio=w['motion_ratio'];law=w.get('coilover_spring');damper=dampers[0]
        corners[c]=dict(spring_n_m=w['spring_n_m'],damper_ns_m=w['damper_ns_m'],preload_n=w['spring_preload_n'],
            spring_law=law or 'single_rate',motion_ratio=ratio,
            wheel_rate_material_term_n_m=w['spring_n_m']*ratio**2,
            wheel_rate_scope='k * motion_ratio^2 only; excludes preload geometric stiffness and tire compliance',
            shock_bump_stop_m=damper['shortBoundRange'],shock_droop_stop_m=damper['longBoundRange'],
            damper_cutoff_hz=damper.get('dampCutoffHz'),exported_beams=beams,
            settings_source=w.get('suspension_settings_source'),recordings=[])
        for run in runs:
            r=json.loads((run/'build_manifest.json').read_bytes())
            if r!=m:raise ValueError('Recording belongs to a different build')
            probe=json.loads((run/'probe.json').read_bytes());completion=json.loads((run/'completion.json').read_bytes())
            if completion.get('status')!='completed' or not probe.get('sources_unchanged') or probe.get('resource_abort') or probe.get('error'):
                raise ValueError('Recording incomplete or changed')
            path=run/'motion_diagnostics.json';files[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
            samples=[s for s in json.loads(path.read_bytes())['samples'] if s['t']>2]
            x=np.array([w['ride_reference']['reference_shock_length_m']-s['coilovers'][c][0]['length_m'] for s in samples])
            measured=np.array([sum(b['elastic_force_n'] for b in s['coilovers'][c] if b['spring_n_m']>0) for s in samples])
            stop=np.array([sum(b['elastic_force_n'] for b in s['coilovers'][c] if b['spring_n_m']==0) for s in samples])
            error=measured-spring_force(w,x)
            corners[c]['recordings'].append(dict(run=str(run),samples=len(samples),compression_mm=np.percentile(x*1000,[0,50,100]).tolist(),
                crossover_active_fraction=float(np.mean(x>law['crossover_compression_m'])) if law else 0.,
                stop_elastic_force_peak_n=float(max(abs(stop))),spring_law_error_peak_n=float(max(abs(error))),
                spring_law_error_rms_n=float(np.sqrt(np.mean(error**2)))))
    return dict(scope=__doc__,qualification_status='not_qualified',manifest=str(manifest),source_hashes=files,corners=corners,
        hardware_provenance='Explicit settings alone do not establish independent measurement; check project provenance.',
        required_physical_evidence=['Measured spring rates','Measured compression/rebound damper curves','Verified free length/preload','Verified travel stops'],
        single_rate_corners=[c for c,w in m['wheels'].items() if not w.get('coilover_spring')],
        numerical_added_mass_kg=m['expected_dry_mass_kg']-m['cad_dry_mass_kg'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--runs',nargs='*',type=Path,default=[])
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();report=audit(a.manifest,a.runs)
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['corners'],indent=2))
