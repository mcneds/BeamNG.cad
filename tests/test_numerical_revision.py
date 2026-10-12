import copy,itertools,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from numerical_revision import condition,build


class NumericalRevisionTests(unittest.TestCase):
    def test_frame_only_rejects_changes_to_baseline_member_settings(self):
        for option in (dict(damping_budget=3.),dict(step_limit=3.6),dict(shared_edge_fit=True),dict(coupled_frequency=500.)):
            with self.assertRaisesRegex(ValueError,'preserve baseline'):
                build(Path('unused'),Path('unused-output'),500,frame_only=True,**option)

    def test_frame_only_preserves_all_member_and_actuator_coefficients(self):
        part,manifest=self.fixture()
        manifest['chassis_nodes']=list('abd');manifest['frame_reference']=dict(mode='rigid_reference',requested_frequency_hz=200.)
        for a,b in [('a','d'),('b','d')]:part['beams'].append([a,b,dict(beamSpring=1000.,beamDamp=1.)])
        for row in part['beams'][1:]:
            if set(row[:2])<=set('abd'):row[-1].update(beamDeform=1e30,beamStrength=1e30)
        before=copy.deepcopy(part)
        reports,budget=condition(part,manifest,500,frame_frequency=300,frame_only=True)
        self.assertEqual(set(reports),{'_frame_reference'})
        self.assertEqual(part['nodes'],before['nodes']);self.assertEqual(part['hydros'],before['hydros'])
        for original,revised in zip(before['beams'][1:],part['beams'][1:]):
            if not set(original[:2])<=set('abd'):self.assertEqual(original,revised)
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)
        with self.assertRaisesRegex(ValueError,'explicit frame'):
            condition(part,manifest,500,frame_only=True)

    def test_owned_arm_fit_preserves_chassis_edge_and_spring(self):
        part,manifest=self.fixture();before=copy.deepcopy(part)
        manifest['template_definition']['parameters']['wishbone_shared_edge_fit']=True
        reports,budget=condition(part,manifest,500)
        self.assertEqual(reports['arm']['owned_constraint_fit']['rank'],2)
        self.assertEqual(reports['arm']['owned_constraint_fit']['nullity'],7)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['beams'][1],before['beams'][1])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertEqual(part['hydros'],before['hydros'])
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)

    def test_angular_lbeam_cannot_receive_an_axial_stability_certificate(self):
        from frame_harness.build import node_table
        from rigid_bracing import budget_connections
        part,_=self.fixture()
        part['beams'][2][-1].update(beamType='|LBEAM',**{'id3:':'b'})
        with self.assertRaisesRegex(ValueError,'angular force tangent'):
            budget_connections(part,node_table(part),[])

    def fixture(self):
        part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*p,dict(nodeWeight=3)] for n,p in zip('abcd',[(0,0,0),(1,0,0),(0,1,0),(0,0,1)])],
            beams=[['id1:','id2:'],['a','b',dict(beamSpring=1000,beamDamp=1)],
                   ['a','c',dict(beamSpring=1000,beamDamp=1)],['b','c',dict(beamSpring=1000,beamDamp=1)],
                   ['c','d',dict(beamType='|BOUNDED',beamSpring=1000,beamDamp=5)]],
            hydros=[['id1:','id2:'],['c','d',dict(beamSpring=500,beamDamp=1)]],
            cadConstraintGroups={'shock':{'beams':[['c','d']]}})
        manifest=dict(component_roles={'arm':'fl_upper_wishbone','frame':'frame'},
            mass_allocations={'arm':dict.fromkeys('abc',1.),'frame':dict.fromkeys('abd',2.)},
            template_definition={'parameters':{}},numerical_mass={'nodes':{}})
        return part,manifest

    def test_frequency_revision_preserves_shared_edge_spring_mass_and_geometry(self):
        part,manifest=self.fixture();before=copy.deepcopy(part)
        reports,budget=condition(part,manifest,500)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['hydros'],before['hydros'])
        self.assertEqual(part['cadConstraintGroups'],before['cadConstraintGroups'])
        self.assertEqual(part['beams'][1],before['beams'][1])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertEqual([r[:2] for r in part['beams']],[r[:2] for r in before['beams']])
        self.assertGreater(part['beams'][2][-1]['beamSpring'],before['beams'][2][-1]['beamSpring'])
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)
        self.assertEqual(reports['arm']['requested_frequency_hz'],500)

    def test_invalid_frequency_and_spring_overlap_rejected(self):
        for frequency in (99,601,float('nan')):
            part,manifest=self.fixture()
            with self.assertRaises(ValueError):condition(part,manifest,frequency)
        part,manifest=self.fixture();part['cadConstraintGroups']['bad']={'beams':[['a','c']]}
        with self.assertRaisesRegex(ValueError,'overlaps'):condition(part,manifest,500)
        part,manifest=self.fixture();manifest['template_definition']['parameters']['coupled_front_frequency_hz']=500
        with self.assertRaisesRegex(ValueError,'explicit frame'):condition(part,manifest,500)

    def test_internal_damping_option_preserves_coilover_and_assembled_limit(self):
        part,manifest=self.fixture();before=copy.deepcopy(part)
        manifest['template_definition']['parameters']['wishbone_damping_budget']=3.2
        reports,budget=condition(part,manifest,500)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['hydros'],before['hydros'])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertEqual(part['beams'][1],before['beams'][1])
        self.assertGreater(part['beams'][2][-1]['beamDamp'],0)
        self.assertEqual(reports['arm']['requested_internal_step_budget'],3.2)
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)
        for invalid in (1.9,3.3,float('nan')):
            part,manifest=self.fixture();manifest['template_definition']['parameters']['wishbone_damping_budget']=invalid
            with self.assertRaisesRegex(ValueError,'budget'):condition(part,manifest,500)

    def test_experimental_step_limit_is_bounded_and_preserves_physical_inputs(self):
        part,manifest=self.fixture();before=copy.deepcopy(part)
        manifest['template_definition']['parameters']['numerical_step_limit']=3.6
        _,budget=condition(part,manifest,600)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['hydros'],before['hydros'])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertEqual(budget['step_limit'],3.6)
        self.assertLessEqual(budget['final_step_eigenvalue'],3.6)
        for invalid in (1.9,3.61,float('nan')):
            part,manifest=self.fixture();manifest['template_definition']['parameters']['numerical_step_limit']=invalid
            with self.assertRaisesRegex(ValueError,'step limit'):condition(part,manifest,500)

    def test_upper_only_conditioning_keeps_lower_member_coefficients(self):
        part,manifest=self.fixture()
        part['nodes'] += [[n,*p,dict(nodeWeight=3)] for n,p in zip('efg',[(0,0,2),(1,0,2),(0,1,2)])]
        lower=[['e','f',dict(beamSpring=2000,beamDamp=2)],['e','g',dict(beamSpring=2000,beamDamp=2)],['f','g',dict(beamSpring=2000,beamDamp=2)]]
        part['beams']+=copy.deepcopy(lower)
        manifest['component_roles']['lower']='fl_lower_wishbone';manifest['mass_allocations']['lower']=dict.fromkeys('efg',3.)
        reports,budget=condition(part,manifest,500,'upper')
        self.assertEqual(set(reports),{'arm'})
        self.assertEqual(part['beams'][-3:],lower)
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)

    def test_pivot_refit_requires_numerical_frame_and_preserves_spring_defaults(self):
        part,manifest=self.fixture()
        with self.assertRaisesRegex(ValueError,'numerical rigid frame'):condition(part,manifest,500,frame_priority=4)
        manifest['chassis_nodes']=list('abd');manifest['frame_reference']=dict(mode='rigid_reference',requested_frequency_hz=300.)
        for a,b in [('a','d'),('b','d')]:part['beams'].append([a,b,dict(beamSpring=1000.,beamDamp=1.)])
        for row in part['beams'][1:]:
            if isinstance(row,list) and set(row[:2])<=set('abd'):row[-1].update(beamDeform=1e30,beamStrength=1e30)
        part['beams'].append(dict(beamSpring=20000.,beamDamp=3.))
        before=copy.deepcopy(part)
        reports,budget=condition(part,manifest,500,frame_priority=4)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['hydros'],before['hydros'])
        self.assertEqual(part['beams'][4],before['beams'][4])
        self.assertEqual(reports['_frame_reference']['pivot_priority'],4)
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)

    def test_joint_frame_frequency_is_budgeted_without_changing_physical_inputs(self):
        part,manifest=self.fixture()
        manifest['chassis_nodes']=list('abd');manifest['frame_reference']=dict(mode='rigid_reference',requested_frequency_hz=300.)
        for a,b in [('a','d'),('b','d')]:part['beams'].append([a,b,dict(beamSpring=1000.,beamDamp=1.)])
        for row in part['beams'][1:]:
            if set(row[:2])<=set('abd'):row[-1].update(beamDeform=1e30,beamStrength=1e30)
        before=copy.deepcopy(part)
        reports,budget=condition(part,manifest,600,frame_frequency=600)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['hydros'],before['hydros'])
        self.assertEqual(part['beams'][4],before['beams'][4])
        self.assertEqual(reports['_frame_reference']['requested_frequency_hz'],600)
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)

    def test_front_load_path_keeps_actuator_geometry_and_coilover_law(self):
        part,manifest=self.fixture()
        points={'e':(0,1,1),'f':(1,1,0),'g':(0,-1,0),'h':(0,-1,1),'i':(1,-1,0)}
        part['nodes'] += [[n,*p,dict(nodeWeight=3.)] for n,p in points.items()]
        for owner,role,names in [('upL','fl_upright','cef'),('upR','fr_upright','ghi')]:
            manifest['component_roles'][owner]=role;manifest['mass_allocations'][owner]=dict.fromkeys(names,1.)
            part['beams'] += [[a,b,dict(beamSpring=1000.,beamDamp=1.)] for a,b in itertools.combinations(names,2)]
        manifest['wheels']={c:dict(hardpoint_nodes=dict(tie_inner='a',tie_outer=n)) for c,n in [('FL','e'),('FR','h')]}
        for n in ('e','h'):
            part['hydros'].append(['a',n,dict(inputSource='steering_input',factor=.04,inRate=2.,outRate=2.,beamPrecompression=.99,beamSpring=1000.,beamDamp=50.,beamStrength=10000.)])
        before=copy.deepcopy(part)
        reports,budget=condition(part,manifest,500,front_load_path_frequency=500)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['beams'][4],before['beams'][4])
        self.assertEqual(part['hydros'][1],before['hydros'][1])
        for old,new in zip(before['hydros'][2:],part['hydros'][2:]):
            self.assertEqual(old[:2],new[:2])
            self.assertEqual({k:v for k,v in old[-1].items() if k not in ('beamSpring','beamDamp')},
                             {k:v for k,v in new[-1].items() if k not in ('beamSpring','beamDamp')})
            self.assertGreater(new[-1]['beamSpring'],old[-1]['beamSpring'])
        self.assertEqual(len(reports['_steering_links']),2)
        self.assertLessEqual(budget['final_step_eigenvalue'],3.2)
        part['hydros'][-1][-1]['inputSource']='throttle'
        with self.assertRaisesRegex(ValueError,'equivalent steering hydro'):
            condition(part,manifest,500,front_load_path_frequency=500)


if __name__=='__main__':unittest.main()
