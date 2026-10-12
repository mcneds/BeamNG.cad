"""Explicit diagnostic A/B: copy one corner's spring law to its axle peer.

Uses the production spring-law emitter. Preserves target preload, hardpoints,
node masses, all other connections, brakes, tires and physical assets. Optional
damping copy is a separately declared intervention. Does not edit source CAD or
claim the copied rates are measured hardware. Fresh normal generation requires
a fresh mass plan because physical spring declarations have changed.
"""
import argparse,copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_revisions import load_baseline,canonical,package_revision
from coilover_springs import rates,crossover_beam

def revise(part,manifest,project,source,target,match_damping=False):
    if source not in ('FL','FR','RL','RR') or target!=source[0]+('L' if source[1]=='R' else 'R'):
        raise ValueError('Select distinct corners on the same axle')
    original=copy.deepcopy(part);m=copy.deepcopy(manifest);p=copy.deepcopy(project);part=copy.deepcopy(part)
    source_owner=next(c for c in p['Components'] if c.get('MvpRole')==source.lower()+'_spring_damper')
    target_owner=next(c for c in p['Components'] if c.get('MvpRole')==target.lower()+'_spring_damper')
    settings=copy.deepcopy(source_owner.get('CoiloverSpring'))
    if not settings or settings.get('Mode')!='dual_rate':raise ValueError('Source must have an explicit dual-rate spring')
    wheel=m['wheels'][target];pair={wheel['nodes']['shock_top'],wheel['nodes']['shock_bottom']}
    matches=[(i,row) for i,row in enumerate(part['beams'][1:],1) if isinstance(row,list) and set(row[:2])==pair]
    if len(matches)!=(3 if wheel.get('coilover_spring') else 2):raise ValueError('Unexpected target shock graph')
    spring=next(row[-1] for _,row in matches if row[-1].get('beamType')=='|BOUNDED' and row[-1].get('beamSpring',0)>0)
    damper=next(row[-1] for _,row in matches if row[-1].get('beamType')=='|BOUNDED' and row[-1].get('beamSpring')==0)
    ride=wheel['ride_reference'];length=ride['reference_shock_length_m'];captured=ride['captured_shock_length_m']
    law=rates(settings,length,damper['shortBoundRange']);law.update(crossover_reference='Compression from the level axle ride reference',preload_mode='Original target preload retained for isolated diagnostic')
    spring.update(beamSpring=law['initial_rate_n_m'],beamPrecompression=(length+wheel['spring_preload_n']/law['initial_rate_n_m'])/captured)
    if match_damping:damper['beamDamp']=m['wheels'][source]['damper_ns_m']
    part['beams']=[row for row in part['beams'] if not (isinstance(row,list) and set(row[:2])==pair and row[-1].get('beamType')=='|SUPPORT')]
    extra=dict(beamDeform=1e30,beamStrength=1e30,breakGroup='')|crossover_beam(law)
    extra['beamPrecompression']*=length/captured
    part['beams'].append([wheel['nodes']['shock_top'],wheel['nodes']['shock_bottom'],extra])
    wheel.update(coilover_spring=law,spring_n_m=law['initial_rate_n_m'],damper_ns_m=damper['beamDamp'],
        coilover_settings_source=dict(source_component=source_owner['Id'],inherited=True,scope='Explicit diagnostic axle-pair copy; hardware unverified'))
    target_owner['CoiloverSpring']=settings
    params=m['template_definition']['parameters'];params['suspension_physical_settings'][target].update(spring_n_m=wheel['spring_n_m'],damper_ns_m=wheel['damper_ns_m'])
    m['template_sha256']=hashlib.sha256(canonical(m['template_definition'])).hexdigest()
    m['explicit_beams']+=len(part['beams'])-len(original['beams'])
    def other_beams(value):return [r for r in value['beams'] if not(isinstance(r,list) and set(r[:2])==pair)]
    if other_beams(part)!=other_beams(original) or {k:v for k,v in part.items() if k!='beams'}!={k:v for k,v in original.items() if k!='beams'}:
        raise ValueError('Revision changed unrelated physics or rendering')
    m.pop('verification',None);m.pop('physical_evidence',None)
    change=dict(source_corner=source,target_corner=target,match_damping=match_damping,preload_unchanged=True,
        scope=__doc__,qualification_status='not_qualified',before=manifest['wheels'][target],after=copy.deepcopy(wheel))
    m['coilover_pair_diagnostic']=change;m['limitations'].append('Diagnostic '+target+' spring copied from '+source+'; damping '+('copied' if match_damping else 'unchanged')+'. Native comparison pending; no hardware qualification.')
    m['calibration_inputs_status']='physical_spring_diagnostic_requires_fresh_plan_for_regeneration'
    return part,m,p,change

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('receipt',type=Path);a.add_argument('--output',required=True,type=Path)
    a.add_argument('--source',required=True);a.add_argument('--target',required=True);a.add_argument('--match-damping',action='store_true');args=a.parse_args()
    record,m,contents,snapshot=load_baseline(args.receipt);p=json.loads((args.receipt.parent/'project.snapshot.json').read_bytes())
    name='vehicles/'+m['model']+'/'+m['main_jbeam'];parts=json.loads(contents[name])
    part,m,p,change=revise(parts[m['main_part']],m,p,args.source,args.target,args.match_damping)
    parts[m['main_part']]=part;contents[name]=canonical(parts)
    provenance={key:(args.receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'diagnostic/coilover-pair.json':canonical(change),'diagnostic/revise-coilover-pair.py':Path(__file__).read_bytes(),
        'diagnostic/coilover_springs.py':(ROOT/'beamng.cad/FramePipeline/coilover_springs.py').read_bytes(),'diagnostic/parent-receipt.json':args.receipt.read_bytes()})
    if load_baseline(args.receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    package_revision(args.output,p,m,contents,provenance,args.receipt,'Explicit coilover-pair diagnostic, not calibrated hardware')
    print('Diagnostic revision: '+str(args.output/'manifest.json'))

if __name__=='__main__':main()
