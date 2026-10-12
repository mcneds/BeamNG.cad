"""Declare chassis supports before frame calibration.

Release mounts add three parent nodes at 6 mm offsets. Direct fixed mounts
reuse existing frame nodes. Articulated pivots become loaded frame nodes before
calibration, with both shell supports and inter-pivot load paths.
"""
from __future__ import annotations
import itertools
import copy
import numpy as np
from frame_harness.build import node_table, beam_table


def complete_mirror_graph(part,center_x,create_nodes=False):
    """Close declared symmetric hull topology before fitting any properties.

    Only the bare wrapped frame may acquire mirrored helper nodes. Mounts keep
    their authored positions: unpaired mounting constraints are never invented.
    CAD mass and responses are still fitted independently after this operation.
    """
    from frame_harness.torsion import table as torsions
    nodes=node_table(part);mapping={};added_nodes=0;added_beams=0;added_bars=0
    tolerance=max(np.linalg.norm(np.ptp([n['position'] for n in nodes.values()],axis=0))*1e-8,1e-9)
    for name,node in list(nodes.items()):
        if name in mapping:continue
        target=np.array(node['position']);target[0]=2*center_x-target[0]
        match=min(nodes,key=lambda n:np.linalg.norm(np.array(nodes[n]['position'])-target))
        if np.linalg.norm(np.array(nodes[match]['position'])-target)>tolerance:
            if not create_nodes:continue
            match=name+'_mirror'
            if match in nodes:raise ValueError('Mirrored helper identity already exists: '+match)
            nodes[match]=dict(position=target.tolist(),options=copy.deepcopy(node['options']))
            part['nodes'].append([match,*target.tolist(),nodes[match]['options']]);added_nodes+=1
        mapping[name]=match;mapping[match]=name
    edges={frozenset((b['a'],b['b'])) for b in beam_table(part)}
    defaults={}
    for row in list(part['beams'][1:]):
        if isinstance(row,dict):defaults.update(row);continue
        if any(n not in mapping for n in row[:2]):continue
        a,b=(mapping[n] for n in row[:2]);key=frozenset((a,b))
        if key in edges:continue
        edges.add(key);added_beams+=1
        part['beams'].append([a,b,copy.deepcopy(defaults|(row[2] if len(row)>2 else {}))])
    def angular_key(ids):
        a,b,c,d=ids
        return min((a,b,c,d),(d,b,c,a),(a,c,b,d),(d,c,b,a))
    unique={}
    for bar in torsions(part):
        key=angular_key(bar['nodes'])
        if key in unique and unique[key]['options']!=bar['options']:
            raise ValueError('Equivalent raw angular constraints have different properties')
        unique.setdefault(key,bar)
    bars=list(unique.values());seen=set(unique)
    if bars:part['torsionbars']=[['id1:','id2:','id3:','id4:']]+[[*b['nodes'],b['options']] for b in bars]
    for bar in bars:
        if any(n not in mapping for n in bar['nodes']):continue
        ids=[mapping[n] for n in bar['nodes']];key=angular_key(ids)
        if key in seen:continue
        seen.add(key);added_bars+=1
        part['torsionbars'].append([*ids,copy.deepcopy(bar['options'])])
    return dict(center_x_m=float(center_x),paired_nodes=len(mapping),added_nodes=added_nodes,
                added_beams=added_beams,added_torsionbars=added_bars)


