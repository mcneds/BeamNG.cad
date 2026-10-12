import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from wheel_support_reuse import apply, renormalize_couplings


class WheelSupportReuseTests(unittest.TestCase):
    def fixture(self):
        options=dict(numRays=16,hubNodeWeight=.2,nodeWeight=.15,radius=.3,hubRadius=.12,
            tireWidth=.14,hubWidth=.10,pressurePSI=12,wheelSideBeamSpring=10200,brakeTorque=200)
        p=dict(nodes=[['id','posX','posY','posZ'],['a',-.05,0,0,{'nodeWeight':2.}],['b',.05,0,0,{'nodeWeight':2.}]],
            beams=[['id1:','id2:'],['a','b',{'beamSpring':123456,'beamDamp':321}]],
            pressureWheels=[['name','hubGroup','group','node1:','node2:','nodeS','nodeArm:','wheelDir'],['FL','rim','tire','a','b',9999,'c',1,options]])
        m=dict(component_roles={'wheel':'fl_wheel','upright':'fl_upright'},
            nodes={n:dict(position=[x,0,0],mass_kg=2.) for n,x in [('a',-.05),('b',.05)]},
            mass_allocations={'wheel':{},'upright':{'a':2.,'b':2.}},component_reports={'upright':{'numerical_added_mass_kg':3.6}},
            numerical_mass=dict(added_mass_kg=3.6,added_by_component_kg={'upright':3.6},
                nodes={n:dict(target_kg=2.,added_mass_kg=1.8,added_by_component_kg={'upright':1.8},redistributed_cad_mass_kg=.2,reasons=[]) for n in ['a','b']}),
            device_contract={},template_definition={'parameters':{}},
            wheels={'FL':dict(nodes={'axis_in':'a','axis_out':'b'},wheel_mass_kg=11.2,cad_wheel_mass_kg=11.2,
                mass_allocation={'added_per_axle_node_kg':0},effective_unsprung_mass_kg=15.2,
                spring_n_m=10000.,damper_ns_m=1000.,spring_preload_n=300.)},expected_dry_mass_kg=15.2,limitations=[])
        return p,m

    @staticmethod
    def refresh(m,delta):
        assert delta=={}
        m['expected_dry_mass_kg']=sum(n['mass_kg'] for n in m['nodes'].values())+sum(w['wheel_mass_kg'] for w in m['wheels'].values())

    @staticmethod
    def discrete_moments(options,extra=0):
        # Reconstruct actual symmetric rings as point masses, then rotate and
        # translate them: check the full tensor, not the solver's scalar formula.
        points=[];masses=[]
        for radius,width,mass in [(options['radius'],options['tireWidth'],options['nodeWeight']),
                                  (options['hubRadius'],options['hubWidth'],options['hubNodeWeight'])]:
            for side in [-1,1]:
                for angle in np.linspace(0,2*np.pi,options['numRays'],endpoint=False):
                    points.append([side*width/2,radius*np.cos(angle),radius*np.sin(angle)]);masses.append(mass)
        points.extend([[-.05,0,0],[.05,0,0]]);masses.extend([extra,extra])
        points=np.array(points);masses=np.array(masses)
        q,_=np.linalg.qr(np.array([[1.,2,3],[3,1,4],[5,2,1]]));points=points@q+[4,5,6]
        com=masses@points/sum(masses);d=points-com
        tensor=sum(m*(np.dot(x,x)*np.eye(3)-np.outer(x,x)) for m,x in zip(masses,d))
        return sum(masses),com,tensor

    def test_ballast_replaced_and_full_wheel_moments_preserved(self):
        p,m=self.fixture();old=copy.deepcopy((p,m));before=self.discrete_moments(p['pressureWheels'][1][-1])
        with patch('wheel_support_reuse.refresh_load_metadata',side_effect=self.refresh), patch('wheel_support_reuse.renormalize_couplings',return_value={}):apply(p,m,1.)
        after=self.discrete_moments(p['pressureWheels'][1][-1],1.)
        for a,b in zip(before,after):np.testing.assert_allclose(a,b,atol=1e-12)
        self.assertEqual(p['nodes'],old[0]['nodes']);self.assertEqual(p['beams'],old[0]['beams'])
        for key,value in old[0]['pressureWheels'][1][-1].items():
            if key not in ('nodeWeight','hubNodeWeight','hubWidth'):self.assertEqual(p['pressureWheels'][1][-1][key],value)
        self.assertAlmostEqual(m['expected_dry_mass_kg'],13.2)
        self.assertAlmostEqual(m['numerical_mass']['added_mass_kg'],1.6)
        for n in ['a','b']:
            self.assertAlmostEqual(m['mass_allocations']['upright'][n]-m['numerical_mass']['nodes'][n]['added_mass_kg'],.2)
            self.assertEqual(m['mass_allocations']['wheel'][n],1.)
        for k in ('spring_n_m','damper_ns_m','spring_preload_n','cad_wheel_mass_kg'):
            self.assertEqual(m['wheels']['FL'][k],old[1]['wheels']['FL'][k])

    def test_invalid_requests_and_insufficient_ballast_are_atomic(self):
        for kind in ('zero','large','nan','bool','ballast','floor','wheelmass','owners'):
            p,m=self.fixture();amount={'zero':0.,'large':1.1,'nan':float('nan'),'bool':True}.get(kind,1.)
            if kind=='ballast':m['numerical_mass']['nodes']['a']['added_mass_kg']=.1
            if kind=='floor':p['nodes'][1][-1]['nodeWeight']=1.9
            if kind=='wheelmass':m['wheels']['FL']['wheel_mass_kg']=12.
            if kind=='owners':m['mass_allocations']['upright']['a']=1.
            before=copy.deepcopy((p,m))
            with self.assertRaises(ValueError):apply(p,m,amount)
            self.assertEqual((p,m),before)

    def test_repeat_rejected_without_mutation(self):
        p,m=self.fixture()
        with patch('wheel_support_reuse.refresh_load_metadata',side_effect=self.refresh), patch('wheel_support_reuse.renormalize_couplings',return_value={}):apply(p,m,.5)
        before=copy.deepcopy((p,m))
        with self.assertRaisesRegex(ValueError,'already applied'):apply(p,m,.5)
        self.assertEqual((p,m),before)

    def test_native_damping_conversion_preserves_force_laws(self):
        import math
        from vehicle_drivetrain import generate,configure_carrier
        p,c=generate('cvt_rear_front_output',dict(rear_reduction=9,front_reduction=6,front_output_ratio=.2),['a','b','c'],'d')
        old=dict(FL=.11,FR=.12,RL=.135,RR=.14)
        configure_carrier(p,c,dict(front=.0004,rear=.001),old,{})
        before=copy.deepcopy((p,c));new={k:v*.65 for k,v in old.items()}
        report=renormalize_couplings(p,c,new,{})
        native_front=(new['FL']+new['FR'])/1.2**2
        cases=[('clutch_coupling',p['clutch'],'lockSpring','lockDampRatio',native_front/(9*3)**2),
               ('parking_lock',p['gearbox'],'parkLockSpring','parkLockDampRatio',native_front/9**2),
               ('carrier_coupling',next(r[4] for r in p['powertrain'][1:] if r[1]=='rearCarrierTakeoff'),
                'lockSpring','lockDampRatio',new['RL']+new['RR'])]
        for key,options,sk,rk,inertia in cases:
            self.assertAlmostEqual(options[rk]*math.sqrt(options[sk]*inertia),before[1][key]['damping_nm_s_rad'])
            self.assertEqual(report[key]['retained_damping'],before[1][key]['damping_nm_s_rad'])
            self.assertLess(report[key]['step_eigenvalue'],3.2)
            options[rk]=report[key]['damping_ratio_before']
        self.assertEqual(p,before[0])

    def test_unsafe_native_inertia_change_is_atomic(self):
        from vehicle_drivetrain import generate,configure_carrier
        p,c=generate('cvt_rear_front_output',{},['a','b','c'],'d')
        configure_carrier(p,c,dict(front=.1,rear=.1),dict(FL=.1,FR=.1,RL=.1,RR=.1),{})
        before=copy.deepcopy((p,c))
        with self.assertRaisesRegex(ValueError,'timestep bound'):
            renormalize_couplings(p,c,dict(FL=1e-8,FR=1e-8,RL=1e-8,RR=1e-8),{})
        self.assertEqual((p,c),before)


if __name__=='__main__':unittest.main()
