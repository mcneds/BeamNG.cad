"""Apply sourced constant-rate spring declarations to an immutable vehicle revision.

A series stack with unknown crossover is represented with both springs active.
Preload, damping, stops, CAD geometry and numerical mass are preserved explicitly.
"""
import argparse,copy,hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_revisions import load_baseline,canonical,package_revision
import components
LBF_PER_IN_TO_N_PER_M=4.4482216152605/.0254


def effective_rate(spec):
    values=spec['rates_lbf_per_in']
    if not values or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in values):
        raise ValueError('Positive finite hardware spring rates required')
    if spec['model']=='single' and len(values)==1:return values[0]*LBF_PER_IN_TO_N_PER_M
    if spec['model']=='series_unknown_crossover' and len(values)==2:
        return LBF_PER_IN_TO_N_PER_M/sum(1/v for v in values)
    raise ValueError('Use one spring or two active series springs with unknown crossover')


def revise(part,manifest,project,specification):
    before=copy.deepcopy(part);part=copy.deepcopy(part);m=copy.deepcopy(manifest);p=copy.deepcopy(project)
    pairs=[];changes={}
    for corner,spec in specification['corners'].items():
        if corner not in m['wheels']:raise ValueError('Unknown wheel corner: '+corner)
        rate=effective_rate(spec);w=m['wheels'][corner];pair={w['nodes']['shock_top'],w['nodes']['shock_bottom']};pairs.append(pair)
        rows=[r for r in part['beams'][1:] if isinstance(r,list) and set(r[:2])==pair]
        springs=[r for r in rows if r[-1].get('beamType')=='|BOUNDED' and r[-1].get('beamSpring',0)>0]
        dampers=[r for r in rows if r[-1].get('beamType')=='|BOUNDED' and r[-1].get('beamSpring')==0]
        supports=[r for r in rows if r[-1].get('beamType')=='|SUPPORT']
        if len(springs)!=1 or len(dampers)!=1 or len(supports)!=(1 if w.get('coilover_spring') else 0) or len(rows)!=2+len(supports):
            raise ValueError(corner+': unrecognized coilover graph')
        ride=w['ride_reference'];spring=springs[0][-1]
        spring.update(beamSpring=rate,beamPrecompression=(ride['reference_shock_length_m']+w['spring_preload_n']/rate)/ride['captured_shock_length_m'])
        part['beams']=[r for r in part['beams'] if r not in supports]
        changes[corner]=dict(before_rate_n_m=w['spring_n_m'],after_rate_n_m=rate,hardware=spec,removed_crossover_beams=len(supports))
        w.pop('coilover_spring',None);w.update(spring_n_m=rate,hardware_spring=spec,suspension_settings_source='user_spring_rates_existing_preload_and_damping')
        owner=next(c for c in p['Components'] if c.get('MvpRole')==corner.lower()+'_spring_damper')
        owner['CoiloverSpring']={'Mode':'auto'} # explicit template values below override automatic rates
        owner['SpringHardware']=spec
        physical=m['template_definition']['parameters'].setdefault('suspension_physical_settings',{})
        physical[corner]=dict(physical.get(corner,{}),spring_n_m=rate,damper_ns_m=w['damper_ns_m'],spring_preload_n=w['spring_preload_n'])
    def unrelated(value):return [r for r in value['beams'] if not(isinstance(r,list) and set(r[:2]) in pairs)]
    if unrelated(before)!=unrelated(part) or {k:v for k,v in before.items() if k!='beams'}!={k:v for k,v in part.items() if k!='beams'}:
        raise ValueError('Unrelated graph, mass, rendering or physics changed')
    m['explicit_beams']+=len(part['beams'])-len(before['beams'])
    m['template_definition']['spring_hardware']=specification
    m['template_sha256']=hashlib.sha256(canonical(m['template_definition'])).hexdigest()
    m['hardware_spring_revision']=dict(source=specification['source'],changes=changes,preload_damping_stops_unchanged=True)
    m['calibration_inputs_status']='hardware_springs_updated_numerical_plan_not_requalified'
    m.pop('verification',None);m.pop('physical_evidence',None)
    m['limitations'].append('User-supplied spring rates; rear series stack stays active without assumed crossover. Preload, dampers, stops and tires remain provisional; previous dynamic qualification does not transfer.')
    return part,m,p


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('receipt',type=Path);parser.add_argument('specification',type=Path);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    record,m,contents,snapshot=load_baseline(a.receipt);p=json.loads((a.receipt.parent/'project.snapshot.json').read_bytes());spec=json.loads(a.specification.read_bytes())
    name='vehicles/'+m['model']+'/'+m['main_jbeam'];parts=json.loads(contents[name]);part,m,p=revise(parts[m['main_part']],m,p,spec)
    parts[m['main_part']]=part;contents[name]=canonical(parts)
    info_name='vehicles/'+m['model']+'/info_base.json'
    if info_name in contents:
        info=json.loads(contents[info_name]);info['Configuration']='CAD first drive - sourced springs'
        info['Description']='Front 80 lb/in; rear 285/110 lb/in series, crossover unknown. Existing damping/preload/stops retained.'
        contents[info_name]=canonical(info)
    p['TemplateDefinitionPath']=str((a.output/'spring-template.json').resolve());m['project_fingerprint']=components.fingerprint(p)
    provenance={key:(a.receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'hardware/spring-source.json':canonical(spec),'hardware/apply-spring-specification.py':Path(__file__).read_bytes(),'hardware/parent-receipt.json':a.receipt.read_bytes()})
    if load_baseline(a.receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    package_revision(a.output,p,m,contents,provenance,a.receipt,'User spring rates; existing geometry, mass, damping, preload and stops retained')
    (a.output/'spring-template.json').write_bytes(canonical(m['template_definition']))
    print('SPRING_REVISION '+str(a.output/'manifest.json'))


if __name__=='__main__':main()