def insert_mounts(part, declarations):
    original=node_table(part);names=list(original);positions={n:np.asarray(v['position'],float) for n,v in original.items()}
    if part.get('cadMountPatches'):raise ValueError('Frame already contains mounting patches')
    patches={};edges={tuple(sorted((b['a'],b['b']))) for b in beam_table(part)}
    def beam(a,b):
        key=tuple(sorted((a,b)))
        if key in edges:return
        edges.add(key);part['beams'].append([a,b,dict(beamSpring=150000,beamDamp=30,beamDeform=80000,beamStrength=160000)])
    # Create the loaded pivot skeleton before selecting fixed-body supports.
    # Body display names and declaration order must not change the load path.
    ordered=sorted(declarations.items(),key=lambda item:(
        0 if isinstance(item[1],dict) and item[1].get('mode')=='joint' else 1,item[0]))
    for name,declaration in ordered:
        mode=declaration.get('mode','short') if isinstance(declaration,dict) else 'short'
        point=declaration['position'] if isinstance(declaration,dict) else declaration
        if mode not in ('short','direct','joint'):raise ValueError('Unknown mounting representation: '+str(mode))
        p=np.asarray(point,float)
        if p.shape!=(3,) or not np.isfinite(p).all():raise ValueError('Invalid mount position: '+name)
        if not name.replace('_','').isalnum():raise ValueError('Invalid semantic mount name')
        loaded=[q['parents'][0] for q in patches.values() if q['mode']=='joint']
        pools=[('loaded_skeleton',loaded),('shell',names)] if mode=='direct' else [('shell',names)]
        chosen=None
        for support_source,pool in pools:
            ranked=sorted(pool,key=lambda n:np.linalg.norm(positions[n]-p))
            boundary=np.linalg.norm(positions[ranked[min(31,len(ranked)-1)]]-p) if ranked else 0
            support=[n for n in ranked if np.linalg.norm(positions[n]-p)<=boundary+1e-10]
            if len(support)<4:continue
            xyz=np.array([positions[n] for n in support]);delta=xyz-p;distance=np.linalg.norm(delta,axis=1)
            valid=distance>1e-5;distance=distance[valid];delta=delta[valid]
            support=[n for n,keep in zip(support,valid) if keep]
            if len(support)<4:continue
            candidates=np.array(list(itertools.combinations(range(len(support)),4)))
            directions=delta/distance[:,None]
            basis=directions[candidates];eigen=np.linalg.eigvalsh(np.einsum('nki,nkj->nij',basis,basis))
            # Rank alone accepts almost coplanar supports with metres of compliance.
            score=eigen[:,0]/np.mean(distance[candidates],axis=1)
            best=int(np.argmax(score))
            if eigen[best,0]>=.01:
                tied=np.flatnonzero(np.isclose(score,score[best],rtol=1e-9,atol=1e-12))
                chosen=[support[i] for i in sorted(set(candidates[tied].ravel()))];break
        if chosen is None:raise ValueError('No well-conditioned frame support near '+name)
        if mode=='joint':
            # Distribute a loaded pivot across nearby frame mass. Four parents
            # are sufficient for rank but concentrate every reaction on a few
            # light shell nodes and make the modal stiffness cap unnecessarily soft.
            boundary=np.linalg.norm(positions[support[min(11,len(support)-1)]]-p)
            chosen+= [n for n in support if n not in chosen and np.linalg.norm(positions[n]-p)<=boundary+1e-10]
        parent=[]
        # Full-rank short links, with an X-reflection-invariant locator set.
        # Three positive coordinate-axis offsets introduced a handed mount.
        length=float(declaration.get('attachment_length_m',.006)) if isinstance(declaration,dict) else .006
        if not np.isfinite(length) or not .001<=length<=.05:raise ValueError('Invalid short mounting link length')
        offsets=np.array([[np.sqrt(.75),.5,0],[-np.sqrt(.75),.5,0],[0,0,1]])*length if mode=='short' else np.zeros((1,3)) if mode=='joint' else []
        for i,offset in enumerate(offsets):
            node='mount_'+name+'_'+str(i)
            if node in positions:raise ValueError('Mount node identity collision')
            xyz=p+offset;positions[node]=xyz;parent.append(node)
            part['nodes'].append([node,*xyz.tolist(),dict(nodeWeight=.05,collision=False,selfCollision=False,group=['frame'])])
            for target in chosen:beam(node,target)
        # Each locator already has three-dimensional restraint from the four
        # frame supports. Tiny redundant edges between the locators consume the
        # modal stiffness budget and can leave the actual load path too soft.
        patches[name]=dict(position=p.tolist(),parents=parent,mode=mode,attachment_length_m=length if mode=='short' else None,
                           frame_supports=chosen,support_source=support_source,minimum_direction_eigenvalue=float(eigen[best,0]))
        if isinstance(declaration,dict) and declaration.get('reference_pair'):
            patches[name]['reference_pair']=declaration['reference_pair']
    # Loaded pivots carry appreciable mass. Connecting them only through light
    # shell locators bottlenecks transverse reactions at the modal stability cap.
    # Include their axial load paths in the fresh graph; the CAD response fit
    # determines their stiffness, rather than adding rigid links after tuning.
    joints=[p['parents'][0] for p in patches.values() if p['mode']=='joint']
    # Interior support nodes are already part of the generated frame, including
    # the points used for its global loading fixtures. Include them in the same
    # load path so a loaded interior node is not isolated behind light shell mass.
    interior=[n for n in names if original[n]['options'].get('collision') is False]
    for a,b in itertools.combinations(joints+interior,2):
        if np.linalg.norm(positions[a]-positions[b])>1e-5:beam(a,b)
    # Release fasteners transfer load through their separate parent locators.
    # Four light shell supports alone create a soft artificial foundation even
    # when the short child beams are stiff. Carry these reactions into the same
    # loaded skeleton, with values determined by the full mounting response fit.
    for patch in patches.values():
        if patch['mode']!='short':continue
        for parent in patch['parents']:
            for target in joints+interior:
                if np.linalg.norm(positions[parent]-positions[target])>1e-5:beam(parent,target)
    part['cadMountPatches']=patches
    return patches


