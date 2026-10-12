"""Rigid-link template checks. Preview predictions are not simulated BeamNG results."""
from __future__ import annotations
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def hinge(point, a, b, angle):
    axis=b-a
    if np.linalg.norm(axis)<1e-5:raise ValueError('Hinge points coincide')
    return a+Rotation.from_rotvec(axis/np.linalg.norm(axis)*angle).apply(point-a)


class Mechanism:
    def __init__(self,project,corner):
        self.project=project;self.corner=corner;self.p=project.corner_points(corner)
        self.front=corner.startswith('F')
        self.steering=project.data.get('steering',{})
        self.translating_rack=self.front and self.steering.get('kind')=='translating_rack'
        self.rack_axis=np.asarray(self.steering.get('axis',[1,0,0]),float)
        if self.translating_rack and (self.rack_axis.shape!=(3,) or not np.isfinite(self.rack_axis).all() or abs(np.linalg.norm(self.rack_axis)-1)>1e-6):
            raise ValueError('Rack axis must be a finite unit vector')
        self.template=project.data['corners'][corner]['template']
        if self.template not in ('double_wishbone','trailing_arm','trailing_links','trailing_radius_toe','trailing_ball_radius_toe'):raise ValueError('Unsupported mechanism: '+self.template)
        self.wishbone=self.template=='double_wishbone';self.hinged=self.template=='trailing_arm'
        self.radius_toe=self.template=='trailing_radius_toe'
        self.ball_radius_toe=self.template=='trailing_ball_radius_toe'
        self.size=8 if self.wishbone else 1 if self.hinged else 7 if self.radius_toe else 4 if self.ball_radius_toe else 6
        self.links=[(project.point(l['inner']),project.point(l['outer'])) for l in project.data['corners'][corner]['links']]
        self.locating_links=('radius_upper','radius_lower','tie') if self.radius_toe or self.ball_radius_toe else ()
        if self.radius_toe or self.ball_radius_toe:
            pivots={'trailing_ball','carrier_axis_a','carrier_axis_b'} if self.ball_radius_toe else {'hinge_inner','hinge_outer','carrier_ball'}
            required=pivots|{'hub','hub_axis','shock_top','shock_bottom'}|{link+'_'+end for link in self.locating_links for end in ('inner','outer')}
            missing=required-set(self.p)
            if missing:raise ValueError(corner+': missing ball-joint hardpoints: '+', '.join(sorted(missing)))
            if self.front:raise ValueError('Trailing arm with radius/toe rods is a rear suspension option')
            if self.ball_radius_toe and np.linalg.norm(self.p['carrier_axis_b']-self.p['carrier_axis_a'])<.001:raise ValueError('Carrier hinge requires distinct axis sites')
            for link in self.locating_links:
                if np.linalg.norm(self.p[link+'_outer']-self.p[link+'_inner'])<.01:raise ValueError(corner+': locating rod endpoints must be at least 10 mm apart: '+link)

    def pose(self,x):
        p=self.p;off=2 if self.wishbone else 1 if self.radius_toe else 0
        if self.ball_radius_toe:
            rotation=Rotation.from_rotvec(x[:3])
            def arm(point):return p['trailing_ball']+rotation.apply(point-p['trailing_ball'])
            def carrier(point):return arm(hinge(point,p['carrier_axis_a'],p['carrier_axis_b'],x[3]))
            result={k:v.copy() for k,v in p.items()}
            for key in ('carrier_axis_a','carrier_axis_b','shock_bottom','radius_upper_outer','radius_lower_outer'):result[key]=arm(p[key])
            for key in ('hub','hub_axis','tie_outer'):result[key]=carrier(p[key])
            return result,carrier
        if self.hinged:
            def rigid(point):return hinge(point,p['hinge_inner'],p['hinge_outer'],x[0])
            return {key:rigid(value) if key in ('hub','hub_axis','shock_bottom') else value.copy() for key,value in p.items()},rigid
        rotation=Rotation.from_rotvec(x[off:off+3]);translation=x[off+3:off+6]
        def rigid(point):return p['hub']+rotation.apply(point-p['hub'])+translation
        result={k:v.copy() for k,v in p.items()}
        if self.wishbone:
            for arm,angle in [('lower',x[0]),('upper',x[1])]:
                for key in [arm+'_ball']+(['shock_bottom'] if arm=='lower' else []):
                    result[key]=hinge(p[key],p[arm+'_inner_front'],p[arm+'_inner_rear'],angle)
            for key in ['hub','hub_axis','tie_outer']:result[key]=rigid(p[key])
        elif self.radius_toe:
            # Two spherical chassis joints fix the arm's axis; a SINGLE
            # spherical arm/carrier joint leaves carrier orientation to the
            # three independent spherical-ended locating rods.
            for key in ('carrier_ball','shock_bottom'):
                result[key]=hinge(p[key],p['hinge_inner'],p['hinge_outer'],x[0])
            for key in ('hub','hub_axis',*(link+'_outer' for link in self.locating_links)):
                result[key]=rigid(p[key])
        else:
            for key in ['hub','hub_axis','shock_bottom']:result[key]=rigid(p[key])
        return result,rigid

    def constraints(self,x,steer=0):
        p=self.p;pose,rigid=self.pose(x)
        if self.hinged:return np.empty(0)
        if self.wishbone:
            residual=list(rigid(p['lower_ball'])-pose['lower_ball'])+list(rigid(p['upper_ball'])-pose['upper_ball'])
            # Same variable-length tie rod used by the generated steering hydro.
            tie=np.linalg.norm(p['tie_outer']-p['tie_inner'])
            inner=p['tie_inner']+self.rack_axis*steer if self.translating_rack else p['tie_inner']
            residual.append(np.linalg.norm(rigid(p['tie_outer'])-inner)-tie-(0 if self.translating_rack else steer))
        elif self.ball_radius_toe:
            residual=[np.linalg.norm(pose[link+'_outer']-p[link+'_inner'])-np.linalg.norm(p[link+'_outer']-p[link+'_inner'])-(steer if link=='tie' else 0.) for link in self.locating_links]
        elif self.radius_toe:
            residual=list(rigid(p['carrier_ball'])-pose['carrier_ball'])
            residual.extend(np.linalg.norm(rigid(p[link+'_outer'])-p[link+'_inner'])-
                np.linalg.norm(p[link+'_outer']-p[link+'_inner'])-(steer if link=='tie' else 0.) for link in self.locating_links)
        else:
            residual=list(rigid(p['trailing_pivot'])-p['trailing_pivot'])
            residual.extend(np.linalg.norm(rigid(b)-a)-np.linalg.norm(b-a) for a,b in self.links)
        return np.array(residual)

    def solve(self,height=0,steer=0,initial=None):
        def residual(x):return np.r_[self.constraints(x,steer),self.pose(x)[0]['hub'][2]-self.p['hub'][2]-height]
        start=np.zeros(self.size) if initial is None else np.asarray(initial,float).copy()
        # A previous solution at design height can be numerical noise around
        # zero. SciPy uses that tiny nonzero norm as its initial trust radius,
        # then stops before taking a meaningful travel step. Exact zero selects
        # its normal unit radius and preserves the same physical constraints.
        if np.linalg.norm(start)<1e-6:start[:]=0
        fit=least_squares(residual,start,xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=300)
        error=float(np.max(np.abs(fit.fun)))
        if not fit.success or error>1e-4:raise ValueError(f'{self.corner}: linkage cannot reach {height*1000:.0f} mm travel (error {error*1000:.2f} mm)')
        pose,_=self.pose(fit.x)
        if self.translating_rack:pose['tie_inner']=self.p['tie_inner']+self.rack_axis*steer
        return fit.x,pose

    def component_transforms(self,x,steer=0):
        """Display-only rigid motions. Never commit an articulation preview to CAD placement."""
        p=self.p;pose,rigid=self.pose(x);off=2 if self.wishbone else 1 if self.radius_toe else 0
        if self.translating_rack:pose['tie_inner']=p['tie_inner']+self.rack_axis*steer
        body=np.eye(4)
        if self.ball_radius_toe:
            arm_rot=Rotation.from_rotvec(x[:3]).as_matrix();a=p['trailing_ball']
            arm=np.eye(4);arm[:3,:3]=arm_rot;arm[:3,3]=a-arm_rot@a
            a=p['carrier_axis_a'];axis=p['carrier_axis_b']-a;axis/=np.linalg.norm(axis)
            relative=np.eye(4);relative[:3,:3]=Rotation.from_rotvec(axis*x[3]).as_matrix();relative[:3,3]=a-relative[:3,:3]@a
            body=arm@relative;rot=body[:3,:3]
        elif self.hinged:
            axis=p['hinge_outer']-p['hinge_inner'];rot=Rotation.from_rotvec(axis/np.linalg.norm(axis)*x[0]).as_matrix()
            body[:3,3]=p['hinge_inner']-rot@p['hinge_inner']
        else:
            rot=Rotation.from_rotvec(x[off:off+3]).as_matrix();body[:3,3]=p['hub']-rot@p['hub']+x[off+3:off+6]
        body[:3,:3]=rot
        result={'upright':body,'wheel':body,'tire':body,'trailing_arm':body}
        if self.ball_radius_toe:result['trailing_arm']=arm
        if self.radius_toe:
            a=p['hinge_inner'];axis=p['hinge_outer']-a;rotation=Rotation.from_rotvec(axis/np.linalg.norm(axis)*x[0]).as_matrix()
            m=np.eye(4);m[:3,:3]=rotation;m[:3,3]=a-rotation@a;result['trailing_arm']=m
        if self.wishbone:
            for i,arm in enumerate(('lower','upper')):
                a=p[arm+'_inner_front'];axis=p[arm+'_inner_rear']-a;rotation=Rotation.from_rotvec(axis/np.linalg.norm(axis)*x[i]).as_matrix()
                m=np.eye(4);m[:3,:3]=rotation;m[:3,3]=a-rotation@a;result[arm+'_arm']=m
        def rod(a,b,aa,bb):
            old=b-a;new=bb-aa;old/=np.linalg.norm(old);new/=np.linalg.norm(new)
            rotation=Rotation.align_vectors([new],[old])[0].as_matrix();m=np.eye(4);m[:3,:3]=rotation;m[:3,3]=aa-rotation@a;return m
        result['shock_body']=rod(p['shock_top'],p['shock_bottom'],pose['shock_top'],pose['shock_bottom'])
        result['shock_rod']=rod(p['shock_bottom'],p['shock_top'],pose['shock_bottom'],pose['shock_top'])
        if self.wishbone:result['tie_rod']=rod(p['tie_inner'],p['tie_outer'],pose['tie_inner'],pose['tie_outer'])
        for link in self.locating_links:
            a=p[link+'_inner'];b=p[link+'_outer'];result[link]=rod(a,b,a,pose[link+'_outer'])
        for i,(a,b) in enumerate(self.links):result[self.corner+f'_link_{i}']=rod(a,b,a,rigid(b))
        return result

    def inspect(self,travel=None):
        p=self.p;x=np.zeros(self.size);step=1e-6
        jac=np.column_stack([(self.constraints(x+np.eye(self.size)[i]*step)-self.constraints(x-step*np.eye(self.size)[i]))/(2*step) for i in range(self.size)])
        rank=int(np.linalg.matrix_rank(jac,tol=1e-6)) if jac.size else 0;dof=self.size-rank
        if dof!=1:raise ValueError(f'{self.corner}: linkage has {dof} free motions; expected one suspension motion. Check pivots and locating links.')
        if np.linalg.norm(p['hub_axis']-p['hub'])<.01:raise ValueError('Hub axis point must be at least 10 mm from hub center')
        travel=travel or self.project.data['parameters']['travel_m'];samples=[];locating_levers=[]
        for height in np.linspace(-travel/2,travel/2,9):
            state,pose=self.solve(float(height));axis=pose['hub_axis']-pose['hub'];axis*=1 if axis[0]>=0 else -1
            if self.radius_toe or self.ball_radius_toe:
                tangent=np.column_stack([(self.constraints(state+np.eye(self.size)[i]*step)-self.constraints(state-step*np.eye(self.size)[i]))/(2*step) for i in range(self.size)])
                if np.linalg.matrix_rank(tangent,tol=1e-6)!=self.size-1:raise ValueError(f'{self.corner}: locating links become singular at {height*1000:.0f} mm travel')
            if self.radius_toe:
                rows=[]
                for link in self.locating_links:
                    a=pose[link+'_inner'];b=pose[link+'_outer'];direction=(b-a)/np.linalg.norm(b-a)
                    rows.append(np.cross(b-pose['carrier_ball'],direction))
                locating_levers.append(float(np.linalg.svd(rows,compute_uv=False)[-1]))
            samples.append({'travel_m':float(height),'shock_length_m':float(np.linalg.norm(pose['shock_bottom']-pose['shock_top'])),
                            'toe_deg':float(np.degrees(np.arctan2(axis[1],axis[0]))),
                            'camber_deg':float(np.degrees(np.arctan2(axis[2],np.linalg.norm(axis[:2])))),
                            'points':{k:v.tolist() for k,v in pose.items()}})
        _,lo=self.solve(-.001);_,hi=self.solve(.001)
        ratio=abs(np.linalg.norm(hi['shock_bottom']-p['shock_top'])-np.linalg.norm(lo['shock_bottom']-p['shock_top']))/.002
        if not .05<ratio<3:raise ValueError(f'{self.corner}: coilover motion ratio {ratio:.3f} is implausible; verify the lower-arm/trailing-arm mount')
        steering=[]
        if self.front:
            tie=p['tie_outer']-p['tie_inner'];king=p['upper_ball']-p['lower_ball'];king/=np.linalg.norm(king)
            arm=p['tie_outer']-p['lower_ball'];gain=float(np.dot(np.cross(king,arm),tie/np.linalg.norm(tie)))
            if abs(gain)<.005:raise ValueError(f'{self.corner}: tie rod cannot provide steering leverage')
            steer_travel=gain*np.radians(self.project.data['parameters']['steer_degrees'])
            if self.translating_rack:steer_travel=float(self.steering['half_travel_m'])
            for sign in [-1,1]:
                _,pose=self.solve(0,sign*steer_travel)
                axis=pose['hub_axis']-pose['hub'];axis*=1 if axis[0]>=0 else -1
                steering.append(float(np.degrees(np.arctan2(axis[1],axis[0]))))
        else:steer_travel=0.
        result={'corner':self.corner,'template':self.template,'degrees_of_freedom':dof,'motion_ratio':ratio,'steer_length_m':steer_travel,
                'steering_toe_deg':steering,'samples':samples,'kind':'analytical prediction - verify in simulator'}
        if locating_levers:result['minimum_locating_lever_m']=min(locating_levers)
        return result


def inspect_all(project):
    return {c:Mechanism(project,c).inspect() for c in project.data['corners']}
