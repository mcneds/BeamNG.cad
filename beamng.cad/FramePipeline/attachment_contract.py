"""Explicit fastener ownership and failure groups, shared by both build routes."""
from __future__ import annotations
import hashlib
import math
import numpy as np


def release_group(connection, child):
    if connection.get('Template') == 'fixed':
        if connection.get('ReleaseSet'):raise ValueError('A non-breaking attachment cannot belong to a release set')
        return ''
    if connection.get('Template') != 'breakable_fastener':raise ValueError('Unsupported attachment failure behavior')
    key=connection.get('ReleaseSet') or connection['Id']
    # Sets are scoped to a child. Two panels using the same friendly name cannot
    # release each other. Persistent IDs, never list indices, define membership.
    return 'fastener_'+hashlib.sha256((child+'|'+key).encode()).hexdigest()[:24]


def settings(connection, child):
    spring=float(connection.get('Spring') or 0);damping=float(connection.get('Damping') or 0)
    strength=float(connection.get('Strength',4000));length=float(connection.get('AttachmentLength') or .006)
    if not all(math.isfinite(v) and v>=0 for v in (spring,damping,strength)) or strength<=0:
        raise ValueError('Fastener needs finite non-negative spring/damping and positive per-beam strength')
    if not math.isfinite(length) or not .001<=length<=.05:raise ValueError('Fastener connector length must be between 1 and 50 mm')
    return dict(group=release_group(connection,child),spring=spring,damping=damping,strength=strength,length=length)


def resolve(project):
    anchors={a['Id']:a for a in project.get('Anchors',[])}
    owners={c['Id']:c for c in project.get('Components',[])}
    result=[];seen=set()
    for connection in project.get('Connections',[]):
        if connection['Id'] in seen:raise ValueError('Duplicate fastener identity')
        seen.add(connection['Id'])
        try:a,b=anchors[connection['AnchorA']],anchors[connection['AnchorB']]
        except KeyError as error:raise ValueError('Fastener references a missing mounting point') from error
        if a['ComponentId']==b['ComponentId']:raise ValueError('Fastener must connect two different physical components')
        for anchor in (a,b):
            if anchor['ComponentId'] not in owners:raise ValueError('Fastener owner no longer exists')
            p=np.asarray(anchor.get('Position'),float)
            if anchor.get('Status')!='resolved' or p.shape!=(3,) or not np.isfinite(p).all():raise ValueError('Repair mounting point '+anchor['Name'])
            if owners[anchor['ComponentId']].get('Representation')=='visual_only':raise ValueError('Visual-only components cannot own physical fasteners')
            if anchor.get('GeneratedSource')=='auto_connect':
                from auto_connect import geometry_hash
                if anchor.get('GeometryHash')!=geometry_hash(owners[anchor['ComponentId']]):raise ValueError('Auto-connect mounting geometry changed; preview again: '+anchor['Name'])
        # Editor endpoint order is the parent/child contract. Never silently swap
        # it based on which generated node happens to exist.
        parent,child=a['ComponentId'],b['ComponentId']
        config=settings(connection,child)
        if np.linalg.norm(np.array(a['Position'])-b['Position'])>.001:
            raise ValueError(connection['Name']+': mate mounting sites within 1 mm; a fastener is not a long structural link')
        result.append(dict(id=connection['Id'],name=connection['Name'],parent=parent,child=child,
                           position=b['Position'],parent_position=a['Position'],support_position=connection.get('SupportPosition'),normal=connection.get('Normal'),release_set=connection.get('ReleaseSet') or '',**config))
    return result


def audit_release(part,mounts,node_owners,mesh_bindings=None):
    """Fail closed when a nominally detachable boundary contains hidden ties.

    Contact triangles stay within their component. Other mechanical constraints
    crossing a release boundary must be declared fastener edges; deleting only
    normal beams is not sufficient when torsion bars or hydros still join it.
    """
    from components import expand
    from frame_harness.build import node_table
    detachable={m['child'] for m in mounts if m.get('group')}
    declared={frozenset(edge):m for m in mounts for edge in m['edges']}
    for row,options in expand(part['beams']):
        a,b=row[:2];oa,ob=node_owners[a],node_owners[b]
        if oa==ob or not ({oa,ob}&detachable):continue
        edge=frozenset((a,b))
        if edge not in declared:raise ValueError('Undeclared structural tether across detachable boundary: '+a+'/'+b)
        if options.get('breakGroup','')!=declared[edge]['group']:raise ValueError('Fastener release membership differs from manifest')
    for section,count in [('hydros',2),('torsionbars',4),('triangles',3)]:
        for row in part.get(section,[])[1:]:
            if not isinstance(row,list):continue
            owners={node_owners[n] for n in row[:count] if n in node_owners}
            if len(owners)>1 and owners&detachable:raise ValueError('Cross-component '+section+' prevents independent panel release')
    rails=part.get('rails',{})
    for row,options in expand(part.get('slidenodes',[['id:','railName']])):
        name,rail=row[:2];links=rails.get(rail,{}).get('links:',[])
        owners={node_owners[n] for n in [name,*links] if n in node_owners}
        if len(owners)>1 and owners&detachable:raise ValueError('Cross-component slidenodes prevent independent panel release')
    for child in detachable:
        names={n for n,owner in node_owners.items() if owner==child}
        if not names:raise ValueError('Detachable component has no independent physical nodes')
        if mesh_bindings is not None:
            groups=set(mesh_bindings.get(child,[]))
            if not groups or any(groups&set(v.get('options',{}).get('group',[])) for n,v in node_table(part).items() if n not in names):
                raise ValueError('Detachable mesh is bound to nodes outside its component')
    return dict(status='passed',detachable_components=sorted(detachable),fasteners=len(mounts))


