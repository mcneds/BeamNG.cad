"""SolidWorks boundary for immutable CAD generations and shared calibration."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import zipfile
from appearance_textures import dae_texture_assets

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
HARNESS = HERE/'calibration'/'Test Harness'
if not HARNESS.exists():
    HARNESS = HERE.parents[1]/'dependencies'/'cad-calibration'/'Test Harness'
sys.path.insert(0, str(HARNESS))


def preflight():
    if sys.version_info < (3, 11):
        raise ValueError('CAD calibration requires Python 3.11 or newer')
    # Repeated small dense solves become dramatically slower when BLAS starts
    # one thread per logical CPU. Respect an explicitly configured override.
    os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
    try:
        import numpy, scipy, matplotlib
    except ImportError as error:
        raise ValueError('Calibration Python needs NumPy, SciPy and Matplotlib. Configure Calibration Python in Settings.') from error


def read(path):
    return json.loads('\n'.join(line for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if not line.lstrip().startswith('//')))


def stage_script(name, source):
    old = sys.argv
    try:
        script = source/name
        shutil.copy2(HERE/'generation'/name, script)
        sys.argv = [str(script)]
        runpy.run_path(str(script), run_name='__main__')
    finally:
        sys.argv = old


def fixed_preview(job,source):
    """Capture a verified old graph for a fresh CAD fit and display that graph."""
    from frame_harness.build import sha256,write_json,node_table,beam_table
    from components import write_off
    import numpy as np
    job,source=Path(job).resolve(),Path(source).resolve();check_snapshot(job)
    if source==job/'source':raise ValueError('Fixed graph refit needs fresh prepared CAD inputs')
    raw=job/'source/mochi_raw.jbeam';before=sha256(raw);part=read(raw)['mochi']
    validate_fixed_mounts(part,read(source/'frame-mounts.json') if (source/'frame-mounts.json').exists() else {})
    shutil.copy2(raw,source/'fixed-graph.jbeam')
    if sha256(raw)!=before or sha256(source/'fixed-graph.jbeam')!=before:raise ValueError('Baseline graph changed during snapshot')
    write_json(source/'fixed-graph-info.json',dict(baseline_generation=str(job),graph_sha256=before,mode='fixed graph; fresh CAD/reference properties required'))
    nodes=node_table(part);names=list(nodes);indices={n:i for i,n in enumerate(names)}
    faces=[[indices[n] for n in row[:3]] for row in part.get('triangles',[])[1:] if isinstance(row,list)]
    faces.extend([[indices[e['a']],indices[e['b']]] for e in beam_table(part)])
    write_off(source/'mochi_hull.off',np.array([nodes[n]['position'] for n in names]),faces)


def validate_fixed_mounts(part,declarations):
    import numpy as np
    patches=part.get('cadMountPatches',{})
    if set(patches)!=set(declarations):raise ValueError('Mount plan changed; regenerate the frame graph explicitly')
    if any(not np.allclose(patches[name]['position'],point['position'] if isinstance(point,dict) else point,atol=1e-7,rtol=0) for name,point in declarations.items()):
        raise ValueError('A mounting point moved; regenerate the frame graph explicitly')
    if any(patches[name].get('mode','short')!=(point.get('mode','short') if isinstance(point,dict) else 'short') for name,point in declarations.items()):
        raise ValueError('Mount representation changed; regenerate the frame graph explicitly')
    if any(patches[name].get('reference_pair')!=(point.get('reference_pair') if isinstance(point,dict) else None) for name,point in declarations.items()):
        raise ValueError('Mount reference pairing changed; regenerate the frame graph explicitly')
    if any(patches[name].get('mode','short')=='short' and abs(patches[name].get('attachment_length_m',.006)-(point.get('attachment_length_m',.006) if isinstance(point,dict) else .006))>1e-9 for name,point in declarations.items()):
        raise ValueError('Fastener attachment length changed; regenerate the frame graph explicitly')


def prepare(source, output, previous=None):
    from frame_harness.build import sha256, write_json, node_table, beam_table
    from build_static_frame import INPUTS, validate_inputs
    source, output = Path(source).resolve(), Path(output).resolve()
    validate_inputs(source)
    material_snapshot=source/'material-snapshot.json'
    geometry=read(source/'geometry.json') if (source/'geometry.json').exists() else {}
    if geometry.get('MaterialSource')=='solidworks' and not material_snapshot.exists():
        raise ValueError('SolidWorks material snapshot missing; export the selected bodies again')
    if material_snapshot.exists():
        from frame_harness.materials import load_snapshot
        load_snapshot(material_snapshot,[m['Id'] for m in geometry['Meshes']] if geometry else None)
    if output == source or source in output.parents:
        raise ValueError('Generation must be outside prepared inputs')
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output/'source'; snapshot.mkdir()
    hashes = {}
    texture_names=list(dae_texture_assets(source/'mochi.dae'))
    for name,data in dae_texture_assets(source/'mochi.dae').items():
        (snapshot/name).write_bytes(data);hashes[name]=sha256(snapshot/name)
    for name in INPUTS + tuple(n for n in ('geometry.json','material-snapshot.json','frame-mounts.json','fixed-graph.jbeam','fixed-graph-info.json') if (source/n).exists()):
        before = sha256(source/name); shutil.copy2(source/name, snapshot/name)
        if sha256(snapshot/name) != before or sha256(source/name) != before:
            raise ValueError('Source changed during snapshot: '+name)
        hashes[name] = before
    # Reusing a prepared generation must keep its original physical CAD, not
    # feed its subdivided render derivative back into the reference audit.
    if (source/'generation.json').exists():
        prior=read(source/'generation.json');physical=prior.get('mesh','mochi.dae')
        if Path(physical).name!=physical:raise ValueError('Invalid physical CAD source')
        before=sha256(source/physical)
        shutil.copy2(source/physical,snapshot/'mochi.dae')
        if sha256(snapshot/'mochi.dae')!=before:raise ValueError('Physical CAD snapshot changed')
        hashes[physical]=before
    if (snapshot/'fixed-graph.jbeam').is_file():
        raw=read(snapshot/'fixed-graph.jbeam')
        info=read(snapshot/'fixed-graph-info.json')
        if sha256(snapshot/'fixed-graph.jbeam')!=info['graph_sha256']:raise ValueError('Fixed graph snapshot changed')
        validate_fixed_mounts(raw['mochi'],read(snapshot/'frame-mounts.json') if (snapshot/'frame-mounts.json').exists() else {})
        bracing=dict(mode='fixed_graph',baseline=info,node_count=len(node_table(raw['mochi'])),final_beams=len(beam_table(raw['mochi'])))
    else:
        stage_script('JBeamShellGenerator.py', snapshot)
        from frame_harness.bracing import add_local_bracing
        raw=read(snapshot/'mochi_raw.jbeam')
        bracing=add_local_bracing(raw['mochi'])
        symmetric=geometry.get('Assignment',{}).get('Hull',{}).get('Symmetry',False)
        if symmetric:
            from planned_mounts import complete_mirror_graph
            xs=[v['position'][0] for v in node_table(raw['mochi']).values()]
            center_x=(min(xs)+max(xs))*.5
            raw['mochi']['cadGraphSymmetry']=dict(center_x_m=center_x,axis='X')
            bracing['hull_symmetry']=complete_mirror_graph(raw['mochi'],center_x,create_nodes=True)
        if (snapshot/'frame-mounts.json').is_file():
            from planned_mounts import insert_mounts
            patches=insert_mounts(raw['mochi'],read(snapshot/'frame-mounts.json'))
            bracing['mount_patches']=patches
            from frame_harness.torsion import add_frame_bracing
            bracing['angular']=add_frame_bracing(raw['mochi'])
            if symmetric:bracing['mounted_symmetry']=complete_mirror_graph(raw['mochi'],center_x)
            bracing['node_count']=len(node_table(raw['mochi']))
            bracing['final_beams']=len(beam_table(raw['mochi']))
    write_json(snapshot/'mochi_raw.jbeam',raw)
    write_json(snapshot/'graph-generation.json',bracing)
    print(f"Local frame bracing: {bracing['node_count']} nodes, {bracing['final_beams']} beams; fresh calibration required.",flush=True)
    from frame_harness.skin import prepare_skin
    shutil.copy2(snapshot/'mochi.dae',snapshot/'cad_source.dae')
    bindings=prepare_skin(raw['mochi'],snapshot/'cad_source.dae',snapshot/'mochi.dae')
    write_json(snapshot/'mesh-bindings.json',bindings)
    shutil.copy2(HARNESS/'frame_harness/lua/cadSkin.lua',snapshot/'cadSkin.lua')
    print(f"Local render binding: {len(bindings['regions'])} regions; original CAD retained for physical calibration.",flush=True)
    # Metadata reads the graph, never invokes a tuner or associates meshes.
    write_json(snapshot/'mochi.jbeam', read(snapshot/'mochi_raw.jbeam'))
    stage_script('BeamNGVehicleInfoGenerator.py', snapshot)
    (snapshot/'mochi.jbeam').unlink()
    part = read(snapshot/'mochi_raw.jbeam')['mochi']; nodes = node_table(part)
    # Frame-reference fixtures belong on the frame shell. Template mounting
    # patches can extend to suspension hardpoints outside the audited members.
    names = [name for name in nodes if not name.startswith('mount_')]
    def pair(fraction, excluded=()):
        available = [n for n in names if n not in excluded]
        ys = [nodes[n]['position'][1] for n in names]; xs = [nodes[n]['position'][0] for n in names]
        y = min(ys)+(max(ys)-min(ys))*fraction
        result = []
        for x in (min(xs), max(xs)):
            choice = min((n for n in available if n not in result), key=lambda n:
                         (nodes[n]['position'][1]-y)**2+(nodes[n]['position'][0]-x)**2)
            result.append(choice)
        return result
    supports = pair(0); supports += pair(1, supports)
    loads = pair(.5, supports); cut = pair(0)
    fixtures = {name: dict(fixed_nodes=supports, load_nodes=loads,
                 load_vectors={n:[0,0,(-.5 if name=='flex' or i==0 else .5)] for i,n in enumerate(loads)})
                for name in ('flex','torsion')}
    config = read(HARNESS/'examples'/'4130-reference.json')
    if material_snapshot.exists():
        for key in ('density_kg_m3','young_pa','poisson'):config.pop(key,None)
        config.update(material_source='solidworks',actual_condition='assigned_in_cad')
    config.update(fixtures=fixtures, cut_fixture=dict(load_nodes=cut,load_vectors={n:[0,-.5,0] for n in cut}))
    # Spatial correspondence only suggests selections. Approval is always cleared.
    if previous and (Path(previous)/'review.json').exists():
        old=read(Path(previous)/'review.json')
        def mapping(folder):
            g=folder/'geometry.json'
            return read(g)['Assignment']['Hull']['Orientation'] if g.exists() else 'XYZ'
        if old.get('nodes') and mapping(snapshot)==mapping(Path(previous)/'source'):
            old_positions={n['id']:n['position'] for n in old['nodes']}
            used={}; span=max(max(v['position'][i] for v in nodes.values())-min(v['position'][i] for v in nodes.values()) for i in range(3))
            def remap(n):
                if n not in used:
                    p=old_positions[n]
                    nearest=min(names,key=lambda k:sum((a-b)**2 for a,b in zip(nodes[k]['position'],p)))
                    if sum((a-b)**2 for a,b in zip(nodes[nearest]['position'],p))>(span*.1)**2:
                        raise ValueError('Previous fixture is too far from the new graph')
                    if nearest in used.values():raise ValueError('Previous fixtures collapse onto one node')
                    used[n]=nearest
                return used[n]
            def remap_fixture(f):
                return dict(fixed_nodes=[remap(n) for n in f.get('fixed_nodes') or []],load_nodes=[remap(n) for n in f['load_nodes']],
                            load_vectors={remap(n):v for n,v in f['load_vectors'].items()})
            try:
                remapped={k:remap_fixture(v) for k,v in old['fixtures'].items()};remapped_cut=remap_fixture(old['cut_fixture'])
                fixtures=remapped;config.update(fixtures=fixtures,cut_fixture=remapped_cut)
            except (ValueError,KeyError):pass
    from planned_mounts import reference_fixtures,reference_response_pairs
    fixtures.update(reference_fixtures(part,fixtures['flex']['fixed_nodes']))
    config.update(fixtures=fixtures,reference_cases=list(fixtures),reference_response_pairs=reference_response_pairs(fixtures))
    write_json(snapshot/'reference.json', config)
    manifest = dict(version=1, part='mochi', raw='mochi_raw.jbeam',mesh='cad_source.dae',vehicle='mochi.jbeam',render_binding='mesh-bindings.json',
                    assets=['mochi.dae','main.materials.json','info.json','base.pc','info_base.json',*texture_names],
                    runtime_assets={'cadSkin.lua':'lua/controller/cadSkin.lua'})
    if material_snapshot.exists(): manifest['material_snapshot']='material-snapshot.json'
    if (snapshot/'geometry.json').exists():
        hull=read(snapshot/'geometry.json')['Assignment']['Hull']
        manifest['coordinates']=dict(convention=hull.get('CoordinateConvention','legacy'),mapping=hull['Orientation'],units='metres',origin='assembly')
    manifest['sources'] = sorted(p.name for p in snapshot.iterdir() if p.is_file())
    write_json(snapshot/'generation.json', manifest)
    graph_hash = sha256(snapshot/'mochi_raw.jbeam')
    write_json(output/'review.json', dict(version=1,graph_sha256=graph_hash, approved=False,
        nodes=[dict(id=n,position=v['position']) for n,v in nodes.items()],
        beams=[[b['a'],b['b']] for b in beam_table(part)],fixtures=fixtures,cut_fixture=config['cut_fixture']))
    if any(sha256(source/name)!=expected for name,expected in hashes.items()):
        raise ValueError('Prepared inputs changed during generation; prepare again')
    write_json(output/'snapshot.json', dict(prepared_source=str(source), input_sha256=hashes,
        source_sha256={p.name:sha256(p) for p in snapshot.iterdir() if p.is_file()}))
    print('GENERATION '+str(output), flush=True)


def project(job, game=None, profile=None):
    from frame_harness.models import HarnessProject
    p = HarnessProject(source=job/'source', runs=job/'tests')
    if game: p.game = Path(game)
    if profile: p.userpath = Path(profile)
    return p


def check_snapshot(job, allow_reference=False):
    from frame_harness.build import sha256
    seal = read(job/'snapshot.json')
    for name, expected in seal['source_sha256'].items():
        if allow_reference and name == 'reference.json': continue
        if sha256(job/'source'/name) != expected:
            raise ValueError('Generation snapshot changed: '+name+'; prepare a new generation')


def calibrate(job, resume=False, live=False, game=None, profile=None, diagnostic=False, case=None,verification='full',save_report=True):
    from frame_harness.build import sha256, write_json, validate_part
    from frame_harness.calibration import run_calibration, load_part
    from frame_harness.generation import scenario
    check_snapshot(job)
    review = read(job/'review.json'); source = job/'source'; study = job/'study'
    if not review.get('approved') or review['graph_sha256'] != sha256(source/'mochi_raw.jbeam'):
        raise ValueError('Review and approve fixtures for this generation first')
    config = read(source/'reference.json')
    config.update(fixtures=review['fixtures'],cut_fixture=review['cut_fixture'])
    part = load_part(source/'mochi_raw.jbeam')
    for name in ('flex','torsion'): validate_part(part, scenario(config,name))
    from frame_harness.models import TestScenario
    cut = config['cut_fixture']
    validate_part(part, TestScenario('mesh-cut',10,0,[],cut['load_nodes'],1,load_vectors=cut['load_vectors']))
    if study.exists():
        if read(source/'reference.json') != config:
            raise ValueError('Fixtures changed; prepare a new generation instead of resuming')
        previous=read(study/'calibration-study.json')
        for prior_case, report in previous.get('candidates',{}).items():
            if report.get('artifact_sha256') and sha256(study/prior_case/'calibration.json') != report['artifact_sha256']:
                raise ValueError('Calibration artifact changed after generation')
    else:
        write_json(source/'reference.json',config)
        seal=read(job/'snapshot.json');seal['source_sha256']['reference.json']=sha256(source/'reference.json')
        write_json(job/'snapshot.json',seal)
    if case is None:
        case='solidworks-assigned' if config.get('material_source')=='solidworks' else '4130-annealed'
    chosen=case
    if verification not in ('quick','full'):raise ValueError('Unknown verification mode')
    state=run_calibration(project(job,game,profile),source/'reference.json',study,resume=resume,live=live and verification=='full',diagnostic=diagnostic,case=case,save_report=save_report)
    for case in state['candidates']:
        artifact=study/case/'calibration.json'
        state['candidates'][case]['artifact_sha256']=sha256(artifact)
    write_json(study/'calibration-study.json',state)
    if live and verification=='quick':
        from frame_harness.verification import run_quick
        from frame_harness.progress import emit
        quick=run_quick(project(job,game,profile),study,state,chosen,save_report=save_report)
        emit('Quick check finished',detail=quick['status']+('; '+ '; '.join(quick['reasons']) if quick['reasons'] else '; full qualification not performed'),outcome=quick['status'])
        print('QUICK STATUS '+quick['status'],flush=True)
        return quick
    print('CALIBRATION STATUS '+state['status'],flush=True)
    if not all(r['offline_accepted'] for r in state['candidates'].values()):
        from frame_harness.progress import emit
        reasons=list(state.get('limitations',[]))
        for case,report in state['candidates'].items():
            if report['offline_accepted']:continue
            if not report.get('fit',{}).get('attempted'):
                reasons.append(case+': stiffness fit not attempted because valid reference targets were unavailable')
            if not report.get('mass',{}).get('accepted'):
                reasons.append(case+': CAD mass-moment fit failed')
            for name,response in report.get('responses',{}).items():
                target=response.get('reference')
                if not target:continue
                local=report.get('local_mount_reference',{}).get(name)
                if local:
                    if not local['numerical_ceiling_met']:reasons.append(f'{case}: {name} exceeds the numerical connection compliance ceiling')
                    if not local.get('yield_floor_met',True):reasons.append(f'{case}: {name} yields before its CAD-derived mounting load')
                    continue
                for field,reference,tolerance,label in (
                    ('compliance_m_n','compliance_m_n',.1,'stiffness response'),
                    ('elastic_yield_proxy_n','first_yield_force_n',.15,'first-yield load')):
                    if response.get('elastic_only') and field=='elastic_yield_proxy_n':continue
                    error=abs(response[field]/target[reference]-1)
                    if error>tolerance:reasons.append(f'{case}: {name} {label} differs from reference by {error:.1%} (limit {tolerance:.0%})')
        reasons=reasons or ['Numerical calibration acceptance failed']
        emit('Calibration rejected',detail='; '.join(reasons),outcome='rejected',report=str(study/'index.html'))
    else:
        from frame_harness.progress import emit
        emit('Study finished',detail=state['status'],outcome=state['status'],report=str(study/'index.html'))


def package(job, case, output):
    from frame_harness.build import sha256, write_json
    from frame_harness.generation import load_artifact
    from build_static_frame import PACKAGE_FILES, validate_package
    check_snapshot(job)
    state=read(job/'study/calibration-study.json'); artifact=job/'study'/case/'calibration.json'
    if state['candidates'][case].get('artifact_sha256') != sha256(artifact):
        raise ValueError('Calibration artifact changed after generation')
    spec, vehicle=load_artifact(project(job), artifact)
    if not spec.get('offline_accepted') or not spec.get('geometry_valid'):
        raise ValueError('Calibration did not pass CAD and numerical acceptance')
    texture_names=list(dae_texture_assets(job/'source/mochi.dae'))
    output.mkdir(parents=True,exist_ok=False)
    target=output/'work/dist/ak1di_mochi.zip'; target.parent.mkdir(parents=True)
    shutil.copy2(job/'source/mochi_hull.off',output/'work/mochi_hull.off')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name in PACKAGE_FILES:
            z.write(vehicle if name=='mochi.jbeam' else job/'source'/name,'vehicles/mochi/'+name)
        for name in texture_names:
            z.write(job/'source'/name,'vehicles/mochi/'+name)
        from frame_harness.generation import inputs
        for source,target_name in inputs(project(job)).get('runtime_assets',{}).items():
            z.write(job/'source'/source,'vehicles/mochi/'+target_name)
    with zipfile.ZipFile(target) as z:
        validate_package(z)
        if z.read('vehicles/mochi/mochi.jbeam') != vehicle.read_bytes(): raise AssertionError('Packaging changed calibrated JBeam')
    check_snapshot(job)
    load_artifact(project(job),artifact)
    if sha256(artifact)!=state['candidates'][case]['artifact_sha256']:
        raise ValueError('Calibration artifact changed during packaging')
    qualification=state.get('acceptance',{}).get(case,{})
    quick_path=job/'study/quick-verification.json'
    quick=read(quick_path) if quick_path.exists() else None
    if quick and (quick['identity'].get('case')!=case or quick['identity'].get('artifact')!=sha256(artifact)
                  or quick['identity'].get('calibration')!=state.get('identity')):
        raise ValueError('Quick verification does not match this calibrated artifact')
    provenance=output/'calibration';provenance.mkdir()
    for name,path in [('calibration.json',artifact),('report.json',artifact.parent/'report.json'),
                      ('reference.json',job/'source/reference.json'),('snapshot.json',job/'snapshot.json'),
                      ('calibration-study.json',job/'study/calibration-study.json')]: shutil.copy2(path,provenance/name)
    for name in ('mesh-review.json','mesh-review-evidence.json','build-result.json','quick-verification.json','quick-result.json'):
        if (job/'study'/name).exists():shutil.copy2(job/'study'/name,provenance/name)
    if (job/'source/material-snapshot.json').exists():shutil.copy2(job/'source/material-snapshot.json',provenance/'material-snapshot.json')
    record=dict(format='truemesh-static-frame-build',version=1,status='succeeded',
        zip_file='work/dist/ak1di_mochi.zip',zip_sha256=sha256(target), stages=['CAD calibration','Package'],
        calibration=dict(generation=str(job),case=case,artifact_sha256=sha256(artifact),vehicle_sha256=sha256(vehicle),
                         input_sha256=spec['source_hashes'],reference=spec['reference_config'],
                         local_mount_reference_qualified=spec.get('local_mount_reference_qualified',True)),
        generation_status='succeeded',recording_status=('not_run' if not state.get('runs') else
            'completed' if all(r['status']=='completed' for r in state['runs']) and state['status'] in ('completed','completed_with_limitations') else state['status']),
        qualification_status='qualified' if qualification.get('accepted') else 'diagnostic',
        limitations=(state.get('limitations',[])+qualification.get('reasons',[]) +
            [qualification.get('qualification_scope','Fracture and mesh separation require current-generation live and rendered evidence.')]))
    record['calibration_files_sha256']={p.relative_to(output).as_posix():sha256(p) for p in provenance.iterdir()}
    if quick:
        record['quick_verification_status']=quick['status']
        if not state.get('runs'):
            record['recording_status']='completed (quick screening)' if quick['status']=='quick_passed' else quick['status']
    write_json(output/'static_frame_build.json',record)
    print('RESULT '+str(target),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['doctor','prepare','calibrate','package','verify','fixed-preview'])
    for name in ('source','output','job','game','profile','cancel-file','previous'): p.add_argument('--'+name,type=Path)
    p.add_argument('--case',help='Candidate to calibrate, verify or package; defaults to the captured SolidWorks assignments')
    p.add_argument('--resume',action='store_true')
    p.add_argument('--diagnostic',action='store_true')
    p.add_argument('--save-report',action='store_true',help='Keep full successful-run reports and raw diagnostics; failures are always retained')
    p.add_argument('--verification',choices=['quick','full'],default='full')
    a=p.parse_args(); preflight()
    if a.cancel_file: os.environ['BEAMNG_CAD_CANCEL']=str(a.cancel_file)
    if a.action=='doctor': print('PASS Python, NumPy, SciPy, Matplotlib and shared calibration package');return
    if a.action=='fixed-preview':fixed_preview(a.job,a.source)
    elif a.action=='prepare': prepare(a.source,a.output,a.previous)
    elif a.action=='package': package(a.job,a.case or ('solidworks-assigned' if (a.job/'source/material-snapshot.json').exists() else '4130-annealed'),a.output)
    else:
        calibrate(a.job,resume=a.resume or a.action=='verify',live=a.action=='verify',game=a.game,profile=a.profile,diagnostic=a.diagnostic,case=a.case,verification=a.verification,save_report=a.save_report)
        from frame_harness.retention import apply_retention
        state=read(a.job/'study/calibration-study.json')
        quick=read(a.job/'study/quick-verification.json') if a.action=='verify' and a.verification=='quick' else None
        summary=apply_retention(a.job,state,a.save_report,quick=quick)
        print('REPORT RETENTION '+summary['retention_reason']+'; freed '+str(summary['freed_bytes'])+' bytes',flush=True)


if __name__=='__main__': main()
