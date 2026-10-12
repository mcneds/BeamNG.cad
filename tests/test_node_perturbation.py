import importlib.util,unittest,json,tempfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('node_probe',ROOT/'tools/probe-node-perturbation.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
spec=importlib.util.spec_from_file_location('node_analysis',ROOT/'tools/analyze-node-perturbation.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)

class NodePerturbationTests(unittest.TestCase):
    def test_analysis_rejects_bad_evidence_and_reports_unrecovered_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def write(name,value):(root/name).write_text(json.dumps(value))
            job=dict(id='one',scenario='node_perturbation',gravity=-9.81,fixture_fixed_nodes=[],
                     perturbed_node='FR_axis_out',duration=18.,excitation=probe.excitation('FR',0))
            completion=dict(job_id='one',status='completed',samples=360)
            write('job.json',job);write('completion.json',completion)
            write('probe.json',dict(sources_unchanged=True,completion=completion,manifest_sha256='fixture'))
            write('compiled.json',dict(fixed_nodes=0))
            meta=dict(complete=True,job_id='one',node='FR_axis_out',samples=36000)
            write('node_perturbation.json',meta)
            data=np.zeros((36000,8));data[:,0]=np.arange(1,36001)/2000
            np.savetxt(root/'node_perturbation.csv',data,delimiter=',',header='t,f,x,y,z,vx,vy,vz',comments='')
            regular=np.zeros((360,7));regular[:,0]=np.arange(1,361)/20;regular[:,4]=1.
            def save_regular():np.savetxt(root/'vehicle.csv',regular,delimiter=',',header='t,throttle,brake,broken,up_z,relative_node_speed,speed',comments='')
            save_regular()
            write('motion_diagnostics.json',dict(job_id='one',samples=[dict(steering_applied=0,steering_command=0)]*360))
            (root/'beamng.log').write_text('')
            self.assertTrue(analysis.analyze(root)['recovery_screen_passed'])
            write('node_perturbation.json',dict(meta,job_id='other'))
            with self.assertRaisesRegex(ValueError,'identity'):analysis.analyze(root)
            write('node_perturbation.json',meta)
            regular[-1,5]=.6;save_regular()
            self.assertFalse(analysis.analyze(root)['recovery_screen_passed'])
            regular[-1,5]=0;regular[12,0]=regular[11,0];save_regular()
            with self.assertRaisesRegex(ValueError,'telemetry'):analysis.analyze(root)
            job['excitation']['amplitude_n']=250;write('job.json',job)
            with self.assertRaisesRegex(ValueError,'waveform'):analysis.analyze(root)

    def test_bounded_zero_mean_and_release(self):
        e=probe.excitation('FR',1000);t=np.linspace(6,10,8001);f=np.array([probe.waveform(x,e) for x in t])
        self.assertLessEqual(max(abs(f)),1000)
        self.assertAlmostEqual(np.trapezoid(f,t),0,places=8)
        self.assertEqual(probe.waveform(0,e),0);self.assertEqual(probe.waveform(11,e),0)
        for force in (1001,float('nan'),-100):
            with self.assertRaises(ValueError):probe.excitation('FR',force)
    def test_single_node_instrument_keeps_native_validation(self):
        source=(ROOT/'dependencies/cad-calibration/Test Harness/frame_harness/lua/vehicle_recorder.lua').read_text()
        result=probe.instrument(source)
        self.assertIn('obj:applyForceVector(node,vec3(force,0,0))',result)
        self.assertNotIn('yaw_moment_nm',result)
        self.assertNotIn('setBeamSpring',result)
        self.assertIn('Compiled fixture pins differ',result)
        self.assertIn('shiftToGearIndex(0)',result)

if __name__=='__main__':unittest.main()
