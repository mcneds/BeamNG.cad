"""Compare native prop transforms with the recorded steering electric and CAD pivot."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

LABELS=('neutral','left','right','return','low-left','low-right','medium-left','medium-right')


def pose_error(binding,manifest,snapshot):
    ids=binding['nodes'];rest=np.array([manifest['nodes'][n]['position'] for n in ids])
    live=np.array([snapshot['reference_nodes'][n] for n in ids]);a=rest.mean(0);b=live.mean(0)
    u,_,vt=np.linalg.svd((rest-a).T@(live-b));rotation=vt.T@u.T
    if np.linalg.det(rotation)<0:vt[-1]*=-1;rotation=vt.T@u.T
    steering=binding['steering'];basis=np.array(steering['basis']);pivot=np.array(steering['Pivot'])
    expected_rotation=rotation@basis@Rotation.from_euler('z',snapshot['steering_degrees'],degrees=True).as_matrix()
    expected_pivot=(pivot-a)@rotation.T+b
    actual=np.array(snapshot['columns']);error=Rotation.from_matrix(expected_rotation.T@actual[:3].T).magnitude()
    return dict(angle_error_deg=float(np.degrees(error)),pivot_error_m=float(np.linalg.norm(expected_pivot-actual[3])))


def analyze(directory,manifest):
    directory=Path(directory);results={};errors=[];speeds={};angles={}
    for label in LABELS:
        path=directory/('steering-'+label+'.json')
        if not path.is_file():errors.append('Missing native steering pose: '+label);continue
        snapshot=json.loads(path.read_text());speeds[label]=snapshot['speed_m_s'];angles[label]=snapshot['steering_degrees']
        results[label]={}
        for owner,binding in manifest.get('rigid_render',{}).items():
            if not binding.get('steering'):continue
            for mesh in binding['steering']['meshes']:
                pose=snapshot['props'].get(mesh)
                if not pose:errors.append('Missing rendered steering mesh: '+mesh);continue
                if pose.get('coordinate_space')!='world':errors.append('Steering capture coordinate space is missing: '+label);continue
                error=pose_error(binding,manifest,pose|dict(steering_degrees=snapshot['steering_degrees']))
                results[label][mesh]=error
                if error['angle_error_deg']>.5 or error['pivot_error_m']>.002:errors.append('Native prop differs from steering/pivot contract: '+label+'/'+mesh)
        if not results[label]:errors.append('No steering props checked: '+label)
        from frame_harness.capture import usable_capture
        if not usable_capture(directory/('steering-'+label+'.png')):errors.append('Missing readable steering capture: '+label)
    if angles:
        if angles.get('left',0)*angles.get('right',0)>=0:errors.append('Stationary sweep did not exercise opposite steering angles')
        if abs(angles.get('return',float('inf')))>.5:errors.append('Steering did not return to neutral')
    if not all(speeds.get(label,0)>=minimum for label,minimum in [('low-left',1.),('low-right',1.),('medium-left',4.),('medium-right',4.)]):
        errors.append('Requested low/moderate-speed steering coverage was not reached')
    result=dict(status='passed' if not errors else 'failed',errors=errors,poses=results,steering_degrees=angles,speeds_m_s=speeds,
                scope='Native visual animation and pivot tracking; not a real steering-column ratio qualification')
    (directory/'steering-animation-result.json').write_text(json.dumps(result,indent=2))
    return result
