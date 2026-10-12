"""Opt-in damping of existing, exclusively owned wishbone strain constraints.

No springs or graph edits. The unfiltered damping envelope is screened at the
rest pose; this is not a nonlinear/native stability certificate.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from frame_harness.build import node_table
from rigid_bracing import budget_connections
from vehicle_revisions import canonical,load_baseline,package_revision


def apply(part,manifest,ratio,cutoff=25.,step_limit=3.2):
    ratio=float(ratio);cutoff=float(cutoff)
    if not math.isfinite(ratio) or not 0<ratio<=2:raise ValueError('Strain damping ratio must be in (0,2]')
    if not math.isfinite(cutoff) or not 25<=cutoff<=100:raise ValueError('Validated cutoff range is 25 to 100 Hz')
    if not math.isfinite(step_limit) or not 3.2<=step_limit<=3.6:raise ValueError('Experimental envelope limit must be in [3.2,3.6]')
    original=copy.deepcopy(part);shadow=copy.deepcopy(part);nodes=node_table(part)
    allocations={o:set(v) for o,v in manifest['mass_allocations'].items()}
    owners={o for o,r in manifest['component_roles'].items() if r and r.endswith('_wishbone')}
    groups=shadow.pop('cadConstraintGroups',{})
    protected={frozenset(pair) for group in groups.values() for pairs in group.values() for pair in pairs}
    selected=[];defaults={};seen=set()
    for index,row in enumerate(shadow['beams'][1:],1):
        if isinstance(row,dict):defaults.update(row);continue
        pair=frozenset(row[:2]);matches=[o for o,n in allocations.items() if pair<=n]
        if len(matches)!=1 or matches[0] not in owners:continue
        options=defaults|(row[-1] if isinstance(row[-1],dict) else {})
        if len(row) not in (2,3) or (len(row)==3 and not isinstance(row[-1],dict)):raise ValueError('Unsupported strain beam row')
        if pair in seen:raise ValueError('Duplicate owned strain beam')
        seen.add(pair)
        if pair in protected or options.get('beamType','|NORMAL')!='|NORMAL':raise ValueError('Strain damping overlaps a physical spring')
        if options.get('dampCutoffHz',0):raise ValueError('Start from an unfiltered baseline')
        ma,mb=[float(nodes[n]['options']['nodeWeight']) for n in row[:2]]
        spring=float(options.get('beamSpring',0))
        if min(ma,mb,spring)<=0 or not all(math.isfinite(x) for x in (ma,mb,spring)):raise ValueError('Invalid strain beam mass or stiffness')
        requested=min(2*ratio*math.sqrt(spring*ma*mb/(ma+mb)),min(ma,mb)/.0005)
        # Screen fixed K plus adjustable C; analysis-only parallel columns never
        # enter the package. Native filtered force magnitude <= c*abs(velocity).
        shadow['beams'][index]=row[:2]+[options|{'beamDamp':0.}]
        selected.append(dict(index=index,owner=matches[0],nodes=row[:2],requested=requested))
    if not selected:raise ValueError('No exclusively owned wishbone strain beams')
    original_count=len(shadow['beams']);adjustable=[]
    for entry in selected:
        options=dict(beamType='|NORMAL',beamSpring=0.,beamDamp=entry['requested'],dampCutoffHz=0.)
        shadow['beams'].append(entry['nodes']+[options]);adjustable.append(options)
    budget=budget_connections(shadow,node_table(shadow),adjustable,limit=step_limit)
    if any(shadow.get(k)!=original.get(k) for k in original if k not in ('beams','cadConstraintGroups')):
        raise ValueError('Envelope screening changed another physical constraint')
    if len(shadow['beams'])!=original_count+len(selected):raise ValueError('Unexpected screen graph change')
    for entry,options in zip(selected,adjustable):
        index=entry.pop('index');row=part['beams'][index]
        updated=dict(row[-1]) if isinstance(row[-1],dict) else {}
        updated.update(beamDamp=options['beamDamp'],dampCutoffHz=cutoff)
        part['beams'][index]=row[:2]+[updated]
        entry['exported_damping_ns_m']=options['beamDamp']
    manifest['filtered_strain_damping']=dict(ratio=ratio,cutoff_hz=cutoff,beams=selected,unfiltered_envelope=budget,
        scope='Existing exclusively owned wishbone beams only. K, mass, topology, coilovers and targets unchanged. Rest-pose envelope screening; native motion and stability checks required.')
    return manifest['filtered_strain_damping']


def build(receipt,output,ratio=None,cutoff=25.,step_limit=3.2,fixed_limit=None):
    receipt=Path(receipt);record,manifest,contents,snapshot=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes())
    files=[n for n in contents if n.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('One assembled JBeam required')
    parts=json.loads(contents[files[0]])
    if len(parts)!=1:raise ValueError('One assembled part required')
    if ratio is None and fixed_limit is None:raise ValueError('Choose an explicit damping conditioning stage')
    if fixed_limit is not None:
        from fixed_strain_damping import apply as apply_fixed
        apply_fixed(next(iter(parts.values())),manifest,fixed_limit)
        manifest['template_definition']['parameters']['fixed_damping_step_limit']=fixed_limit
    if ratio is not None:
        apply(next(iter(parts.values())),manifest,ratio,cutoff,step_limit)
        manifest['template_definition']['parameters'].update(wishbone_filtered_damping_ratio=ratio,wishbone_damping_cutoff_hz=cutoff,filtered_strain_step_limit=step_limit)
    manifest['template_sha256']=hashlib.sha256(canonical(manifest['template_definition'])).hexdigest()
    manifest.pop('verification',None);manifest.pop('physical_evidence',None)
    manifest.update(rendered_review_status='required',calibration_inputs_status='numerical_revision')
    contents[files[0]]=canonical(parts)
    provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'baseline-receipt.json':receipt.read_bytes(),'strain-damping.json':canonical({k:manifest[k] for k in ('fixed_strain_damping','filtered_strain_damping') if k in manifest})})
    for file in ('filtered_strain_damping.py','fixed_strain_damping.py','rigid_bracing.py'):
        provenance['numerical-generator/'+file]=Path(__file__).with_name(file).read_bytes()
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    return package_revision(output,project,manifest,contents,provenance,receipt,'Filtered internal strain damping; native qualification pending')
