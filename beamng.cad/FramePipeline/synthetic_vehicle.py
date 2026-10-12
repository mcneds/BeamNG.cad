"""Versioned, independent CAD recipes. Coordinates are BeamNG metres (Z up).

Primitives are built by SolidWorks and exported through FrameSelection. Analytic
volumes below provide independent checks; they are not production mass inputs.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import math
import functools
from pathlib import Path
import numpy as np


@functools.lru_cache(maxsize=16)
def aligned_tie_inner(snapshot,travel=.16):
    """Design this synthetic fixture's tie pivot using the rigid-link reference.

    This changes native fixture geometry, never a user's selected CAD hardpoints.
    All points are normalized to the left corner at longitudinal origin.
    """
    import sys
    from scipy.optimize import least_squares
    from types import SimpleNamespace
    wizard=Path(__file__).resolve().parent/'calibration/Vehicle Wizard'
    if not wizard.is_dir():wizard=Path(__file__).resolve().parents[2]/'dependencies/cad-calibration/Vehicle Wizard'
    if str(wizard) not in sys.path:sys.path.insert(0,str(wizard))
    from vehicle_wizard.kinematics import Mechanism
    points={k:np.array(v,float) for k,v in snapshot};initial=points['tie_inner'].copy()
    model=SimpleNamespace(data={'corners':{'FL':{'template':'double_wishbone','links':[]}}},corner_points=lambda _:points)
    def curve(values):
        points['tie_inner']=np.array([values[0],initial[1],values[1]])
        mechanism=Mechanism(model,'FL');result=[]
        for height in np.linspace(-travel/2,travel/2,9):
            _,pose=mechanism.solve(float(height));axis=pose['hub_axis']-pose['hub']
            result.append(np.arctan2(axis[1],axis[0]))
        return np.array(result)
    fit=least_squares(curve,initial[[0,2]]+[0,.025],bounds=(initial[[0,2]]-[.1,.09],initial[[0,2]]+[.1,.09]),
        diff_step=1e-4,xtol=1e-10,gtol=1e-10,ftol=1e-10)
    if not fit.success or np.max(abs(np.degrees(curve(fit.x))))>.25:raise ValueError('Synthetic steering geometry cannot meet the bump-steer design limit')
    return (float(fit.x[0]),float(initial[1]),float(fit.x[1]))


def recipe(variant='primary', wheelbase=1.9, track=1.5, tube_wall=.002, panel_thickness=.002, caster_degrees=0.):
    if variant not in ('primary','independent_rear','radius_toe','ball_radius_toe'):raise ValueError('Unsupported synthetic template')
    if not 1.5<=wheelbase<=2.5 or not 1.3<=track<=1.8 or not .001<=tube_wall<=.004:raise ValueError('Recipe dimensions outside tested generation domain')
    if not math.isfinite(caster_degrees) or not 0<=caster_degrees<=10:raise ValueError('Synthetic caster must be between 0 and 10 degrees')
    result=dict(kind='synthetic_native_vehicle',version=4,variant=variant,
                dimensions=dict(wheelbase=wheelbase,track=track,tube_wall=tube_wall,panel_thickness=panel_thickness,caster_degrees=caster_degrees),
                source='Independent synthetic geometry; no Mochi measurements or artifacts',components=[],hardpoints={},
                templates=dict(front_suspension='double_wishbone',rear_suspension={'primary':'trailing_arm','independent_rear':'double_wishbone','radius_toe':'trailing_radius_toe','ball_radius_toe':'trailing_ball_radius_toe'}[variant],
                               drivetrain='cvt_rear_front_output' if variant!='independent_rear' else 'cvt_rear_drive'))
    components={}
    def primitive(role,kind,center,size=None,a=None,b=None,radius=None,wall=None,weight='solid'):
        item=components.setdefault(role,dict(id=role,role=role,primitives=[],surface_mass_mode='thickness',thickness=panel_thickness))
        shape=dict(kind=kind,center=center,size=size,a=a,b=b,radius=radius,wall=wall)
        if kind in ('tube','cylinder'):
            volume=math.pi*(radius**2-(radius-wall)**2 if kind=='tube' else radius**2)*float(np.linalg.norm(np.array(b)-a))
        elif kind=='sheet':volume=0
        else:volume=float(np.prod(size))
        shape['analytic_volume_m3']=volume;item['primitives'].append(shape)
        if weight=='ignore':item['surface_mass_mode']='ignore';item['visual_parent']='frame'
    def rod(role,a,b,r=.018,w=.002):primitive(role,'tube',None,a=list(a),b=list(b),radius=r,wall=w)
    # Rectangular space frame with diagonals and an elevated front/rear hoop.
    corners=list(itertools.product([-.31,.31],[0,wheelbase],[.24,.66]))
    edges=[]
    for i,a in enumerate(corners):
        for j,b in enumerate(corners[:i]):
            if sum(x!=y for x,y in zip(a,b))==1:edges.append((a,b))
    edges += [(corners[0],corners[6]),(corners[4],corners[2]),(corners[0],corners[3]),(corners[4],corners[7])]
    for a,b in edges:rod('frame',a,b,.02,tube_wall)
    primitive('engine','box',[0,wheelbase-.25,.46],[.22,.16,.13])
    primitive('cvt','box',[.23,wheelbase-.25,.46],[.10,.12,.065])
    primitive('rear_final_drive' if variant!='independent_rear' else 'rear_diff','box',[0,wheelbase,.34],[.15,.12,.10])
    if variant!='independent_rear':
        primitive('front_diff','box',[0,0,.34],[.12,.10,.09]);rod('front_propshaft',[0,.12,.34],[0,wheelbase-.12,.34],.019,.003)
    rod('cvt_output_shaft',[.23,wheelbase-.25,.46],[0,wheelbase,.34],.017,.003)
    for corner in ('FL','FR','RL','RR'):
        side=1 if corner[1]=='L' else -1;y=0 if corner[0]=='F' else wheelbase;hub=track/2
        def p(x,dy,z):return [side*x,y+dy,z]
        points=dict(hub=p(hub,0,.29),hub_axis=p(hub+.10,0,.29),shock_top=p(.28,-.03,.73),shock_bottom=p(hub-.18,-.08,.23))
        wishbone=corner[0]=='F' or variant=='independent_rear'
        if wishbone:
            for arm,x,z in [('upper',hub-.12,.47),('lower',hub-.08,.20)]:
                caster=(.47-.20)*math.tan(math.radians(caster_degrees)) if corner[0]=='F' and arm=='upper' else 0.
                points[arm+'_inner_front']=p(.26,-.16,z+.025);points[arm+'_inner_rear']=p(.26,.16,z+.025);points[arm+'_ball']=p(x,caster,z)
                role=corner.lower()+'_'+arm+'_wishbone'
                rod(role,points[arm+'_inner_front'],points[arm+'_ball'],.016,.002)
                rod(role,points[arm+'_inner_rear'],points[arm+'_ball'],.016,.002)
            points['tie_inner']=p(.25,.14,.36);points['tie_outer']=p(hub-.09,.14,.36)
            snapshot=tuple((k,(v[0]*side,v[1]-y,v[2])) for k,v in sorted(points.items()))
            inner=aligned_tie_inner(snapshot);points['tie_inner']=p(*inner)
            rod(corner.lower()+('_tie_rod' if corner[0]=='F' else '_toe_link'),points['tie_inner'],points['tie_outer'],.011,.002)
            rod(corner.lower()+'_upright',points['lower_ball'],points['upper_ball'],.027,.005)
            points['shock_bottom']=p(hub-.20,0,.215)
        elif variant=='ball_radius_toe':
            points.update(trailing_ball=p(.36,-.70,.23),carrier_axis_a=p(hub-.13,0,.20),carrier_axis_b=p(hub-.13,0,.40),
                          radius_upper_inner=p(.14,.06,.42),radius_upper_outer=p(hub-.13,.08,.40),
                          radius_lower_inner=p(.14,.06,.20),radius_lower_outer=p(hub-.13,.08,.20),
                          tie_inner=p(.17,.22,.30),tie_outer=p(hub-.12,.18,.30))
            points['shock_bottom']=p(hub-.23,-.27,.24)
            arm=corner.lower()+'_trailing_arm';upright=corner.lower()+'_upright'
            for key in ('carrier_axis_a','carrier_axis_b','radius_upper_outer','radius_lower_outer','shock_bottom'):
                rod(arm,points['trailing_ball'],points[key],.024,.003)
            rod(arm,points['carrier_axis_a'],points['carrier_axis_b'],.024,.003)
            for key in ('carrier_axis_a','carrier_axis_b','tie_outer'):rod(upright,points[key],points['hub'],.027,.005)
            for key,suffix in [('radius_upper','upper_radius_rod'),('radius_lower','lower_radius_rod'),('tie','toe_link')]:
                rod(corner.lower()+'_'+suffix,points[key+'_inner'],points[key+'_outer'],.016,.003)
        else:
            points['hinge_inner']=p(.40,-.57,.29);points['hinge_outer']=p(.64,-.57,.29)
            # These are physical CAD tubes, not a drawing of the constraint
            # graph. Route them inboard of the tire and cross the wheel plane
            # only through its central opening. The forward dogleg also clears
            # the tire at the narrowest supported track width.
            role=corner.lower()+'_trailing_arm'
            carrier=p(hub-.15,-.173 if variant=='radius_toe' else 0,.29);knee=p(hub-.15,-.40,.29)
            rod(role,points['hinge_inner'],carrier,.024,.003)
            rod(role,points['hinge_outer'],knee,.024,.003)
            rod(role,knee,carrier,.024,.003)
            rod(role,points['hinge_inner'],points['hinge_outer'],.025,.003)
            if variant=='radius_toe':
                points['carrier_ball']=carrier
                # Independent fixture, not inferred real vehicle mounts. The
                # carrier ball sits forward of three well-separated locating
                # rods. Nearly coaxial rod/chassis joints admit large carrier
                # rotation from tiny link strain despite a correct DOF count.
                points['radius_upper_inner']=p(.282,.171,.431);points['radius_upper_outer']=p(hub-.167,0,.45)
                points['radius_lower_inner']=p(.329,-.176,.137);points['radius_lower_outer']=p(hub-.205,0,.18)
                points['tie_inner']=p(.264,.045,.269);points['tie_outer']=p(hub-.179,.18,.31)
                for key,suffix in [('radius_upper','upper_radius_rod'),('radius_lower','lower_radius_rod'),('tie','toe_link')]:
                    rod(corner.lower()+'_'+suffix,points[key+'_inner'],points[key+'_outer'],.016,.003)
                    rod(corner.lower()+'_upright',carrier,points[key+'_outer'],.027,.005)
                rod(corner.lower()+'_upright',carrier,points['hub'],.027,.005)
            else:rod(role,carrier,points['hub'],.024,.003)
            rod(role,carrier,points['shock_bottom'],.024,.003)
        rod(corner.lower()+'_spring_damper',points['shock_top'],points['shock_bottom'],.021,.003)
        if variant!='independent_rear' or corner[0]=='R':rod(corner.lower()+'_halfshaft',p(.08,0,.34),points['hub'],.016,.004)
        primitive(corner.lower()+'_wheel','tube',None,a=p(hub-.08,0,.29),b=p(hub+.08,0,.29),radius=.28,wall=.008)
        result['hardpoints'][corner]=points
    rack=result['hardpoints']['FL']['tie_inner'];rod('steering_rack',[-rack[0],rack[1],rack[2]+.01],[rack[0],rack[1],rack[2]+.01],.016,.003)
    primitive('panel_floor','sheet',[0,wheelbase/2,.245],[.55,wheelbase*.86,0])
    primitive('panel_nose','sheet',[0,-.1,.60],[.48,.25,0],weight='ignore')
    primitive('accessory','box',[0,wheelbase*.45,.70],[.06,.07,.04])
    for role,item in components.items():
        item['analytic_volume_m3']=sum(p['analytic_volume_m3'] for p in item['primitives'])
        item['material']='AISI 4130 Steel, annealed at 865C'
        result['components'].append(item)
    result['recipe_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--variant',default='primary');parser.add_argument('--wheelbase',type=float,default=1.9);parser.add_argument('--track',type=float,default=1.5)
    parser.add_argument('--caster',type=float,default=0.)
    args=parser.parse_args();data=recipe(args.variant,args.wheelbase,args.track,caster_degrees=args.caster)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':main()