def prepare_points(fixed,mounts,frame):
    locators={}
    # Verify that each mounted component reaches the frame. Retaining a cycle
    # of floating brackets is not equivalent to mounting them to ground.
    attached={frame}
    while True:
        expanded=attached|{m['child'] for m in mounts if m['parent'] in attached}
        if expanded==attached:break
        attached=expanded
    if set(fixed)-attached:raise ValueError('Mount parent chain does not reach the frame: '+', '.join(sorted(set(fixed)-attached)))
    for owner,points in fixed.items():
        xyz=np.asarray(points,float)
        if len(xyz)<3 or np.linalg.matrix_rank(xyz-xyz[0],tol=1e-8)<2:
            raise ValueError(owner+': use at least three separated non-collinear fastener sites for a fixed mounted component')
    for m in mounts:
        if m['parent']==frame:continue
        if m['parent'] not in fixed:raise ValueError('Parent needs an explicit supported physical mount representation: '+m['parent'])
        offsets=np.array([[np.sqrt(.75),.5,0],[-np.sqrt(.75),.5,0],[0,0,1]])*m['length']
        points=fixed[m['parent']];start=len(points)
        points.extend((np.array(m['position'])+offsets).tolist())
        locators[m['id']]=[m['parent']+'_mount_'+str(start+i) for i in range(3)]
    return locators


def connect(graph,mounts,parent_locators):
    for m in mounts:
        child=m['child']+'_mount_'+str(m['index'])
        if child not in graph.nodes:raise ValueError('Fastener child has no independent physical mass: '+m['name'])
        direct=m['parent']==graph.frame_owner and not m['group']
        if m['parent']==graph.frame_owner:
            patch=graph.part.get('cadMountPatches',{}).get('fastener_'+m['id'])
            if not patch or patch['mode']!=('direct' if direct else 'short') or not np.allclose(patch['position'],m['position'],atol=1e-7,rtol=0):
                raise ValueError('Regenerate/calibrate the frame with the reviewed fastener plan: '+m['name'])
            if not direct and abs(patch.get('attachment_length_m',.006)-m['length'])>1e-9:raise ValueError('Fastener length changed after calibration')
            # Permanent restraints distribute their reaction through the
            # existing frame supports. Extra tiny frame cages are required only
            # for the deliberately short, separate breakaway connectors.
            parents=patch['frame_supports'] if direct else patch['parents']
        else:parents=parent_locators[m['id']]
        edges=[]
        for parent in parents:
            ma=graph.nodes[parent]['options']['nodeWeight'];mb=graph.nodes[child]['options']['nodeWeight'];reduced=ma*mb/(ma+mb)
            spring=m['spring'] or (2000000. if direct else min(180000.,min(ma,mb)*(2*math.pi*120)**2/6))
            damping=m['damping'] or (120. if direct else 1.2*math.sqrt(spring*reduced))
            graph.beam(parent,child,beamSpring=spring,beamDamp=damping,beamStrength=m['strength'] if m['group'] else 1e30,
                       beamDeform=1e30,breakGroup=m['group'],breakGroupType=0,disableMeshBreaking=True,disableTriangleBreaking=True)
            edges.append([parent,child])
        graph.mounts.append(dict(id=m['id'],name=m['name'],group=m['group'],parent=m['parent'],child=m['child'],edges=edges,
                                 attachment_length_m=None if direct else m['length'],representation='permanent_frame_restraint' if direct else 'short_connector',
                                 per_beam_strength_n=m['strength'],release_scope='independent' if not m.get('release_set') else 'linked'))
        if direct:
            graph.joints.append(dict(id=m['id'],kind='spherical',parent=m['parent'],child=m['child'],nodes=[*parents,child]))
        # These are releasable point restraints, deliberately absent from the
        # permanent-joint telemetry contract once their fastener has failed.
