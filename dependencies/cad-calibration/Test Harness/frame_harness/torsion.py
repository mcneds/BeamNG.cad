"""Four-node angular constraints in native BeamNG Nm/rad units."""
import itertools
import math
import numpy as np


def angle(points):
    a,b,c,d=np.asarray(points,float);axis=c-b;axis/=np.linalg.norm(axis)
    left=a-b;right=d-c
    left-=axis*np.dot(left,axis);right-=axis*np.dot(right,axis)
    return math.atan2(np.dot(axis,np.cross(left,right)),np.dot(left,right))


def gradient(points):
    points=np.asarray(points,float);h=max(np.linalg.norm(np.ptp(points,axis=0))*1e-6,1e-8)
    result=np.zeros((4,3))
    for i,j in itertools.product(range(4),range(3)):
        plus=points.copy();minus=points.copy();plus[i,j]+=h;minus[i,j]-=h
        change=angle(plus)-angle(minus)
        result[i,j]=math.atan2(math.sin(change),math.cos(change))/(2*h)
    return result


def table(part):
    defaults={};result=[]
    for row in part.get('torsionbars',[])[1:]:
        if isinstance(row,dict):defaults.update(row);continue
        if len(row)<4:raise ValueError('Torsion bar requires four nodes')
        result.append(dict(nodes=row[:4],options=defaults|(row[4] if len(row)>4 else {})))
    return result


def columns(positions,endpoints):
    positions=np.asarray(positions,float);result=np.zeros((3*len(positions),len(endpoints)))
    for col,ids in enumerate(endpoints):
        p=positions[ids];axis=p[2]-p[1];length=np.linalg.norm(axis)
        if len(set(ids))!=4 or length<1e-6 or min(np.linalg.norm(np.cross(p[i]-p[1],axis))/length for i in (0,3))<1e-6:
            raise ValueError('Degenerate torsion bar')
        result[:,col].reshape(-1,3)[ids]=gradient(p)
    return result


def add_frame_bracing(part):
    """Declare broad angular load paths before the immutable-graph CAD fit.

    Three reference triangles cover distinct directions. Reject short or nearly
    axis-aligned levers; native torsion bars become ill-conditioned there.
    Consecutive axial edges preserve native break-on-support-failure behavior.
    """
    from .build import node_table,beam_table
    if table(part):raise ValueError('Frame already has angular bracing')
    nodes=node_table(part);names=list(nodes);xyz=np.array([nodes[n]['position'] for n in names])
    seeds=[];minimum=np.linalg.norm(np.ptp(xyz,axis=0))*.04
    for axis in range(3):
        first=int(np.argmin(xyz[:,axis]));second=int(np.argmax(xyz[:,axis]));line=xyz[second]-xyz[first]
        third=int(np.argmax(np.linalg.norm(np.cross(line,xyz-xyz[first]),axis=1)))
        seeds.append([first,second,third])
    rows=[];seen=set();edges={frozenset([b['a'],b['b']]) for b in beam_table(part)}
    for target in range(len(names)):
        for basis in seeds:
            if target in basis:continue
            candidates=[]
            for a,b,c in itertools.permutations(basis):
                axis=xyz[c]-xyz[b];length=np.linalg.norm(axis)
                if length<minimum:continue
                lever=[xyz[a]-xyz[b],xyz[target]-xyz[c]]
                arms=[np.linalg.norm(np.cross(v,axis))/length for v in lever]
                sine=[arm/np.linalg.norm(v) for arm,v in zip(arms,lever)]
                if min(arms)>minimum and min(sine)>.4:candidates.append((min(arms),[a,b,c,target]))
            if not candidates:continue
            _,ids=max(candidates,key=lambda v:v[0]);key=tuple(ids)
            if key in seen:continue
            seen.add(key);bar=[names[i] for i in ids]
            rows.append([*bar,dict(spring=100.,damp=0.,deform=1000.,strength=2000.)])
            for a,b in zip(bar,bar[1:]):
                pair=frozenset([a,b])
                if pair not in edges:
                    edges.add(pair);part['beams'].append([a,b,dict(beamSpring=15000.,beamDamp=2.,beamDeform=80000.,beamStrength=160000.)])
    # Global triangles alone couple every mount's angular response to distant
    # shell points. Add independent angular energies within each fixed mount's
    # actual support cluster before calibration; the response fit selects their
    # positive stiffnesses under the same assembled modal cap.
    def angular_key(ids):
        a,b,c,d=ids
        return min((a,b,c,d),(d,b,c,a),(a,c,b,d),(d,c,b,a))
    local_seen={angular_key(row[:4]) for row in rows};local_count=0
    index={n:i for i,n in enumerate(names)}
    for patch in part.get('cadMountPatches',{}).values():
        if patch.get('mode')!='direct':continue
        for group in itertools.combinations(sorted(set(patch['frame_supports'])),4):
            for bar in itertools.permutations(group):
                key=angular_key(bar)
                if key in local_seen:continue
                p=xyz[[index[n] for n in bar]];axis=p[2]-p[1];length=np.linalg.norm(axis)
                if length<minimum:continue
                levers=[p[0]-p[1],p[3]-p[2]]
                arms=[np.linalg.norm(np.cross(v,axis))/length for v in levers]
                if min(arms)<=minimum or min(arm/np.linalg.norm(v) for arm,v in zip(arms,levers))<=.4:continue
                local_seen.add(key);local_count+=1
                rows.append([*bar,dict(spring=100.,damp=0.,deform=1000.,strength=2000.)])
                for a,b in zip(bar,bar[1:]):
                    pair=frozenset([a,b])
                    if pair not in edges:
                        edges.add(pair);part['beams'].append([a,b,dict(beamSpring=15000.,beamDamp=2.,beamDeform=80000.,beamStrength=160000.)])
    if rows:part['torsionbars']=[['id1:','id2:','id3:','id4:'],*rows]
    return dict(count=len(rows),minimum_lever_m=float(minimum),minimum_lever_sine=.4,
                local_mount_count=local_count,
                scope='Angular numerical frame constraints; properties require fresh CAD response calibration')
