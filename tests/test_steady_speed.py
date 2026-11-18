import importlib.util,sys,unittest
from pathlib import Path
import numpy as np
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from steady_speed_control import settings,step,instrument
spec=importlib.util.spec_from_file_location('steady_analysis',ROOT/'tools/analyze-steady-speed.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)

class SteadySpeedTests(unittest.TestCase):
    def test_coast_releases_both_pedals_without_windup(self):
        config=settings(2.2352,30.)
        for speed in (0.,2.2352,5.):
            self.assertEqual(step(speed,30.,.05,.4,config),(0.,0.,.4))
        self.assertGreater(step(0.,29.9,.05,.4,config)[0],0.)
        for start in (19.,46.,float('nan')):
            with self.assertRaises(ValueError):settings(2.2352,start)
    def test_controller_recovers_drag_change_without_simultaneous_pedals(self):
        for target in (1.34112,2.2352,3.12928,5.,10.,15.):
            config=settings(target);speed=0.;integral=0.;history=[]
            for t in np.arange(0,55,.05):
                throttle,brake,integral=step(speed,t,.05,integral,config)
                self.assertTrue(0<=throttle<=1 and 0<=brake<=.5 and throttle*brake==0)
                drag=.08*speed+(.35 if t>=35 else 0.)
                speed=max(0,speed+.05*(3*throttle-8*brake-drag));history.append(speed)
            self.assertLess(max(abs(np.array(history)[900:]-target)),.03)
    def test_unreachable_speed_does_not_wind_up_and_overspeed_brakes(self):
        c=settings(15.);integral=0.
        for _ in range(10000):throttle,brake,integral=step(0,40,.05,integral,c)
        self.assertLessEqual(abs(integral),1)
        throttle,brake,_=step(20,40,.05,integral,c)
        self.assertEqual(throttle,0);self.assertGreater(brake,0)
        with self.assertRaises(ValueError):settings(float('nan'))
        for target in (True,0.,-1.,float('inf'),15.01):
            with self.assertRaises(ValueError):settings(target)
    def test_hold_gate_excludes_transients_and_fragmented_holds(self):
        t=np.arange(.05,55.01,.05)
        speed=np.minimum(t/3,10.)
        mask,a,segments=analysis.hold_mask(t,speed,10.)
        self.assertTrue(segments);self.assertGreaterEqual(segments[0][0],30.)
        self.assertLess(max(abs(a[mask])),.15)
        self.assertFalse(analysis.hold_mask(t,np.ones(len(t))*8,10.)[0].any())
        fragmented=np.where((t%4)<2,10.,11.)
        self.assertFalse(analysis.hold_mask(t,fragmented,10.)[0].any())
        with self.assertRaises(ValueError):analysis.hold_mask(t[::-1],speed,10.)
    def test_instrument_preserves_validation_and_zero_steering(self):
        source=(ROOT/'dependencies/cad-calibration/Test Harness/frame_harness/lua/vehicle_recorder.lua').read_text()
        changed=instrument(source)
        for check in ('Compiled beam/properties differ','Compiled fixture pins differ',"input.event('steering',steering"):
            self.assertIn(check,changed)
        self.assertIn("local throttle,brake,steering=0,0,0",changed)
        self.assertNotIn('setBeamSpring',changed)
        with self.assertRaises(ValueError):instrument(changed)

    def test_reference_map_preserves_authored_asymmetry_and_roll_steer(self):
        corners=('FL','FR','RL','RR')
        manifest={'wheels':{c:{'ride_reference':{'hub_height_m':0}} for c in corners}}
        class Predictor:
            def __init__(self,m):
                self.mechanisms={c:SimpleNamespace(p={'hub':np.array([1. if c[1]=='L' else -1.,0,0]),'hub_axis':np.array([2. if c[1]=='L' else 0.,0,0])},translating_rack=False,wishbone=False,radius_toe=False,ball_radius_toe=False) for c in corners}
            def solve(self,c,travel,extension):
                toe=np.radians((1 if c[1]=='L' else -1.4)+(10 if c[1]=='L' else -10)*travel)
                hub=self.mechanisms[c].p['hub'];return {'hub':hub,'hub_axis':hub+np.array([np.cos(toe),np.sin(toe),0])}
        with patch.object(analysis,'Predictor',Predictor):
            value=analysis.steering_map(manifest,{'samples':[{'t':5}]})
        neutral=next(r for r in value['curves'] if r['mode']=='level_bump' and abs(r['offset_m'])<1e-8)
        self.assertAlmostEqual(sum(neutral['corners'][c]['toe_deg'] for c in ('FL','FR'))/2,-.2)
        roll=value['curves'][-1]
        self.assertAlmostEqual(sum(roll['corners'][c]['toe_deg'] for c in ('FL','FR'))/2,.2)

if __name__=='__main__':unittest.main()
