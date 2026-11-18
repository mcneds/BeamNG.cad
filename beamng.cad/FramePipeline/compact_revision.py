"""Regenerate only explicitly fixed components using the compact rigid generator."""
import copy
import json
from pathlib import Path
import tempfile
import numpy as np
import components as c
from compact_rigid import generate
from fixed_structure import attach
from rigid_bracing import budget_connections
from rigid_visuals import render
from coilover_visuals import replace_rows
from prepare_frame import write_dae,dae_materials
from appearance_textures import dae_texture_assets
from vehicle_revisions import load_baseline,package_revision,canonical,appearance_meshes
from frame_harness.build import node_table,beam_table


def revise(receipt,owners,output):
    receipt=Path(receipt);record,manifest,contents,_=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_text());prefix='vehicles/'+manifest['model']+'/'
    key=prefix+manifest['main_jbeam'];parts=json.loads(contents[key]);part=parts[manifest['main_part']]
    original=copy.deepcopy(part);audit={};removed_all=set();new_all=set();new_options=[]
    with tempfile.TemporaryDirectory(prefix='compact-render-',dir=Path(output).parent) as scratch:
        for owner in owners:
            if owner not in manifest.get('fixed_attachment_contract',{}):raise ValueError('Compact revision requires an explicitly fixed attachment: '+owner)
            if any(j.get('child')==owner and j.get('kind') not in ('spherical','fixed') for j in manifest.get('joints',[])):
                raise ValueError('Articulated components require regeneration of their joint contract')
            component=next(v for v in project['Components'] if v['Id']==owner);component['Method']='rigid'
            points=manifest['template_definition']['fixed_mounts'][owner]
            anchors=[dict(Id=str(i),Status='resolved',Position=p) for i,p in enumerate(points)]
            replacement,report=generate(component,anchors,c.read_geometry(component)[1])
            removed={n for n,v in manifest['nodes'].items() if v.get('component')==owner};removed_all|=removed
            if removed!=set(manifest['mass_allocations'][owner]):raise ValueError('Shared mass nodes cannot be replaced independently')
            before_nodes=node_table(part)
            weights=np.array([before_nodes[n]['mass'] for n in sorted(removed)])
            xyz=np.array([before_nodes[n]['position'] for n in sorted(removed)])
            center=weights@xyz/weights.sum();relative=xyz-center
            inertia=sum(m*(p@p*np.eye(3)-np.outer(p,p)) for m,p in zip(weights,relative))
            target=c.read_geometry(component)[1]
            if not (np.isclose(weights.sum(),target[0],rtol=1e-7) and np.allclose(center,target[1],atol=1e-7,rtol=0) and np.allclose(inertia,target[2],atol=1e-8,rtol=1e-6)):
                raise ValueError('Captured CAD properties differ from the baseline; use full recalibration')
            # Reject references that this operation cannot safely rewrite.
            for section,value in part.items():
                if section in ('nodes','beams','triangles','torsionbars','props','flexbodies','cadMountPatches'):continue
                def referenced(v):
                    if isinstance(v,str):return v in removed
                    if isinstance(v,dict):return any(referenced(x) for pair in v.items() for x in pair)
                    if isinstance(v,list):return any(referenced(x) for x in v)
                    return False
                if referenced(value):raise ValueError('Component is referenced by '+section+'; regenerate its complete mechanism')
            if any((b['a'] in removed) != (b['b'] in removed) and (b['b'] if b['a'] in removed else b['a']) not in manifest['chassis_nodes'] for b in beam_table(part)):
                raise ValueError('Component has a non-frame connection')
            for section,width in (('nodes',1),('beams',2),('triangles',3),('torsionbars',4)):
                rows=part.get(section)
                if rows is not None:part[section]=rows[:1]+[r for r in rows[1:] if not isinstance(r,list) or not removed.intersection(r[:width])]
                part.setdefault(section,replacement.get(section,[[]])[:1]).extend(replacement.get(section,[])[1:])
            names=[r[0] for r in replacement['nodes'][1:]];new_all.update(names)
            new_options.extend(r[-1] for r in replacement['beams'][1:])
            rows,contract=attach(part,names,manifest['chassis_nodes']);new_options.extend(r[-1] for r in rows)
            manifest['fixed_attachment_contract'][owner]=contract
            allocations={r[0]:r[-1]['nodeWeight'] for r in replacement['nodes'][1:]};manifest['mass_allocations'][owner]=allocations
            for n in removed:manifest['nodes'].pop(n)
            for row in replacement['nodes'][1:]:manifest['nodes'][row[0]]=dict(position=row[1:4],mass_kg=row[-1]['nodeWeight'],component=owner)
            manifest['component_reports'][owner]=report['mass']|dict(representation=report,render_as_rigid_prop=True)
            manifest.get('rigid_refits',{}).pop(owner,None)
            meshes,source=appearance_meshes(component);mesh_names=[manifest['model']+'__compact_'+owner+'_'+str(i) for i in range(len(meshes))]
            old_meshes=manifest['component_meshes'][owner];replace_rows(part,old_meshes,[],[])
            rendered,render_report=render(owner,part,{owner:allocations},meshes,mesh_names,component.get('SteeringAppearance'))
            manifest.setdefault('rigid_render',{})[owner]=render_report;manifest['component_meshes'][owner]=mesh_names
            path=Path(scratch)/(owner+'.dae');write_dae(path,[(r|dict(Id=mesh_names[i]),t) for i,(r,t) in enumerate(rendered)])
            contents[prefix+'compact_'+owner+'.dae']=path.read_bytes();contents.update({prefix+n:d for n,d in dae_texture_assets(path).items()})
            materials=json.loads(contents[prefix+'main.materials.json']);materials.update(dae_materials(path.read_bytes(),prefix));contents[prefix+'main.materials.json']=canonical(materials)
            manifest.setdefault('appearance_inputs',{})[owner]=source
            audit[owner]=dict(previous_nodes=len(removed),new_nodes=len(names),mass=report['mass'],collision='disabled for rigid mass quadrature',mounts_preserved=points)
        limit=float(manifest.get('connection_budget',{}).get('step_limit',3.2))
        if not 0<limit<=3.6:raise ValueError('Unsupported baseline timestep budget')
        manifest['compact_component_budget']=budget_connections(part,node_table(part),new_options,limit=limit)
        manifest['previous_connection_budget']=manifest.get('connection_budget')
        manifest['connection_budget']=manifest['compact_component_budget']
        # Only selected component constraints may change. Suspension/drivetrain stay exact.
        for section in original:
            if section in ('nodes','beams','triangles','torsionbars','props','flexbodies'):continue
            if original[section]!=part[section]:raise ValueError('Compact revision changed unrelated '+section)
        for section,width in (('nodes',1),('beams',2),('triangles',3),('torsionbars',4)):
            def retained(value,excluded):return [r for r in value.get(section,[])[1:] if not isinstance(r,list) or not excluded.intersection(r[:width])]
            if retained(original,removed_all)!=retained(part,new_all):raise ValueError('Compact revision changed unrelated '+section)
        manifest['explicit_beams']=len(beam_table(part));contents[key]=canonical(parts)
        manifest.update(compact_component_revision=audit,qualification_status='diagnostic',rendered_review_status='required')
        project['LastBuildReceipt']=str(receipt)
        provenance={'baseline-receipt.json':receipt.read_bytes(),'compact-component-audit.json':canonical(audit)}
        return package_revision(output,project,manifest,contents,provenance,receipt,'Compact fixed components preserve CAD mass, COM, inertia and declared mounts; native revalidation required')
