import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_components import module,box_geometry
from test_surface_components import sheet_geometry
import auto_connect as auto
import component_representation as representation


class AutoConnectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def project(self):
        box_geometry(self.root/'frame',(1.2,1.,.1),(0,0,-.08),mass=20)
        sheet_geometry(self.root/'panel')
        return dict(Components=[dict(Id='frame',Name='Frame',MvpRole='frame',Template='calibrated_frame',GeometryDirectory=str(self.root/'frame')),
          dict(Id='panel',Name='Panel',MvpRole='panel_front',Template='panel',Thickness=.002,SurfaceMassMode='thickness',GeometryDirectory=str(self.root/'panel'))],Anchors=[],Connections=[],JointWorkspace=dict(Placements=[dict(ComponentId='frame',Fixed=True),dict(ComponentId='panel',Fixed=True)]))
    def preview(self,p):
        with patch('joint_inference.rows',return_value=[]):return auto.proposals(p)
    def test_corners_inward_support_and_independent_editable_bolts(self):
        p=self.project();before=copy.deepcopy(p);result=self.preview(p);row=next(r for r in result['Rows'] if r['Id']=='panel')
        self.assertEqual(row['Status'],'ready');self.assertEqual(len(row['Connections']),4);self.assertEqual(p,before)
        for mount in row['Connections']:
            self.assertEqual(mount['ReleaseSet'],'');self.assertLess(mount['Normal'][2],0);self.assertAlmostEqual(mount['SupportPosition'][2],-.03)
        applied=auto.apply(p,[row]);second=auto.apply(applied,[row]);self.assertEqual(applied,second)
        edited=copy.deepcopy(applied);edited['Connections'][0]['Strength']=1234
        self.assertEqual(next(r for r in self.preview(edited)['Rows'] if r['Id']=='panel')['Status'],'manual')
        with self.assertRaisesRegex(ValueError,'Manual/edited'):auto.apply(edited,[row])
    def test_missing_support_does_not_create_connections(self):
        p=self.project()
        with patch('joint_inference.rows',return_value=[]):result=auto.proposals(p,search=.001)
        row=next(r for r in result['Rows'] if r['Id']=='panel');self.assertEqual(row['Status'],'needs_input');self.assertNotIn('Connections',row)
    def test_save_reload_numeric_format_preserves_generated_bolts(self):
        p=self.project();row=next(r for r in self.preview(p)['Rows'] if r['Id']=='panel');saved=auto.apply(p,[row])
        for bolt in saved['Connections']:
            bolt['Strength']=int(bolt['Strength']);bolt['Spring']=0;bolt['Damping']=0
            bolt['Normal']=[int(v) if v==int(v) else v for v in bolt['Normal']]
        self.assertEqual(next(r for r in self.preview(saved)['Rows'] if r['Id']=='panel')['Status'],'ready')
    def test_fixed_moving_role_flagged(self):
        p=self.project();p['Components'][1]['MvpRole']='fl_wheel'
        row=next(r for r in self.preview(p)['Rows'] if r['Id']=='panel');self.assertIn('moving role',row['Issue'])
    def test_winding_does_not_change_corner_positions(self):
        t=sheet_geometry(self.root/'shape');a=auto.panel_sites(t);b=auto.panel_sites(t[:,::-1]);np.testing.assert_allclose([p for p,n in a],[p for p,n in b])
    def test_closed_solid_panel_with_different_skin_triangulations(self):
        t=box_geometry(self.root/'solid-panel',(1.,.6,.002));sites=auto.panel_sites(t)
        self.assertEqual(len(sites),4)
        for p,n in sites:self.assertLess(abs(p[0]),.5);self.assertLess(abs(p[1]),.3);self.assertAlmostEqual(abs(p[2]),.001)


