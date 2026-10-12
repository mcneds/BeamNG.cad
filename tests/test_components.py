import json
from pathlib import Path
import sys
import tempfile
import shutil
import copy
import unittest
import numpy as np
from scipy.spatial import ConvexHull

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import components as module
from prepare_frame import write_stl


def box_geometry(folder,extent,offset=(0,0,0),mass=4.):
    folder.mkdir()
    import itertools
    points=np.array(list(itertools.product(*[[-e/2,e/2] for e in extent])))+offset
    hull=ConvexHull(points);faces=hull.simplices.copy()
    for i,face in enumerate(faces):
        p=points[face]
        if np.dot(np.cross(p[1]-p[0],p[2]-p[0]),hull.equations[i,:3])<0:faces[i]=face[::-1]
    triangles=points[faces]
    # Input STL is SolidWorks Y-up; tests describe BeamNG coordinates.
    cad=triangles[:,:,[0,2,1]].copy();cad[:,:,2]*=-1
    write_stl(folder/'body.stl',cad)
    module.write(folder/'geometry.json',{'Meshes':[{'Id':folder.name,'File':'body.stl','Body':'Fixture','MassKg':mass}]})
    return triangles


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='components-');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def definition(self,name,extent,offset=(0,0,0),mass=4.):
        box_geometry(self.root/name,extent,offset,mass)
        return dict(Id=name,Name=name,Template='bulk',Method='convex',GeometryDirectory=str(self.root/name),Spacing=0)
    def test_geometry_settings_distinguish_panel_and_bulk(self):
        thin=box_geometry(self.root/'thin',(1,.8,.003))
        thick=box_geometry(self.root/'thick',(.4,.5,.6))
        self.assertEqual(module.suggest(thin,2)['classification'],'panel')
        self.assertEqual(module.suggest(thick,20)['classification'],'bulk')
        self.assertGreater(module.suggest(thick,20)['alpha_m'],0)
    def test_cad_appearance_does_not_change_generated_component_physics(self):
        from prepare_frame import dae_materials
        comp=self.definition('colored',(.4,.5,.6),mass=20)
        before,_=module.generate_component(comp,[],self.root/'before-color')
        path=Path(comp['GeometryDirectory'])/'geometry.json';geometry=json.loads(path.read_text())
        geometry['Meshes'][0]['AppearanceGroups']=[dict(StartTriangle=0,TriangleCount=12,Appearance=dict(BaseColor=[.8,.05,.15,1],Roughness=.22,Metallic=.4))]
        module.write(path,geometry);after,_=module.generate_component(comp,[],self.root/'after-color')
        self.assertEqual(before,after)
        materials=dae_materials((self.root/'after-color/component.dae').read_bytes())
        self.assertEqual(next(iter(materials.values()))['Stages'][0]['baseColorFactor'],[.8,.05,.15,1])
    def test_auto_convex_shortcut_preserves_closed_boundary_and_winding(self):
        comp=self.definition('block',(.4,.5,.6),offset=(12,-4,3),mass=20);comp['Method']='auto'
        part,report=module.generate_component(comp,[],self.root/'auto')
        self.assertEqual(report['settings']['method'],'exact_convex_solid')
        self.assertEqual(report['collision_triangles'],12)
        nodes={r[0]:np.array(r[1:4]) for r in part['nodes'][1:]};center=np.array([12,-4,3])
        for face in part['triangles'][1:]:
            q=np.array([nodes[n] for n in face]);self.assertGreater(np.dot(np.cross(q[1]-q[0],q[2]-q[0]),q.mean(axis=0)-center),0)
        self.assertAlmostEqual(report['mass']['actual_mass_kg'],20)
        self.assertLess(report['mass']['inertia_relative_error'],1e-6)

    def test_explicit_box_envelope_preserves_physical_moments(self):
        comp=self.definition('housing',(.4,.5,.6),offset=(2,-1,3),mass=20);comp['Method']='oriented_box'
        part,report=module.generate_component(comp,[],self.root/'box-envelope')
        self.assertEqual(report['settings']['wrap']['selected_method'],'oriented_box')
        self.assertEqual(report['collision_triangles'],12)
        self.assertLessEqual(report['nodes'],32)
        self.assertAlmostEqual(report['mass']['actual_mass_kg'],20)
        self.assertLess(report['mass']['inertia_relative_error'],1e-6)

    def test_convex_shortcut_cannot_fill_a_closed_cavity_or_merge_bodies(self):
        outer=box_geometry(self.root/'outer',(1,1,1));inner=box_geometry(self.root/'inner',(.5,.5,.5))
        hollow=np.concatenate((outer,inner[:,::-1]))
        self.assertIsNone(module.exact_convex_solid([({},hollow)]))
        self.assertIsNone(module.exact_convex_solid([({},outer),({},inner)]))
        self.assertIsNone(module.exact_convex_solid([({'BodyKind':'surface'},outer)]))
    def test_fresh_export_paths_are_equivalent_but_changed_mass_is_not(self):
        from component_worker import geometry_inputs
        comp=self.definition('engine',(.4,.5,.6),mass=20)
        project={'Components':[comp],'LastBuildReceipt':'old'}
        baseline=geometry_inputs(project);fingerprint=module.fingerprint(project)
        moved=copy.deepcopy(project);shutil.copytree(self.root/'engine',self.root/'fresh')
        moved['Components'][0]['GeometryDirectory']=str(self.root/'fresh');moved['LastBuildReceipt']='new'
        self.assertEqual(module.fingerprint(moved),fingerprint)
        self.assertEqual(geometry_inputs(moved),baseline)
        path=self.root/'fresh/geometry.json';geometry=json.loads(path.read_text());geometry['Meshes'][0]['MassKg']=21;module.write(path,geometry)
        self.assertNotEqual(geometry_inputs(moved),baseline)
        moved['Components'][0]['Spacing']=.1
        self.assertNotEqual(module.fingerprint(moved),fingerprint)
    def test_bulk_preserves_mass_and_has_no_internal_mechanisms(self):
        comp=self.definition('engine',(.4,.5,.6),mass=20)
        part,report=module.generate_component(comp,[],self.root/'result')
        self.assertTrue(report['mass']['accepted'])
        self.assertAlmostEqual(report['mass']['actual_mass_kg'],20)
        self.assertEqual(report['rank'],3*report['nodes']-6)
        self.assertLessEqual(report['max_frequency_hz'],180.001)
    def test_panel_grid_fits_thin_material_and_owns_its_skin(self):
        comp=self.definition('panel',(1,.8,.003),mass=3);comp['Template']='panel'
        part,report=module.generate_component(comp,[],self.root/'result')
        self.assertTrue(report['mass']['accepted'])
        self.assertLess(report['collision_triangles'],200)
        self.assertTrue(all(row[1]==['panel_structure'] for row in part['flexbodies'][1:]))
        self.assertLessEqual(report['mass']['inertia_relative_error'],.010000001)
        self.assertLess(report['mass']['center_error_m'],1e-8)
        self.assertGreater(report['mass']['minimum_node_mass_kg'],.001)
        colliders={n for row in part['triangles'][1:] for n in row}
        self.assertTrue(all(row[-1]['collision']==(row[0] in colliders) for row in part['nodes'][1:]))
    def test_small_hole_inside_triangle_is_not_filled(self):
        # This opening misses the candidate's centroid and all edge midpoints.
        rectangles=[(0,0,.2,1),(.3,0,1,1),(.2,0,.3,.2),(.2,.3,.3,1)]
        source=[]
        for x,y,X,Y in rectangles:
            source.extend([[[x,y],[X,y],[X,Y]],[[x,y],[X,Y],[x,Y]]])
        source=np.array(source)
        self.assertFalse(module.covered_triangle(np.array([[0.,0.],[1.,0.],[0.,1.]]),source))
        self.assertTrue(module.covered_triangle(np.array([[.4,.1],[.9,.1],[.4,.8]]),source))
    def test_anchor_id_survives_representation_change(self):
        comp=self.definition('engine',(.4,.5,.6),mass=20)
        anchor=dict(Id='bolthole',Name='Mount',Status='resolved',Position=[.2,.2,0],ComponentId='engine')
        part,_=module.generate_component(comp,[anchor],self.root/'first')
        anchor['Position']=[.2,.2,.01]
        changed,_=module.generate_component(comp,[anchor],self.root/'second')
        def locate(p):return next(r for r in p['nodes'][1:] if r[0]=='engine_mount_bolthole')
        self.assertEqual(locate(part)[0],locate(changed)[0]);self.assertNotEqual(locate(part)[1:4],locate(changed)[1:4])
        anchor['Status']='needs_repair'
        with self.assertRaisesRegex(ValueError,'repair'):module.generate_component(comp,[anchor],self.root/'bad')
    def test_three_independent_mounts_constrain_parts_and_do_not_share_skin(self):
        frame=self.definition('frame',(1,1,.3),(0,0,0),mass=20)
        engine=self.definition('engine',(.5,.5,.4),(0,0,.5),mass=10)
        anchors=[];connections=[]
        for i,(x,y) in enumerate(((-.2,-.2),(.2,-.2),(0,.2))):
            for owner,z in [('frame',.15),('engine',.3)]:
                anchors.append(dict(Id=owner+str(i),Name='Mount',ComponentId=owner,Status='resolved',Position=[x,y,z]))
            connections.append(dict(Id='m'+str(i),Name='Fastener',AnchorA='frame'+str(i),AnchorB='engine'+str(i),Template='breakable_fastener',Spring=10000,Damping=5,Strength=1000))
        parts={}
        for comp in (frame,engine):
            parts[comp['Id']],_=module.generate_component(comp,[a for a in anchors if a['ComponentId']==comp['Id']],self.root/(comp['Id']+'-result'))
        groups,screen=module.attach(parts,anchors,connections)
        self.assertEqual(len(set(g['group'] for g in groups)),3)
        self.assertEqual(screen['rank'],screen['expected_rank'])
        self.assertTrue(all(len(g['edges'])==3 for g in groups))
        self.assertTrue(all(g['support_direction_minimum_singular_value']>=.05 for g in groups))
        for row in parts['engine']['beams'][-9:]:self.assertTrue(row[-1]['disableMeshBreaking'])
    def test_one_mount_rejects_rotational_mechanism(self):
        frame=self.definition('frame',(1,1,.3),mass=20);engine=self.definition('engine',(.5,.5,.4),(0,0,.5),mass=10)
        anchors=[dict(Id='a',Name='A',ComponentId='frame',Position=[0,0,.15],Status='resolved'),dict(Id='b',Name='B',ComponentId='engine',Position=[0,0,.3],Status='resolved')]
        parts={c['Id']:module.generate_component(c,[a for a in anchors if a['ComponentId']==c['Id']],self.root/(c['Id']+'-result'))[0] for c in (frame,engine)}
        with self.assertRaisesRegex(ValueError,'unconstrained'):
            module.attach(parts,anchors,[dict(Id='joint',Name='Mount',AnchorA='a',AnchorB='b',Template='fixed',Spring=1000,Damping=5,Strength=1000)])


if __name__=='__main__':unittest.main()
