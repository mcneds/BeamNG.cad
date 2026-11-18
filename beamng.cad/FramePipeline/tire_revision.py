"""Immutable application of the production tire-resolution stage to a package."""
import copy,hashlib,json
from pathlib import Path
from tire_resolution import DEFAULT_RAYS,refine,validate_rays
from vehicle_revisions import load_baseline,canonical,package_revision

def revise(part,manifest,rays=DEFAULT_RAYS):
    validate_rays(rays);part=copy.deepcopy(part);m=copy.deepcopy(manifest);changes={}
    for row in part['pressureWheels'][1:]:
        if not isinstance(row,list):continue
        corner=row[0]
        if corner in changes or corner not in m['wheels']:raise ValueError('Ambiguous pressure wheel '+corner)
        row[-1],audit=refine(row[-1],rays);changes[corner]=audit
        w=m['wheels'][corner]
        for key in ('hub_nodes','tread_nodes','reinforcement_l_beams'):w['tire_contract'][key]=2*rays
        w['mass_allocation']['contact_resolution']=audit
    if set(changes)!=set(m['expected_wheel_names']):raise ValueError('Incomplete wheel refinement')
    m['template_definition']['parameters']['tire_rays']=rays
    m['template_sha256']=hashlib.sha256(canonical(m['template_definition'])).hexdigest()
    m['tire_resolution_revision']=dict(corners=changes,suspension_unchanged=True,
        scope='Native pressure-wheel contact refinement; CAD geometry, support masses, springs, dampers, preload and stops unchanged. Tire material response remains provisional.')
    m.pop('verification',None);m.pop('physical_evidence',None)
    m['limitations'].append('Tire contact resolution changed; prior native qualification does not transfer. Carcass compliance remains provisional.')
    return part,m

def build(receipt,output,rays=DEFAULT_RAYS):
    receipt=Path(receipt);output=Path(output)
    record,m,contents,snapshot=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes())
    name='vehicles/'+m['model']+'/'+m['main_jbeam'];parts=json.loads(contents[name])
    before=copy.deepcopy(parts[m['main_part']]);part,m=revise(before,m,rays)
    if {k:v for k,v in before.items() if k!='pressureWheels'}!={k:v for k,v in part.items() if k!='pressureWheels'}:
        raise ValueError('Tire resolution changed unrelated physics')
    parts[m['main_part']]=part;contents[name]=canonical(parts)
    project['TemplateDefinitionPath']=str((output/'tire-template.json').resolve())
    if project.get('JointWorkspace',{}).get('Mode')=='authored':
        project['JointWorkspace'].setdefault('Parameters',{})['tire_rays']=rays
    import components
    m['project_fingerprint']=components.fingerprint(project)
    provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'tire-resolution/parent-receipt.json':receipt.read_bytes(),
        'tire-resolution/changes.json':canonical(m['tire_resolution_revision']),
        'tire-resolution/tire_revision.py':Path(__file__).read_bytes(),
        'tire-resolution/tire_resolution.py':Path(__file__).with_name('tire_resolution.py').read_bytes()})
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during refinement')
    package_revision(output,project,m,contents,provenance,receipt,'Refined tire contacts; suspension laws and CAD geometry retained')
    (output/'tire-template.json').write_bytes(canonical(m['template_definition']))
