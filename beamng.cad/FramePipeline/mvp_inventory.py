"""Reusable CAD grouping evidence, deliberately separate from vehicle qualification."""
from pathlib import Path
import hashlib
import json
import components as c


def configuration(catalog, project):
    choices=project.get('MvpTemplates') or [];selected={};ids=set(catalog['mvp_base_roles']);links=list(catalog['mvp_base_associations'])
    known={s['id'] for s in catalog['mvp_template_sets']}
    if len({v['Category'] for v in choices})!=len(choices) or any(v['Category'] not in known for v in choices):raise ValueError('Unknown or duplicate vehicle template category')
    for group in catalog['mvp_template_sets']:
        value=next((v['Template'] for v in choices if v['Category']==group['id']),group['default'])
        option=next((o for o in group['options'] if o['id']==value),None)
        if option is None:raise ValueError('Unknown '+group['label']+' template: '+value)
        selected[group['id']]=dict(id=value,label=option['label']);ids.update(option['roles']);links.extend(option['associations'])
    if project.get('Driveline'):
        from driveline import drive_role
        ids={role for role in ids if not drive_role(role)}
        ids.update(c['MvpRole'] for c in project['Components'] if drive_role(c.get('MvpRole')))
        links=[link for link in links if not drive_role(link['from_role']) and not drive_role(link['to_role'])]
    return selected,ids,links


