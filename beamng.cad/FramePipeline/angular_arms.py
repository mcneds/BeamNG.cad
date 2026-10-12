"""Opt-in sparse numerical wishbone experiment, gated by a nonsymmetric screen."""
import copy,hashlib,json,math
from pathlib import Path
from angular_beams import validate_references
from angular_screen import matrices,discrete_spectrum
from frame_harness.build import node_table
from vehicle_revisions import canonical,load_baseline,package_revision


def additions(part,manifest,ratio,mode='parallel',members='all'):
    if mode not in ('parallel','replace') or members not in ('all','upper','lower'):raise ValueError('Invalid angular representation selection')
    if not math.isfinite(ratio) or not 0<ratio<=(10 if mode=='replace' else 1):raise ValueError('Invalid angular stiffness ratio')
    if manifest.get('angular_arms'):raise ValueError('Angular arms have already been generated')
    result=[]
    for corner in ('FL','FR'):
        hp=manifest['wheels'][corner]['hardpoint_nodes']
        for arm in ('upper','lower'):
            if members!='all' and members!=arm:continue
            role=corner.lower()+'_'+arm+'_wishbone'
            owners=[o for o,r in manifest['component_roles'].items() if r==role]
            if len(owners)!=1 or owners[0] not in manifest['rigid_refits']:raise ValueError('One numerical rigid arm required for '+role)
            a,b,c=[hp[arm+'_'+key] for key in ('inner_front','ball','inner_rear')]
            if not {a,b,c}<=set(manifest['mass_allocations'][owners[0]]):raise ValueError('Angular constraint escapes its arm')
            existing=[r for r in part['beams'][1:] if isinstance(r,list) and set(r[:2])=={a,b}]
            if len(existing)!=1:raise ValueError('Unique normal arm leg required')
            o=existing[0][-1]
            if o.get('beamType','|NORMAL')!='|NORMAL':raise ValueError('Normal arm leg required')
            result.append([a,b,{'beamType':'|LBEAM','id3:':c,'beamSpring':o['beamSpring']*ratio,'beamDamp':0.,'beamStrength':1e30,'beamDeform':1e30}])
    shadow=copy.deepcopy(part);shadow['beams'].extend(result);validate_references(shadow)
    return result


def staged(part,manifest,ratio,mode='parallel',members='all'):
    new=additions(part,manifest,ratio,mode,members);shadow=copy.deepcopy(part)
    if mode=='parallel':shadow['beams'].extend(new)
    else:
        for replacement in new:
            index=next(i for i,row in enumerate(shadow['beams'][1:],1) if isinstance(row,list) and set(row[:2])==set(replacement[:2]))
            shadow['beams'][index]=replacement
    validate_references(shadow)
    return shadow,new


def apply(part,manifest,ratio,mode='parallel',members='all'):
    shadow,new=staged(part,manifest,ratio,mode,members)
    print('Angular wishbones: solving full nonsymmetric discrete screen',flush=True)
    screen=discrete_spectrum(*matrices(shadow,node_table(shadow)))
    if not screen['passed']:raise ValueError('Angular wishbone screen unstable: spectral radius '+str(screen['spectral_radius']))
    part['beams']=shadow['beams'];manifest['explicit_beams']+=len(new) if mode=='parallel' else 0
    manifest['angular_arms']=dict(ratio=ratio,mode=mode,members=members,beams=new,screen=screen,
        scope='Diagnostic numerical rigidity only. One angular child per selected arm, unique normal parents, no new nodes or cross-member constraints. Replace mode retains beam count. Physical spring laws, steering targets, masses and geometry unchanged. Native qualification required.')
    return manifest['angular_arms']


def build(receipt,output,ratio,mode='parallel',members='all'):
    if Path(output).exists():raise FileExistsError('Use a fresh output directory')
    receipt=Path(receipt);record,manifest,contents,snapshot=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes());files=[n for n in contents if n.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('One assembled JBeam required')
    parts=json.loads(contents[files[0]])
    if len(parts)!=1:raise ValueError('One assembled part required')
    apply(next(iter(parts.values())),manifest,ratio,mode,members)
    manifest['template_definition']['parameters'].update(wishbone_angular_ratio=ratio,wishbone_angular_mode=mode,wishbone_angular_members=members)
    manifest['template_sha256']=hashlib.sha256(canonical(manifest['template_definition'])).hexdigest()
    manifest.pop('verification',None);manifest.pop('physical_evidence',None)
    manifest.update(rendered_review_status='required',calibration_inputs_status='numerical_revision')
    contents[files[0]]=canonical(parts)
    provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'baseline-receipt.json':receipt.read_bytes(),'angular-arms.json':canonical(manifest['angular_arms'])})
    for name in ('angular_arms.py','angular_screen.py','angular_beams.py','rigid_bracing.py'):
        provenance['numerical-generator/'+name]=Path(__file__).with_name(name).read_bytes()
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    return package_revision(output,project,manifest,contents,provenance,receipt,'Sparse angular arm experiment; native qualification pending')
