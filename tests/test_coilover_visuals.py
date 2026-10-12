import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import coilover_visuals as cv
import vehicle_revisions as r
from prepare_frame import write_stl


class CoiloverVisualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.component=dict(Id='shock',Name='Coilover',MvpRole='fl_spring_damper',AppearanceCoilover=dict(HousingMount='top',Pieces=[]))
        self.points={'a':[.2,.1,.8],'b':[.4,.2,.4],'roll':[.6,.1,.5],'other':[0,0,0]}
        self.part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*p,dict(nodeWeight=2,group=['shock_structure'])] for n,p in self.points.items()],
            beams=[['id1:','id2:'],['a','b',dict(beamSpring=17000,beamDamp=300,beamType='|BOUNDED')]],
            flexbodies=[['mesh','[group]:','nonFlexMaterials'],['old',['shock_structure'],[]]])
        self.manifest=dict(model='fixture_aaaaaaaa',vehicle_directory='vehicles/fixture_aaaaaaaa',kind='exported_vehicle',version=1,
            mass_allocations={'shock':{'a':1,'b':1}},template_definition={'hardpoints':{'FL':dict(shock_top=self.points['a'],shock_bottom=self.points['b'])}},
            component_parts={'shock':'fixture_aaaaaaaa'},component_meshes={'shock':['old']},render_bindings={'shock':['shock_structure']},nodes={},expected_dry_mass_kg=8)
        for index,kind in enumerate(cv.KINDS):
            folder=self.root/kind;folder.mkdir();tri=np.array([[[.2,.1,.7],[.22,.1,.7],[.2,.1,.6]]])
            # Source export convention is SolidWorks Y-up.
            sw=tri[:,:,[0,2,1]]*np.array([1,1,-1]);write_stl(folder/'part.stl',sw)
            record=dict(Id=kind,File='part.stl',AppearanceGroups=[dict(StartTriangle=0,TriangleCount=1,Appearance=dict(BaseColor=[index/3,.3,.6,1],Roughness=.3,Metallic=.5))])
            (folder/'geometry.json').write_text(json.dumps(dict(Meshes=[record])))
            self.component['AppearanceCoilover']['Pieces'].append(dict(Kind=kind,BodyIds=[kind],GeometryDirectory=str(folder)))
        self.project=dict(Identity=dict(id='a'*32,namespace='fixture_aaaaaaaa'),Components=[self.component])
        self.key='vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.jbeam'
        self.assets={self.key:r.canonical({'fixture_aaaaaaaa':self.part}),'vehicles/fixture_aaaaaaaa/fixture_aaaaaaaa.dae':b'<COLLADA/>','vehicles/fixture_aaaaaaaa/main.materials.json':b'{}',
            'vehicles/fixture_aaaaaaaa/base.pc':b'{}','vehicles/fixture_aaaaaaaa/info.json':b'{}','vehicles/fixture_aaaaaaaa/info_base.json':b'{}'}
        r.package_revision(self.root/'baseline',self.project,self.manifest,self.assets,{},'','fixture')
        self.project['LastBuildReceipt']=str(self.root/'baseline/static_frame_build.json')

    def tearDown(self):self.temp.cleanup()

    def test_rigid_pieces_use_opposing_mounts_and_preserve_authored_vertices(self):
        for mount in ('top','bottom'):
            self.component['AppearanceCoilover']['HousingMount']=mount
            meshes,names,props,flex,source,contract=cv.render(self.component,self.part,self.manifest,['shock_structure'],'test')
            self.assertEqual(len(props),2);self.assertEqual(len(flex),1)
            self.assertEqual(props[0][2],contract[mount]);self.assertEqual(props[0][3],props[1][2])
            for (record,vertices),row in zip(meshes,props):
                restored=vertices+np.array(self.points[row[2]])
                np.testing.assert_allclose(restored,[[[.2,.1,.7],[.22,.1,.7],[.2,.1,.6]]],atol=1e-7)
            self.assertEqual(contract['housing_mount'],mount)

    def test_repeated_visual_packaging_preserves_physics_and_removes_old_props(self):
        before=r.load_baseline(self.project['LastBuildReceipt'])[3]
        for index in range(2):
            output=self.root/str(index);r.replace_appearance(self.project,['shock'],output)
            self.project['LastBuildReceipt']=str(output/'static_frame_build.json')
            _,manifest,assets,after=r.load_baseline(self.project['LastBuildReceipt']);self.assertEqual(before,after)
            part=json.loads(assets[self.key])['fixture_aaaaaaaa']
            self.assertEqual(len(part['props']),3);self.assertEqual(len(part['flexbodies']),2)
            self.assertNotIn('old',str(part['flexbodies']));self.assertEqual(len(manifest['component_meshes']['shock']),3)
            self.assertEqual(len([n for n in json.loads(assets['vehicles/fixture_aaaaaaaa/main.materials.json']) if n.startswith('cad_appearance_')]),3)

    def test_partial_or_duplicate_assignment_is_rejected(self):
        pieces=self.component['AppearanceCoilover']['Pieces'];original=copy.deepcopy(pieces)
        pieces.pop()
        with self.assertRaisesRegex(ValueError,'all three'):cv.inputs(self.component)
        self.component['AppearanceCoilover']['Pieces']=original
        original[1]['GeometryDirectory']=original[0]['GeometryDirectory']
        with self.assertRaisesRegex(ValueError,'more than one'):cv.inputs(self.component)

    def test_old_projects_keep_combined_mesh_and_visual_fields_do_not_invalidate_physics(self):
        import components
        baseline=copy.deepcopy(self.project);baseline['Components'][0].pop('AppearanceCoilover')
        self.assertFalse(cv.active(baseline['Components'][0]));self.assertEqual(components.fingerprint(self.project),components.fingerprint(baseline))

    def test_missing_or_ambiguous_hardpoints_fail_without_changing_baseline(self):
        original=copy.deepcopy(self.part);bad=copy.deepcopy(self.manifest);bad['mass_allocations']['shock']={}
        with self.assertRaisesRegex(ValueError,'uniquely resolve'):cv.contract(self.component,self.part,bad,['shock_structure'])
        self.assertEqual(self.part,original)

    def test_generic_replacement_removes_old_coilover_props(self):
        cv.replace_rows(self.part,[],[['constant','housing','a','b','roll']],[])
        cv.replace_rows(self.part,['housing','old'],[],[['replacement',['shock_structure'],[]]])
        self.assertEqual(self.part['props'],[cv.PROP_HEADER]);self.assertEqual(len(self.part['flexbodies']),2)


if __name__=='__main__':unittest.main()
