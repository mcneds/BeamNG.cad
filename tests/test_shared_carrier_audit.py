import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('shared_audit',Path(__file__).resolve().parents[1]/'tools/audit-shared-carrier-inputs.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class SharedCarrierAuditTests(unittest.TestCase):
    def fixture(self,root):
        m=dict(component_roles={'carrier':'fl_upright','shaft':'fl_halfshaft'},geometry_inputs_sha256={'cad':'abc'},cad_dry_mass_kg=5.,
            template_definition=dict(hardpoints={'hub':[1,0,0]},halfshafts={'shaft':{'outer':[1,0,0],'plunge_m':.06}}),
            nodes={'shaft_outer':dict(position=[1,0,0],mass_kg=2.),'carrier_mass_0':dict(position=[0,1,0],mass_kg=2.)},
            mass_allocations={'carrier':{'carrier_mass_0':2.},'shaft':{'shaft_outer':2.}},
            joints=[dict(id='shaft_outer',kind='spherical',parent='carrier',child='shaft',nodes=['carrier_mass_0','shaft_outer'])],
            wheels={'FL':dict(spring_n_m=1000,damper_ns_m=100,spring_preload_n=50,tire_contract={'radius':.3})},
            numerical_mass={'nodes':{'shaft_outer':{},'carrier_mass_0':{}}},expected_dry_mass_kg=6.)
        b=copy.deepcopy(m);b['joints'][0].update(kind='shared_ball',nodes=['shaft_outer']);b['mass_allocations']['carrier']['shaft_outer']=1.
        b['mass_allocations']['shaft']['shaft_outer']=1.;b['nodes']['carrier_mass_0']['position']=[0,1.1,0]
        folders=[]
        for name,data in [('before',m),('after',b)]:
            folder=root/name;folder.mkdir();folders.append(folder)
            (folder/'manifest.json').write_text(json.dumps(data))
            payload=json.dumps({'part':{'pressureWheels':[['name'],['FL',{'radius':.3}]]}}).encode()
            (folder/'main.jbeam').write_bytes(payload)
            (folder/'static_frame_build.json').write_text(json.dumps({'component_files':{'main.jbeam':hashlib.sha256(payload).hexdigest()}}))
        return folders

    def test_sharing_preserves_controls_and_allows_only_quadrature_movement(self):
        with tempfile.TemporaryDirectory() as temp:
            folders=self.fixture(Path(temp));r=mod.audit(*folders)
            self.assertEqual(len(r['shared_joints']),1)
            self.assertEqual(r['relocated_quadrature_nodes'],['carrier_mass_0'])

    def test_rejects_changed_center_spring_plunge_or_floor(self):
        mutations=[lambda m:m['nodes']['shaft_outer'].update(position=[1.01,0,0]),
            lambda m:m['wheels']['FL'].update(spring_n_m=900),
            lambda m:m['template_definition']['halfshafts']['shaft'].update(plunge_m=.08),
            lambda m:m['nodes']['shaft_outer'].update(mass_kg=1.99)]
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as temp:
                folders=self.fixture(Path(temp));p=folders[1]/'manifest.json';m=json.loads(p.read_bytes());mutate(m);p.write_text(json.dumps(m))
                with self.assertRaises(ValueError):mod.audit(*folders)

    def test_explicit_sparse_mode_only_removes_carrier_quadrature(self):
        with tempfile.TemporaryDirectory() as temp:
            folders=self.fixture(Path(temp));p=folders[1]/'manifest.json';m=json.loads(p.read_bytes())
            del m['nodes']['carrier_mass_0'];del m['mass_allocations']['carrier']['carrier_mass_0'];del m['numerical_mass']['nodes']['carrier_mass_0']
            p.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'identity'):mod.audit(*folders)
            m['template_definition']['parameters']={'upright_representation':'hardpoint_lumped'};p.write_text(json.dumps(m))
            self.assertEqual(mod.audit(*folders)['removed_quadrature_nodes'],['carrier_mass_0'])

    def test_sparse_brake_reaction_requires_same_owner_and_nondegenerate_lever(self):
        with tempfile.TemporaryDirectory() as temp:
            folders=self.fixture(Path(temp))
            for i,folder in enumerate(folders):
                p=folder/'manifest.json';m=json.loads(p.read_bytes())
                m['nodes'].update(axis_a=dict(position=[0,0,0],mass_kg=2.),axis_b=dict(position=[0,0,1],mass_kg=2.))
                arm='carrier_mass_0'
                if i:
                    arm='shaft_outer';m['template_definition']['parameters']={'upright_representation':'hardpoint_lumped'}
                    del m['nodes']['carrier_mass_0'];del m['mass_allocations']['carrier']['carrier_mass_0'];del m['numerical_mass']['nodes']['carrier_mass_0']
                m['wheels']['FL']['brake_reaction_node']=arm;p.write_text(json.dumps(m))
                wheel=['FL','rim','tire','axis_a','axis_b',9999,arm,-1,{'brakeTorque':100}]
                payload=json.dumps({'part':{'pressureWheels':[['name'],wheel]}}).encode();(folder/'main.jbeam').write_bytes(payload)
                (folder/'static_frame_build.json').write_text(json.dumps({'component_files':{'main.jbeam':hashlib.sha256(payload).hexdigest()}}))
            report=mod.audit(*folders)
            self.assertEqual(report['brake_reaction_changes'][0]['after'],'shaft_outer')
            # Removing its carrier ownership invalidates a superficially valid lever.
            p=folders[1]/'manifest.json';m=json.loads(p.read_bytes());del m['mass_allocations']['carrier']['shaft_outer'];p.write_text(json.dumps(m))
            with self.assertRaises(ValueError):mod.audit(*folders)

    def test_rigid_visual_rebase_reconstructs_rest_vertices(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'part.dae'
            path.write_text('<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema"><library_geometries><geometry id="g" name="mesh"><mesh><source id="positions"><float_array>0 0 0 1 0 0 0 1 0</float_array></source><vertices><input semantic="POSITION" source="#positions"/></vertices></mesh></geometry></library_geometries></COLLADA>')
            zero={'x':0,'y':0,'z':0};part={'props':[['header'],['constant','mesh','anchor','x','y',zero,zero,zero,0,0,0,1,{'baseRotationGlobal':zero,'baseTranslation':zero}]]}
            positions,_=mod.rest_mesh(path,part,{'nodes':{'anchor':{'position':[3,4,5]}}})
            self.assertEqual(positions['mesh'].tolist(),[[3,4,5],[4,4,5],[3,5,5]])
            part['props'][1][7]={'x':1,'y':0,'z':0}
            with self.assertRaises(ValueError):mod.rest_mesh(path,part,{'nodes':{'anchor':{'position':[3,4,5]}}})


if __name__=='__main__':unittest.main()
