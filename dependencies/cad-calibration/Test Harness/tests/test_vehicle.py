import csv
import json
from pathlib import Path
import tempfile
import threading
import unittest
import math
from frame_harness.vehicle import analyze,intake,run_acceptance
from frame_harness.build import sha256,write_json

def fixture_capture(path):
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(128,128),'gray')
    ImageDraw.Draw(image).rectangle((20,20,100,100),fill='blue')
    image.save(path,compress_level=0)


class GenericVehicleTests(unittest.TestCase):
    def test_compiled_paired_hydros_require_both_distinct_declared_supports(self):
        from frame_harness.vehicle import steering_compiled
        contract=dict(actuators=[dict(nodes=['left','rack']),dict(nodes=['right','rack'])],
                      rail_nodes={'r':['a','b']},rail_sliders={'rack':'r'})
        actual=dict(hydros=[['rack','right'],['rack','left']],rails={'r':dict(nodes=['a','b'],capped=True)},sliders={'rack':dict(rail='r',attached=True,fixed=True)})
        self.assertTrue(steering_compiled(contract,actual))
        for rows in ([],[['left','rack']],[['left','rack'],['rack','left']],actual['hydros']+[['left','rack']]):
            self.assertFalse(steering_compiled(contract,actual|dict(hydros=rows)))

    def test_full_circle_does_not_lose_turn_direction_when_returning_near_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);columns=['t','speed','forward_speed','forward_distance','lateral_distance','distance','up_z','relative_node_speed','broken','rpm','cvt_ratio','throttle','brake']
            write_json(root/'compiled.json',{'mass_kg':100});fixture_capture(root/'final.png')
            for direction,scenario in ((1,'left_turn'),(-1,'right_turn')):
                with (root/'vehicle.csv').open('w',newline='') as stream:
                    out=csv.DictWriter(stream,fieldnames=columns);out.writeheader()
                    for i in range(221):
                        theta=2*math.pi*max(0,i-40)/180
                        out.writerow(dict.fromkeys(columns,0)|dict(t=i*.1,up_z=1,speed=2.,forward_speed=2.,
                            forward_distance=5*math.sin(theta),lateral_distance=direction*5*(1-math.cos(theta)),distance=theta*5))
                completion=dict(status='completed',samples=221)
                result=analyze(root,dict(expected_dry_mass_kg=100),scenario,completion)
                self.assertTrue(result['checks']['turns_requested_direction'])
                opposite='right_turn' if direction==1 else 'left_turn'
                self.assertFalse(analyze(root,dict(expected_dry_mass_kg=100),opposite,completion)['checks']['turns_requested_direction'])

    def test_compiled_hydro_endpoint_order_does_not_change_its_identity(self):
        from frame_harness.vehicle import steering_compiled
        contract=dict(actuator_nodes=['base','rack'],rail_nodes={'r':['a','b']},rail_sliders={'rack':'r'})
        actual=dict(hydros=[['rack','base']],rails={'r':dict(nodes=['a','b'],capped=True)},sliders={'rack':dict(rail='r',attached=True,fixed=True)})
        self.assertTrue(steering_compiled(contract,actual))
        for hydros in ([],[['rack','other']],[['rack','rack']],[['rack','base'],['base','rack']]):
            self.assertFalse(steering_compiled(contract,actual|dict(hydros=hydros)))
    def test_native_rack_requires_correct_capped_rails_and_only_one_actuator(self):
        import copy
        from frame_harness.vehicle import steering_compiled
        contract=dict(actuator_nodes=['base','rack'],rail_nodes={'r':['a','b']},rail_sliders={'rack':'r'})
        actual=dict(hydros=[['base','rack']],rails={'r':dict(nodes=['a','b'],capped=True)},sliders={'rack':dict(rail='r',attached=True,fixed=True)})
        self.assertTrue(steering_compiled(contract,actual))
        for change in ('missing','wrong_node','uncapped','detached','extra_actuator'):
            altered=copy.deepcopy(actual)
            if change=='missing':altered={}
            elif change=='wrong_node':altered['rails']['r']['nodes'][0]='wrong'
            elif change=='uncapped':altered['rails']['r']['capped']=False
            elif change=='detached':altered['sliders']['rack']['attached']=False
            else:altered['hydros'].append(['left','right'])
            self.assertFalse(steering_compiled(contract,altered),change)
    def test_nonfinite_completion_becomes_archivable_failure(self):
        from frame_harness.vehicle import finite_completion
        raw=dict(status='completed',job_id='test',final_node_positions={'wheel':[float('-inf'),0,0]})
        safe=finite_completion(raw)
        self.assertEqual(safe['status'],'failed');self.assertEqual(safe['job_id'],'test')
        self.assertIn('nonfinite',safe['reason']);json.dumps(safe,allow_nan=False)
        self.assertEqual(raw['status'],'completed')
        self.assertEqual(analyze('.',{},'settle',safe)['qualification_status'],'not_qualified')
    def test_intake_checks_every_exported_file_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'vehicles/custom';folder.mkdir(parents=True);write_json(folder/'base.pc',{})
            m={'version':1,'kind':'exported_vehicle','model':'custom','vehicle_directory':'vehicles/custom','config':'base.pc',
               'nodes':{'one':{}},'fixed_nodes':[],'files':{'vehicles/custom/base.pc':sha256(folder/'base.pc')}}
            write_json(root/'manifest.json',m);self.assertEqual(intake(root/'manifest.json')[1],folder)
            m['files']['../outside.txt']='bad';write_json(root/'manifest.json',m)
            with self.assertRaises(ValueError):intake(root/'manifest.json')
    def test_cancelled_acceptance_before_first_run_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'manifest.json';event=threading.Event();event.set();result=run_acceptance(p,cancel=event)
            self.assertEqual(result['status'],'failed');self.assertEqual(result['completed_runs'],0)
            self.assertEqual(result['recording_status'],'cancelled')
            self.assertEqual(result['qualification_status'],'not_qualified')
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_completion_alone_cannot_pass_short_or_damaged_recordings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);columns=['t','speed','forward_speed','forward_distance','lateral_distance','distance','up_z','relative_node_speed','broken','rpm','cvt_ratio','throttle','brake']
            def write(broken=0,end=30):
                with (root/'vehicle.csv').open('w',newline='') as stream:
                    out=csv.DictWriter(stream,fieldnames=columns);out.writeheader()
                    for i in range(31):out.writerow(dict.fromkeys(columns,0)|{'t':i*end/30,'up_z':1,'broken':broken})
            write_json(root/'compiled.json',{'mass_kg':100});fixture_capture(root/'final.png')
            completion={'status':'completed','samples':31};manifest={'expected_dry_mass_kg':100}
            write();self.assertEqual(analyze(root,manifest,'settle',completion)['status'],'passed')
            write(broken=1);self.assertEqual(analyze(root,manifest,'settle',completion)['status'],'failed')
            write(end=10);self.assertIn('early',analyze(root,manifest,'settle',completion)['reason'])
            write();completion['samples']=32;self.assertEqual(analyze(root,manifest,'settle',completion)['reason'],'Incomplete telemetry')


if __name__=='__main__':unittest.main()