class RepresentationTests(AutoConnectTests):
    def test_zero_mass_is_never_silent(self):
        p=self.project();skin=p['Components'][1];skin.update(MassPolicy='exclude',Representation='physical')
        with self.assertRaisesRegex(ValueError,'zero mass'):representation.validate(p,module.read_geometry)
        skin.update(Representation='visual_only',VisualParentId='frame')
        with self.assertRaisesRegex(ValueError,'acknowledge'):representation.validate(p,module.read_geometry)
        skin['MassAcknowledgement']=representation.acknowledgement(skin);representation.validate(p,module.read_geometry)
        skin['Thickness']=.004
        with self.assertRaisesRegex(ValueError,'acknowledge'):representation.validate(p,module.read_geometry)
    def test_visual_mass_transfers_once_with_parallel_axis_inertia(self):
        p=self.project();skin=p['Components'][1];skin.update(Representation='visual_only',VisualParentId='frame',MassPolicy='custom',CustomMassKg=2.)
        baseline=module.read_geometry(p['Components'][0])[1];visual=module.read_geometry(skin)[1];actual,report=representation.physical_project(p,module.read_geometry)
        self.assertEqual(len(actual['Components']),1);moments=module.read_geometry(actual['Components'][0])[1];expected=representation.combine([baseline,visual])
        for x,y in zip(moments,expected):np.testing.assert_allclose(x,y)
        self.assertEqual(moments[0],22.);self.assertNotIn('_VisualMass',p['Components'][0]);self.assertEqual(len(report['contributions']),1)
    def test_visual_parent_chain_is_rejected(self):
        p=self.project();p['Components'][1].update(Representation='visual_only',VisualParentId='panel')
        with self.assertRaisesRegex(ValueError,'physical visual parent'):representation.validate(p,module.read_geometry)
    def test_custom_sheet_mass_without_material(self):
        sheet_geometry(self.root/'no-material',density=0)
        comp=dict(GeometryDirectory=str(self.root/'no-material'),MassPolicy='custom',CustomMassKg=3.,Thickness=0)
        self.assertAlmostEqual(module.read_geometry(comp)[1][0],3.)
    def test_combined_mass_is_fitted_on_existing_graph_without_changing_beams(self):
        import itertools
        from frame_harness.build import node_table
        xyz=list(itertools.product((-.6,0,.6),(-.5,0,.5),(-.13,-.08,-.03,0)))
        part=dict(nodes=[['id','posX','posY','posZ']]+[[str(i),*p,dict(nodeWeight=1)] for i,p in enumerate(xyz)],beams=[['id1:','id2:'],['0','1',dict(beamSpring=1234)]])
        p=self.project();p['Components'][1].update(Representation='visual_only',VisualParentId='frame',MassPolicy='custom',CustomMassKg=2.)
        physical,_=representation.physical_project(p,module.read_geometry);moments=module.read_geometry(physical['Components'][0])[1]
        original=copy.deepcopy(part['beams']);report=representation.refit_existing_part(part,moments);nodes=node_table(part)
        masses=np.array([n['mass'] for n in nodes.values()]);positions=np.array([n['position'] for n in nodes.values()])
        self.assertTrue(report['accepted']);self.assertEqual(part['beams'],original);self.assertTrue((masses>0).all())
        self.assertAlmostEqual(sum(masses),22.,places=6);np.testing.assert_allclose((masses[:,None]*positions).sum(axis=0)/sum(masses),moments[1],atol=1e-5)
        r=positions-moments[1];inertia=sum(m*(v@v*np.eye(3)-np.outer(v,v)) for m,v in zip(masses,r))
        self.assertLess(np.linalg.norm(inertia-moments[2])/np.linalg.norm(moments[2]),1e-4)
    def test_carried_mass_never_reduces_sealed_host_node_mass(self):
        import itertools
        xyz=np.array(list(itertools.product((-1.,1.),repeat=3)))
        original=np.arange(1.,9.)
        part=dict(nodes=[['id','posX','posY','posZ']]+[[str(i),*p,dict(nodeWeight=m)] for i,(p,m) in enumerate(zip(xyz,original))],
                  beams=[['id1:','id2:'],['0','1',dict(beamSpring=1234)]])
        beams=copy.deepcopy(part['beams'])
        report=representation.refit_existing_part(part,None,[dict(mass=2.,center=[0,0,0],inertia=(4*np.eye(3)).tolist())])
        added=np.array([v[-1]['nodeWeight'] for v in part['nodes'][1:]])-original
        self.assertTrue(report['accepted']);self.assertTrue((added>0).all())
        self.assertAlmostEqual(added.sum(),2.);np.testing.assert_allclose(added@xyz,0,atol=1e-10)
        inertia=sum(m*(p@p*np.eye(3)-np.outer(p,p)) for m,p in zip(added,xyz))
        np.testing.assert_allclose(inertia,4*np.eye(3),atol=1e-10);self.assertEqual(part['beams'],beams)

    def test_custom_mass_is_partitioned_between_moving_members(self):
        import json,shutil
        from translating_rack import member_component
        box_geometry(self.root/'small',(1,1,1));box_geometry(self.root/'large',(2,1,1))
        whole=self.root/'whole';whole.mkdir();meshes=[]
        for name in ('small','large'):
            mesh=json.loads((self.root/name/'geometry.json').read_text())['Meshes'][0];mesh['File']=name+'.stl';meshes.append(mesh);shutil.copy2(self.root/name/'body.stl',whole/mesh['File'])
        module.write(whole/'geometry.json',dict(Meshes=meshes))
        parent=dict(Id='rack',Name='Rack',MassPolicy='custom',CustomMassKg=12.,GeometryDirectory=str(whole))
        p=dict(Components=[parent],JointWorkspace=dict(Members=[dict(Id=n,Name=n,ComponentId='rack',GeometryDirectory=str(self.root/n),BodyIds=[n],Selections=[]) for n in ('small','large')]))
        self.assertAlmostEqual(module.read_geometry(member_component(p,'rack','small'))[1][0],4.)
        self.assertAlmostEqual(module.read_geometry(member_component(p,'rack','large'))[1][0],8.)


if __name__=='__main__':unittest.main()
