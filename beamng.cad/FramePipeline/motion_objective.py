"""CAD wheel-angle residual gradients; no alteration of intended kinematics."""
import numpy as np
from frame_harness.vehicle_motion import Predictor,rigid_fit,angles,angle_error,hub_datum


def residual_columns(xyz,chassis,weights,axes,hubs,slopes,step=1e-6):
    """Differentiate camber/toe error at the same measured bearing height.

    Columns are radians/metre in ordinary position coordinates. A proper frame
    fit removes overall motion; the CAD travel derivative removes bump steer.
    """
    xyz=np.asarray(xyz,float);axes=np.asarray(axes,int);hubs=np.asarray(hubs,float)
    rest_angles=np.array([angles(xyz[b]-xyz[a]) for a,b in axes])
    def residual(current):
        r,t=rigid_fit(xyz[chassis],current[chassis],weights)
        local=(current-t)@r.T;values=[]
        for i,(a,b) in enumerate(axes):
            hub=hub_datum(hubs[i],xyz[[a,b]],local[[a,b]])
            values.extend(angle_error(angles(local[b]-local[a]),rest_angles[i])-slopes[i]*(hub[2]-hubs[i,2]))
        return np.radians(values)
    columns=np.zeros((xyz.size,2*len(axes)))
    for i in range(xyz.size):
        delta=np.zeros_like(xyz);delta.flat[i]=step
        columns[i]=(residual(xyz+delta)-residual(xyz-delta))/(2*step)
    return columns


def front_columns(part,names,manifest):
    from frame_harness.build import node_table
    nodes=node_table(part);index={n:i for i,n in enumerate(names)}
    if not set(manifest['chassis_nodes'])<=set(names):raise ValueError('Motion objective needs all frame nodes')
    xyz=np.array([nodes[n]['position'] for n in names]);mass=np.array([nodes[n]['options']['nodeWeight'] for n in names])
    chassis=[index[n] for n in manifest['chassis_nodes']];axes=[];hubs=[];slopes=[]
    predictor=Predictor(manifest)
    for corner in ('FL','FR'):
        wheel=manifest['wheels'][corner]
        axes.append([index[wheel['nodes'][k]] for k in ('axis_in','axis_out')])
        p=predictor.mechanisms[corner].p;hubs.append(p['hub']);sample=[]
        for height in (-5e-5,5e-5):
            pose=predictor.solve(corner,height,0.)
            direction=pose['hub_axis']-pose['hub'];direction*=1 if p['hub_axis'][0]>p['hub'][0] else -1
            sample.append(angles(direction))
        slopes.append(angle_error(sample[1],sample[0])/1e-4)
    columns=residual_columns(xyz,chassis,mass[chassis],axes,hubs,np.array(slopes))
    return columns/np.repeat(np.sqrt(mass),3)[:,None],dict(
        channels=['FL_camber','FL_toe','FR_camber','FR_toe'],travel_slope_deg_m=np.array(slopes).tolist(),
        scope='Local derivative of CAD wheel-angle residual, after frame registration and at measured hub height; intended bump steer is subtracted, not retuned.')