def inventory(project, project_path=None):
    catalog_path=Path(__file__).with_name('template_catalog.json')
    catalog=json.loads(catalog_path.read_text(encoding='utf-8-sig'))
    definitions={r['id']:r for r in catalog['mvp_roles']}
    selected,active_roles,relations=configuration(catalog,project)
    for group in catalog['mvp_template_sets']:
        option=next(o for o in group['options'] if o['id']==selected[group['id']]['id'])
        for role,points in option.get('hardpoints',{}).items():definitions[role]=definitions[role]|dict(hardpoints=points)
    if 'shaft_carrier' in active_roles:
        relations.append(dict(from_role='frame',to_role='shaft_carrier',kind='mount'))
        for role in ('front_propshaft','cvt_output_shaft'):
            if role in active_roles:relations.append(dict(from_role='shaft_carrier',to_role=role,kind='review_shaft_support'))
    groups=[];errors=[];owners={}
    for component in project.get('Components',[]):
        role=component.get('MvpRole') or ('frame' if component.get('Template')=='calibrated_frame' else '')
        if role and role not in definitions:errors.append(component['Name']+': unknown MVP role '+role)
        group=dict(id=component['Id'],name=component['Name'],role=role,template=component['Template'],
                   in_current_setup=role in active_roles,
                   configuration=component.get('Configuration'),body_ids=component.get('BodyIds',[]),
                   selections=component.get('Selections',[]),geometry_directory=component.get('GeometryDirectory'),
                   surface_mass_mode=component.get('SurfaceMassMode') or 'thickness',thickness_m=component.get('Thickness') or 0,
                   visual_parent=component.get('VisualParentId'),geometry_status='missing',files_sha256={},bodies=[])
        for body in group['body_ids']:
            if body in owners:errors.append('Body '+body+' has multiple component owners')
            owners[body]=component['Id']
        try:
            if not group['geometry_directory']:raise ValueError('Refresh tagged CAD to export this group')
            root=Path(group['geometry_directory']).resolve();data=json.loads((root/'geometry.json').read_text(encoding='utf-8-sig'))
            if sorted(b['Id'] for b in data['Meshes'])!=sorted(group['body_ids']):raise ValueError('Exported body ownership differs from saved assignment')
            names=['geometry.json']+[b['File'] for b in data['Meshes']]
            if (root/'material-snapshot.json').exists():names.append('material-snapshot.json')
            for name in names:
                path=(root/name).resolve()
                if path.parent!=root:raise ValueError('Geometry input escapes its directory')
                group['files_sha256'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
            group['geometry_status']='exported';group['bodies']=data['Meshes']
            try:
                _,moments,_=c.read_geometry(component);group['mass_kg']=moments[0];group['mass_status']='ready'
                if moments[0]==0 and not group['visual_parent']:raise ValueError('Choose a physical parent for weightless surfaces')
            except ValueError as e:group['mass_status']='needs_input';group['mass_issue']=str(e)
        except (OSError,ValueError,KeyError) as e:
            group['geometry_issue']=str(e);errors.append(component['Name']+': '+str(e))
        groups.append(group)
    roles=[]
    for definition in definitions.values():
        if definition['id'] not in active_roles:continue
        assigned=[g['id'] for g in groups if g['role']==definition['id']]
        from driveline import drive_role
        if project.get('Driveline') and drive_role(definition['id']):definition=definition|dict(repeatable=True,required=False)
        state=('duplicate' if len(assigned)>1 and not definition['repeatable'] else 'tagged') if assigned else ('missing' if definition['required'] else 'optional')
        roles.append(definition|dict(status=state,components=assigned))
        if state=='duplicate':errors.append(definition['label']+': assign this role to one grouped component')
    role_groups={r['id']:r['components'] for r in roles}
    anchors=project.get('Anchors',[]);connections=project.get('Connections',[]);by_anchor={a['Id']:a for a in anchors}
    for anchor in anchors:
        if anchor.get('Status')!='resolved':errors.append(anchor['Name']+': mounting point needs repair')
    associations=[]
    for relation in relations:
        left=role_groups[relation['from_role']];right=role_groups[relation['to_role']]
        # Existing connections are evidence to inspect, never inferred proof of
        # a hinge, shaft, or powertrain device merely from matching role tags.
        candidates=[]
        for link in connections:
            a=by_anchor.get(link['AnchorA'],{}).get('ComponentId');b=by_anchor.get(link['AnchorB'],{}).get('ComponentId')
            if (a in left and b in right) or (b in left and a in right):candidates.append(link['Id'])
        associations.append(relation|dict(from_components=left,to_components=right,
                            status='review_hardpoints_and_joint' if left and right else 'awaiting_groups',candidate_connections=candidates))
    shaft_review=[]
    driveline_review=None
    if project.get('Driveline'):
        from driveline import resolve,validate
        try:
            data=validate(resolve(project),project)
            driveline_review=dict(status='references_and_topology_passed',devices=len(data['devices']),shafts=len(data['shafts']),qualification='unqualified')
        except (ValueError,KeyError,TypeError) as error:
            errors.append('Driveline: '+str(error));driveline_review=dict(status='needs_repair',issue=str(error),qualification='unqualified')
    for role in ('front_propshaft','cvt_output_shaft'):
        sections=role_groups.get(role,[])
        if len(sections)>1 and not project.get('Driveline'):
            shaft_review.append(dict(role=role,sections=sections,status='needs_reviewed_chain',
                message='Define the ordered shaft sections, their joint centres, plunge and carrier supports in the template. Assignment order is not physical order.'))
    return dict(kind='cad_component_inventory',version=1,project_path=str(project_path) if project_path else None,
                source_document=project.get('SourceDocument'),project_fingerprint=c.fingerprint(project),
                catalog_sha256=hashlib.sha256(catalog_path.read_bytes()).hexdigest(),roles=roles,components=groups,
                selected_templates=selected,outside_current_setup=[g['id'] for g in groups if g['role'] and not g['in_current_setup']],
                anchors=anchors,connections=connections,planned_associations=associations,shaft_chain_review=shaft_review,driveline_review=driveline_review,errors=errors,
                tagging_complete=not errors and all(r['status']!='missing' for r in roles),
                qualification='unqualified',limitations=['Tags identify CAD ownership only. Reviewed hardpoints, material inputs, generation and native verification are still required. Strut generation remains planned.',
                'File hashes describe the last CAD export. Refresh tagged CAD after changing the assembly before reusing the inventory.'])
