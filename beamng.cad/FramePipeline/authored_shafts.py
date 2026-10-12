"""Compile ordered supported shaft sections from reviewed endpoint bindings."""
import numpy as np


def compile_chains(project,definition,values,parameters):
    workspace=project['JointWorkspace'];bindings={b['Request']:b for b in workspace['Bindings']}
    joints={j['Id']:j for j in workspace['Joints']};components={c['Id']:c for c in project['Components']}
    chains={}
    for role in ('front_propshaft','cvt_output_shaft'):
        sections=[c for c in components.values() if c.get('MvpRole')==role]
        if len(sections)<2:continue
        vertices=[];edges=[]
        for section in sections:
            ends=[]
            for suffix in ('input_joint','output_joint'):
                key=section['Id']+'.'+suffix;b=bindings.get(key,{})
                joint=joints.get(b.get('JointId'))
                if not joint or joint.get('Status')!='approved' or joint.get('Kind') not in ('spherical','revolute','cylindrical'):
                    raise ValueError(section['Name']+': bind both ends to reviewed joints on their supporting housings/carrier')
                other={joint['Parent'],joint['Child']}-{section['Id']}
                if len(other)!=1:raise ValueError('Shaft endpoint joint has ambiguous ownership')
                parent=other.pop()
                if parent not in definition['fixed_mounts']:raise ValueError('Each shaft joint needs an explicitly mounted housing or carrier')
                point=np.asarray(values[key],float)
                matching=[i for i,v in enumerate(vertices) if v['parent_component']==parent and np.linalg.norm(np.array(v['position'])-point)<1e-5]
                if len(matching)>1:raise ValueError('Ambiguous shaft joint position')
                if matching:index=matching[0]
                else:index=len(vertices);vertices.append(dict(position=point.tolist(),parent_component=parent))
                ends.append(index)
            if ends[0]==ends[1]:raise ValueError('Shaft section endpoints coincide')
            edges.append((section,ends))
        degree={i:sum(i in e for _,e in edges) for i in range(len(vertices))}
        if list(degree.values()).count(1)!=2 or any(d not in (1,2) for d in degree.values()):raise ValueError(role+': shaft sections must form one unbranched chain')
        start_role='rear_final_drive' if role=='front_propshaft' else 'cvt'
        starts=[i for i,d in degree.items() if d==1 and components[vertices[i]['parent_component']].get('MvpRole')==start_role]
        if len(starts)!=1:raise ValueError(role+': bind the input to its drivetrain housing')
        ordered=[vertices[starts[0]]];segments=[];current=starts[0];remaining=edges.copy()
        while remaining:
            choices=[e for e in remaining if current in e[1]]
            if len(choices)!=1:raise ValueError(role+': shaft chain is disconnected or branches')
            section,ends=choices[0];remaining.remove(choices[0]);current=ends[1] if ends[0]==current else ends[0]
            ordered.append(vertices[current]);segments.append(dict(component=section['Id'],plunge_m=float(parameters.get('shaft.'+section['Id']+'.plunge_m',0))))
        chains[role]=dict(role=role,joints=ordered,segments=segments)
    return chains
