import importlib.util, unittest
import numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rate_probe',ROOT/'tools/probe-suspension-rate.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/name)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
analysis=module('analyze-suspension-rate.py');revision=module('revise-coilover-pair.py')
speed_analysis=module('analyze-straightline-speed.py')

class SuspensionRateTests(unittest.TestCase):
    def test_recovery_load_is_bounded_and_retains_preload_bias(self):
        manifest={'wheels':{c:dict(spring_preload_n=1000.,motion_ratio=.5) for c in ('FL','FR','RL','RR')}}
        settings=probe.recovery_excitation(manifest,'FR',1000.)
        self.assertEqual(settings['bias_n'],dict.fromkeys(('FL','FR','RL','RR'),500.))
        self.assertEqual(settings['duration_s'],6.)
        t=np.linspace(0,6,12001);envelope=np.clip(np.minimum(t/2,(6-t)/2),0,1);force=1000*envelope**2*(3-2*envelope)
        self.assertEqual(force[0],0);self.assertEqual(force[-1],0);self.assertEqual(max(force),1000)
        self.assertLess(max(abs(np.diff(force)/.0005)),751)
        for invalid in (-1.,2000.,float('nan')):
            with self.assertRaises(ValueError):probe.recovery_excitation(manifest,'FR',invalid)

    def test_equal_force_bias_and_complete_cycles(self):
        manifest={'wheels':{c:dict(spring_preload_n=1000.,motion_ratio=.5) for c in ('FL','FR','RL','RR')}}
        rows=[probe.excitation(manifest,'FR',hz,100.) for hz in (.5,1.,2.)]
        self.assertTrue(all(r['bias_n']==rows[0]['bias_n'] and r['amplitude_n']==100. for r in rows))
        for row in rows:self.assertEqual(row['duration_s']*row['frequency_hz']%1,0)
        for hz,force in [(float('nan'),100.),(.5,float('inf')),(.1,100.),(.5,201.)]:
            with self.assertRaises(ValueError):probe.excitation(manifest,'FR',hz,force)

    def test_fixture_keeps_native_validation_and_passive_laws(self):
        original=(ROOT/'dependencies/cad-calibration/Test Harness/frame_harness/lua/vehicle_recorder.lua').read_text()
        source=probe.instrument(original)
        for check in ('Compiled beam/properties differ','Compiled fixture pins differ','getBeamStressDamp','shiftToGearIndex(0)'):
            self.assertIn(check,source)
        self.assertNotIn('yaw_moment_nm',source)
        self.assertNotIn('setBeamSpring',source)
        self.assertIn('rateSamples=rateSamples+1',source)

    def test_force_law_and_measured_phase(self):
        wheel=dict(spring_preload_n=1000.,spring_n_m=10000.,coilover_spring=dict(initial_rate_n_m=10000.,final_rate_n_m=30000.,crossover_compression_m=.01))
        np.testing.assert_allclose(analysis.audit.spring_force(wheel,[-.01,0,.01,.02]),[-900,-1000,-1100,-1400])
        t=np.arange(6,10,.0005);response=.017*np.sin(2*np.pi*.5*(t-6)-np.pi/6)
        h=analysis.harmonic(t,response,.5)
        self.assertAlmostEqual(abs(h),.017);self.assertAlmostEqual(np.degrees(np.angle(h)),-30.)

    def test_pair_revision_keeps_mass_geometry_other_beams_and_preload(self):
        p=dict(Components=[dict(Id='left',MvpRole='rl_spring_damper',CoiloverSpring=dict(Mode='dual_rate',MainRateNPerM=30000.,TenderRateNPerM=15000.,CrossoverCompressionM=.01)),dict(Id='right',MvpRole='rr_spring_damper')])
        w=dict(nodes=dict(shock_top='top',shock_bottom='bottom'),spring_preload_n=850.,spring_n_m=14000.,damper_ns_m=1900.,ride_reference=dict(reference_shock_length_m=.55,captured_shock_length_m=.6))
        m=dict(wheels=dict(RR=w,RL=dict(damper_ns_m=1600.)),template_definition=dict(parameters=dict(suspension_physical_settings=dict(RR=dict(spring_n_m=14000.,damper_ns_m=1900.,spring_preload_n=850.)))),explicit_beams=3,limitations=[])
        part=dict(nodes=[['fixed mass and geometry']],beams=[['id1:','id2:'],['top','bottom',dict(beamType='|BOUNDED',beamSpring=14000.,beamDamp=0)],['top','bottom',dict(beamType='|BOUNDED',beamSpring=0,beamDamp=1900.,shortBoundRange=.04)],['other','beam',dict(beamSpring=1e6)]])
        changed,manifest,project,audit=revision.revise(part,m,p,'RL','RR')
        self.assertEqual(changed['nodes'],part['nodes']);self.assertEqual(changed['beams'][3],part['beams'][3])
        self.assertEqual(manifest['wheels']['RR']['spring_preload_n'],850.)
        self.assertEqual(manifest['wheels']['RR']['damper_ns_m'],1900.)
        self.assertEqual(manifest['explicit_beams'],4)
        self.assertAlmostEqual(changed['beams'][1][-1]['beamPrecompression']*.6,.55+.085)
        again,mm,pp,_=revision.revise(changed,manifest,project,'RL','RR',True)
        self.assertEqual(len(again['beams']),len(changed['beams']))
        self.assertEqual(mm['wheels']['RR']['damper_ns_m'],1600.)
        self.assertNotIn('CoiloverSpring',p['Components'][1])

    def test_curvature_distinguishes_speed_and_accumulated_drift(self):
        t=np.arange(0,10,.05)
        for phase in (5*t/100,(3*t+.5*t*t)/100):
            x=100*np.sin(phase);y=100*(1-np.cos(phase))
            curvature,_=speed_analysis.path_curvature(t,x,y)
            # Finite-window cubic smoothing has a small acceleration bias;
            # bound it explicitly rather than claim exact differential curvature.
            np.testing.assert_allclose(curvature[15:-15],.01,rtol=.005,atol=1e-7)
        bad=t.copy();bad[20]+=.005
        with self.assertRaises(ValueError):speed_analysis.path_curvature(bad,x,y)

if __name__=='__main__':unittest.main()