def reference_fixtures(part,supports):
    """Hinge couples and three directional loads on every unpinned mount patch."""
    groups={}
    for patch in part.get('cadMountPatches',{}).values():
        if patch.get('reference_pair'):
            if patch.get('mode')!='joint' or len(patch['parents'])!=1:raise ValueError('Local reference requires structural joint nodes')
            groups.setdefault(patch['reference_pair'],[]).append(patch)
    result={}
    for name,pair in sorted(groups.items()):
        if len(pair)!=2:raise ValueError('A local hinge reference requires two points: '+name)
        axis=np.array(pair[1]['position'])-pair[0]['position'];length=np.linalg.norm(axis)
        if length<1e-4:raise ValueError('Coincident hinge reference points: '+name)
        axis/=length;first=np.cross(axis,np.eye(3)[np.argmin(abs(axis))]);first/=np.linalg.norm(first)
        nodes=[v['parents'][0] for v in pair]
        for index,direction in enumerate((first,np.cross(axis,first))):
            result['mount_'+name+'_'+str(index)]=dict(fixed_nodes=list(supports),load_nodes=nodes,
                load_vectors={nodes[0]:(direction*.5).tolist(),nodes[1]:(direction*-.5).tolist()})
    from frame_harness.build import node_table
    positions={n:np.asarray(v['position'],float) for n,v in node_table(part).items()}
    seen=set()
    for name,patch in sorted(part.get('cadMountPatches',{}).items()):
        nodes=sorted(set(patch['parents'] or patch['frame_supports'])-set(supports))
        key=(tuple(nodes),tuple(patch['position'])) if patch['mode']=='direct' else tuple(nodes)
        if not nodes or key in seen:continue
        seen.add(key)
        if patch['mode']=='direct':
            # Transfer a unit force at the actual body mount through axial
            # support directions. Equal forces at the parent centroid erase
            # the lever moment, especially when several mounts share roots.
            parents=patch['frame_supports'];point=np.array(patch['position'])
            directions=np.array([positions[n]-point for n in parents])
            directions/=np.linalg.norm(directions,axis=1)[:,None]
            coefficients=np.linalg.lstsq(directions.T,np.eye(3),rcond=None)[0]
            if not np.allclose(directions.T@coefficients,np.eye(3),atol=1e-10,rtol=0):
                raise ValueError('Mount reference cannot transfer a full force: '+name)
        for index,direction in enumerate(np.eye(3)):
            vectors={node:(direction/len(nodes)).tolist() for node in nodes}
            if patch['mode']=='direct':
                vectors={node:(directions[i]*coefficients[i,index]).tolist() for i,node in enumerate(parents) if node in nodes}
                # Harness force_n is the sum of applied force magnitudes,
                # including opposing forces in couples. Use that convention
                # without changing this wrench's line of action or moment.
                magnitude=sum(np.linalg.norm(v) for v in vectors.values())
                if magnitude<1e-12:continue
                vectors={node:(np.array(v)/magnitude).tolist() for node,v in vectors.items()}
            result['mount_support_'+name+'_'+str(index)]=dict(fixed_nodes=list(supports),load_nodes=nodes,
                load_vectors=vectors)
    return result


def reference_response_pairs(fixtures):
    """Pair semantic corner loads, preserving their CAD ratios, never assuming symmetry."""
    pairs=[]
    for name in sorted(fixtures):
        for left,right in (('FL','FR'),('RL','RR')):
            for prefix in ('mount_','mount_support_'):
                start=prefix+left+'_'
                if name.startswith(start):
                    other=prefix+right+'_'+name[len(start):]
                    if other in fixtures:pairs.append([name,other])
    return pairs
