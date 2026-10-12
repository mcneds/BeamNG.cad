import copy
import unittest
from unittest.mock import patch
from test_joint_authoring import mate, classify, resolve_bindings
import joint_inference as inference


class InferenceTests(unittest.TestCase):
    def infer(self,kind='spherical',key='RL.tie_inner',role='rl_toe_link',other='frame',sites=None,rear=None,axis_sites=None):
        joint=dict(Id='joint',Name='Native joint',Parent='host',Child='part',Kind=kind,Center=[0,0,0],Axis=[0,1,0],MateIds=['mate'],SourceHash='source')
        workspace=dict(Mates=[dict(Id='mate',Entities=[dict(ComponentId='part',Point=p) for p in (sites or [[0,0,0]])])],Joints=[],Bindings=[],Placements=[])
        project=dict(Components=[dict(Id='part',MvpRole=role),dict(Id='host',MvpRole=other)],JointWorkspace=workspace)
        if rear:project['MvpTemplates']=[dict(Category='rear_suspension',Template=rear)]
        if axis_sites:workspace['Mates'][0]['Entities'][0]['AxisSites']=axis_sites
        with patch('joint_inference.proposals',return_value=[joint]),patch('joint_inference.requests',return_value=[dict(id=key,label=key,role=role)]):
            return project,inference.rows(project)

    def test_rear_toe_inner_connects_to_chassis(self):
        _,rows=self.infer()
        self.assertEqual(rows[0]['Bindings'][0]['Request'],'RL.tie_inner')
    def test_radius_outer_connects_to_upright(self):
        _,rows=self.infer(key='RL.radius_upper_outer',role='rl_upper_radius_rod',other='rl_upright')
        self.assertEqual(rows[0]['Bindings'][0]['Request'],'RL.radius_upper_outer')

    def test_ball_pivot_variant_binds_radius_rod_to_arm(self):
        _,rows=self.infer(key='RL.radius_upper_outer',role='rl_upper_radius_rod',other='rl_trailing_arm',rear='trailing_ball_radius_toe')
        self.assertEqual(rows[0]['Bindings'][0]['Request'],'RL.radius_upper_outer')

    def test_carrier_hinge_uses_native_axis_sites_not_arbitrary_datum_origins(self):
        _,rows=self.infer(kind='revolute',key='RL.carrier_axis_a',role='rl_trailing_arm',other='rl_upright',rear='trailing_ball_radius_toe',axis_sites=[[0,-.12,0],[0,.07,0]])
        self.assertEqual(rows[0]['Anchors'][0]['Position'],[0,-.12,0])
        self.assertEqual(rows[0]['Bindings'][0]['GeneratedSource'],'joint_inference')

    def test_generated_binding_can_refresh_but_manual_binding_is_retained(self):
        project,rows=self.infer();joint=rows[0]['Joint']
        request=dict(id='RL.tie_inner',label='Tie',role='rl_toe_link')
        project['JointWorkspace']['Bindings']=rows[0]['Bindings']
        with patch('joint_inference.proposals',return_value=[joint]),patch('joint_inference.requests',return_value=[request]):
            self.assertEqual(len(inference.rows(project)[0]['Bindings']),1)
            project['JointWorkspace']['Bindings'][0].pop('GeneratedSource')
            self.assertFalse(inference.rows(project)[0]['Bindings'])

    def test_wrong_motion_is_flagged_instead_of_bound(self):
        _,rows=self.infer(kind='revolute',key='RL.carrier_ball',role='rl_trailing_arm',other='rl_upright',sites=[[0,-.1,0],[0,.1,0]])
        self.assertFalse(rows[0]['Bindings']);self.assertEqual(rows[1]['Status'],'needs_input')

    def test_distinct_native_pivots_and_stale_provenance(self):
        project,rows=self.infer(kind='revolute',key='FL.upper_inner_front',role='fl_upper_wishbone',sites=[[0,-.1,0],[0,.1,0]])
        row=rows[0];joint=row['Joint'];joint['Status']='approved'
        project['JointWorkspace'].update(Joints=[joint],Bindings=row['Bindings']);project['Anchors']=row['Anchors']
        self.assertEqual(resolve_bindings(project)['FL.upper_inner_front'],[0,-.1,0])
        joint['SourceHash']='changed'
        with self.assertRaisesRegex(ValueError,'site changed'):resolve_bindings(project)

    def test_single_axis_site_is_not_invented_into_two_pivots(self):
        _,rows=self.infer(kind='revolute',key='FL.upper_inner_front',role='fl_upper_wishbone')
        self.assertFalse(rows[0]['Bindings']);self.assertIn('two distinct',rows[1]['Issue'])

    def test_single_ball_does_not_supply_paired_hinge_sites(self):
        for key,role in [('RL.hinge_inner','rl_trailing_arm'),('RL.hinge_outer','rl_trailing_arm'),('FL.upper_inner_front','fl_upper_wishbone'),('FL.upper_inner_rear','fl_upper_wishbone')]:
            with self.subTest(key=key):
                _,rows=self.infer(key=key,role=role)
                self.assertFalse(rows[0]['Bindings'])
                self.assertEqual(rows[1]['Status'],'needs_input')
                self.assertIn('single ball centre',rows[1]['Issue'])

    def test_shaft_endpoint_requires_exact_joint_center(self):
        _,rows=self.infer(key='RL.unused',role='rl_halfshaft',other='rear_final_drive')
        found=[b for r in rows for b in r.get('Bindings',[]) if b['Request']=='part.inner_joint']
        self.assertEqual(len(found),1)
        _,rows=self.infer(kind='cylindrical',key='RL.unused',role='rl_halfshaft',other='rear_final_drive')
        self.assertFalse([b for r in rows for b in r.get('Bindings',[]) if b['Request']=='part.inner_joint'])

    def test_point_axis_and_circle_plane_combine_into_hinge(self):
        concentric=mate('CONCENTRIC','cylinder')
        stop=mate('COINCIDENT','plane');stop['Entities'][0]['Kind']='circle'
        self.assertEqual(classify([concentric,stop])['Kind'],'revolute')
        point_line=mate('COINCIDENT');point_line['Entities'][1]['Kind']='line'
        self.assertEqual(classify([point_line])['Kind'],'point_on_axis')
        self.assertEqual(classify([point_line])['DegreesOfFreedom'],4)
        offset=copy.deepcopy(point_line);offset['Entities'][0]['Point'][0]+=.01
        with self.assertRaisesRegex(ValueError,'not on axis'):classify([offset])


if __name__=='__main__':unittest.main()
