import importlib.util
from pathlib import Path
import unittest
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))

spec=importlib.util.spec_from_file_location('frequency',Path(__file__).resolve().parents[1]/'tools/analyze-suspension-frequency.py')
frequency=importlib.util.module_from_spec(spec);spec.loader.exec_module(frequency)

class FrequencyTests(unittest.TestCase):
    def test_coherence_averages_multiple_segments_for_short_capture(self):
        rng=np.random.default_rng(107);a=rng.normal(size=4000);b=rng.normal(size=4000)
        result=frequency.averaged_coherence(a,b,2000,16)
        self.assertEqual(result['overlapping_segments'],3)
        self.assertLess(result['coherence_at_peak'],.9)
        self.assertAlmostEqual(frequency.averaged_coherence(a,a,2000,16)['coherence_at_peak'],1.)

    def test_speed_window_rejects_missing_nonfinite_and_off_target_samples(self):
        from steady_speed_control import settings
        job={'steady_speed':settings(15.)};meta={'config':{'start_s':40.,'duration_s':2.}}
        data=np.zeros(1100,dtype=[('t',float),('speed',float),('broken',float)])
        data['t']=np.arange(1,1101)*.05;data['speed']=15
        frequency.validate_speed_window(job,meta,data)
        for field,value in [('speed',float('nan')),('speed',14.),('broken',1.)]:
            bad=data.copy();bad[field][820]=value
            with self.assertRaises(ValueError):frequency.validate_speed_window(job,meta,bad)
        for bad in (data[:820],np.delete(data,820)):
            with self.assertRaises(ValueError):frequency.validate_speed_window(job,meta,bad)

    def test_targets_preserve_steps_and_reject_misaligned_or_incomplete_records(self):
        t=np.arange(200)/2000
        a=np.column_stack([t,np.where(t<.05,.4,.41),np.full(200,.4),np.full(200,.5),np.full(200,.5)])
        meta=dict(job_id='one',complete=True,samples=200,actuators=[dict(corner='FL'),dict(corner='FR')])
        result=frequency.validate_targets(t,a,meta,'one')
        self.assertEqual(result['FL'][99],.4);self.assertEqual(result['FL'][100],.41)
        for bad in (dict(meta,job_id='two'),dict(meta,complete=False),dict(meta,actuators=list(reversed(meta['actuators'])))):
            with self.assertRaises(ValueError):frequency.validate_targets(t,a,bad,'one')
        for bad in (a[:-1],a.copy()):
            if len(bad)==len(a):bad[1,0]+=.0001
            with self.assertRaises(ValueError):frequency.validate_targets(t,bad,meta,'one')
        a[0,1]=np.nan
        with self.assertRaises(ValueError):frequency.validate_targets(t,a,meta,'one')

    def test_recorded_path_uses_each_target_and_rejects_unconverged_reference(self):
        from types import SimpleNamespace
        mechanism=SimpleNamespace(p={'hub':np.zeros(3)},constraints=lambda x,e:np.array([x-e]))
        predictor=SimpleNamespace(mechanisms={'FL':mechanism},previous={})
        def solve(c,h,e):
            predictor.previous[c]=e
            return {'hub':np.array([e,0.,h])}
        predictor.solve=solve
        values,error=frequency.solve_recorded_path(predictor,'FL',[0.,.01,.02],[0.,.03,.03],['hub'])
        np.testing.assert_allclose(values[:,0,0],[0.,.03,.03]);self.assertEqual(error,0.)
        mechanism.constraints=lambda x,e:np.array([2e-7])
        with self.assertRaisesRegex(ValueError,'converge'):frequency.solve_recorded_path(predictor,'FL',[0.],[0.],['hub'])

    def test_rejects_graphics_snapshots_repeated_at_physics_rate(self):
        t=np.arange(8000)/2000
        held=np.repeat(np.arange(80),100)[:,None,None]*np.ones((1,3,3))
        with self.assertRaisesRegex(ValueError,'stale/held'):frequency.validate_fresh_positions(t,held)
        frequency.validate_fresh_positions(t,t[:,None,None]*np.ones((1,3,3)))

    def test_resolves_known_tone_and_rejects_gap(self):
        t=np.arange(8000)/2000;signal=3+2*np.sin(2*np.pi*137*t)
        result=frequency.spectrum(t,signal)
        self.assertAlmostEqual(result['peaks'][0]['hz'],137,places=5)
        self.assertAlmostEqual(result['ac_rms'],np.sqrt(2),places=5)
        self.assertAlmostEqual(result['mean'],3,places=5)
        with self.assertRaises(ValueError):frequency.spectrum(np.delete(t,100),np.delete(signal,100))

    def test_hinge_residual_ignores_intended_rotation_and_translation(self):
        rest=np.array([[0.,0.,0.],[1.,0.,0.],[.3,.7,0.]])
        theta=np.linspace(-1,1,100);moving=np.repeat(rest[None],100,axis=0)
        moving[:,2,1]=.7*np.cos(theta);moving[:,2,2]=.7*np.sin(theta)
        moving+=np.array([100,200,300])
        expected=np.repeat(frequency.hinge_coordinates(rest)[None],100,axis=0)
        np.testing.assert_allclose(frequency.hinge_coordinates(moving),expected,atol=1e-12)
        moving[:,2,0]+=.002
        np.testing.assert_allclose((frequency.hinge_coordinates(moving)-expected)[:,0],.002,atol=1e-12)

if __name__=='__main__':unittest.main()
