import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import property_revisions as p
import vehicle_revisions as r
import components as c


class PropertyRevisionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project=dict(Identity=dict(id='a'*32,namespace='fixture_aaaaaaaa'),Components=[dict(Id='engine',Template='bulk',Name='Engine')])
        self.xyz=np.array([[0.,0,0],[1,0,0],[0,1,0],[0,0,1]])
        self.center=self.xyz.mean(axis=0);rr=self.xyz-self.center
        self.inertia=sum(np.dot(v,v)*np.eye(3)-np.outer(v,v) for v in rr)
        nodes={str(i):dict(position=v.tolist(),mass_kg=6. if i==0 else 1.,component='engine') for i,v in enumerate(self.xyz)}
        part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*v['position'],dict(nodeWeight=v['mass_kg'])] for n,v in nodes.items()],
                  beams=[['id1:','id2:'],['0','1',dict(beamSpring=1000.,beamDamp=5.)]],
                  torsionbars=[['id1:','id2:','id3:','id4:'],['0','1','2','3',dict(spring=100.,damp=10.)]],
                  flexbodies=[['mesh','[group]:'],['same_mesh',['engine']]])
        prefix='vehicles/fixture_aaaaaaaa/'
        assets={prefix+'fixture_aaaaaaaa.jbeam':r.canonical({'fixture_aaaaaaaa':part}),prefix+'fixture_aaaaaaaa.dae':b'<COLLADA/>',prefix+'base.pc':b'{}',prefix+'main.materials.json':b'{}',prefix+'info.json':b'{}',prefix+'info_base.json':b'{}'}
        manifest=dict(kind='exported_vehicle',version=1,model='fixture_aaaaaaaa',component_parts={'engine':'fixture_aaaaaaaa'},nodes=nodes,
                      mass_allocations={'engine':{str(i):1. for i in range(4)},'neighbour':{'0':5.}},expected_dry_mass_kg=9.)
        r.package_revision(self.root/'baseline',self.project,manifest,assets,{'fixture.json':b'{}'},'','Unit test fixture')
        self.receipt=self.root/'baseline/static_frame_build.json';self.project['LastBuildReceipt']=str(self.receipt)
    def tearDown(self):self.temp.cleanup()
    def test_support_mass_requires_assembled_regeneration_without_mutating_baseline(self):
        baseline=r.load_baseline(self.receipt)
        manifest=copy.deepcopy(baseline[1]);manifest['numerical_mass']={'added_mass_kg':3.}
        with patch.object(p,'load_baseline',return_value=(baseline[0],manifest,*baseline[2:])),self.assertRaisesRegex(ValueError,'Regenerate vehicle physics'):
            p.recalibrate_component(self.project,'engine',self.root/'blocked')
        self.assertFalse((self.root/'blocked').exists())
        self.assertEqual(r.load_baseline(self.receipt)[3],baseline[3])
    def test_properties_fit_preserves_graph_render_and_neighbour_mass(self):
        old=self.receipt.read_bytes();before=r.load_baseline(self.receipt)
        with patch.object(c,'read_geometry',return_value=([],(8.,self.center,self.inertia*2),{})),patch('component_worker.geometry_inputs',return_value={'engine':{'geometry.json':'changed'}}):
            p.recalibrate_component(self.project,'engine',self.root/'fit')
        _,manifest,assets,snapshot=r.load_baseline(self.root/'fit/static_frame_build.json')
        self.assertEqual(p.topology(assets),p.topology(before[2]))
        self.assertEqual(manifest['mass_allocations']['neighbour'],{'0':5.})
        self.assertAlmostEqual(manifest['nodes']['0']['mass_kg'],7.)
        self.assertAlmostEqual(manifest['expected_dry_mass_kg'],13.)
        self.assertNotEqual(before[3]['sha256'],snapshot['sha256'])
        for name in assets:
            if not name.endswith('.jbeam'):self.assertEqual(assets[name],before[2][name])
        self.assertEqual(self.receipt.read_bytes(),old)
    def test_impossible_fixed_graph_fit_leaves_baseline_usable(self):
        before=r.load_baseline(self.receipt)[3]
        with patch.object(c,'read_geometry',return_value=([],(8.,self.center+10,self.inertia*2),{})),patch('component_worker.geometry_inputs',return_value={}),self.assertRaisesRegex(ValueError,'cannot fit'):
            p.recalibrate_component(self.project,'engine',self.root/'rejected')
        self.assertEqual(r.load_baseline(self.receipt)[3],before)
        self.assertFalse((self.root/'rejected').exists())

    def test_lighter_material_does_not_raise_angular_damping_per_unit_mass(self):
        from rigid_bracing import gradient
        before=r.load_baseline(self.receipt)
        with patch.object(c,'read_geometry',return_value=([],(1.,self.center,self.inertia/4),{})),patch('component_worker.geometry_inputs',return_value={}):
            p.recalibrate_component(self.project,'engine',self.root/'lighter')
        after=r.load_baseline(self.root/'lighter/static_frame_build.json')
        def angular_bound(data):
            part=next(iter(json.loads(next(v for k,v in data[2].items() if k.endswith('.jbeam'))).values()))
            row=part['torsionbars'][1];nodes=p.node_table(part)
            g=gradient(np.array([nodes[n]['position'] for n in row[:4]]))
            return row[4]['damp']*sum(np.dot(v,v)/nodes[n]['options']['nodeWeight'] for n,v in zip(row[:4],g))
        self.assertLessEqual(angular_bound(after),angular_bound(before)*(1+1e-10))
        self.assertEqual(p.topology(after[2]),p.topology(before[2]))


if __name__=='__main__':unittest.main()
