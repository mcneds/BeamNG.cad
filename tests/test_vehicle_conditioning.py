import copy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from vehicle_conditioning import allocate_support_mass


class SupportMassTests(unittest.TestCase):
    def test_loaded_spherical_joint_floors_receiving_nodes_not_unrelated_accessories(self):
        g,corners=self.fixture()
        for n in ('support_a','support_b','support_c','shaft_inner','shaft_outer','accessory'):
            g.nodes[n]=dict(position=[0,1,0],options=dict(nodeWeight=.02))
            g.mass_allocations.setdefault('shaft_support',{})[n]=.02
        g.joints=[dict(id='outer',kind='spherical',nodes=['support_a','support_b','support_c','shaft_outer']),
                  dict(id='shaft',kind='telescopic',nodes=['shaft_inner','shaft_outer']),
                  dict(id='unrelated',kind='spherical',nodes=['support_a','support_b','support_c','accessory'])]
        before=copy.deepcopy(g.nodes);joints=copy.deepcopy(g.joints)
        result=allocate_support_mass(g,corners,[],{})
        for n in ('support_a','support_b','support_c','shaft_inner','shaft_outer'):
            self.assertEqual(g.nodes[n]['options']['nodeWeight'],2.)
            self.assertEqual(g.nodes[n]['position'],before[n]['position'])
        self.assertEqual(g.nodes['accessory'],before['accessory'])
        self.assertEqual(g.joints,joints)
        self.assertIn('loaded spherical support: outer',result['nodes']['support_a']['reasons'])
        self.assertAlmostEqual(result['added_mass_kg'],1.7+5*1.98)

    def test_slender_wishbone_conditioning_is_scale_and_reflection_invariant(self):
        from vehicle_conditioning import wishbone_support_targets
        for scale in (1.,10.):
            nodes={};corners={}
            for corner,sign in (('FL',1),('FR',-1)):
                points={'upper_inner_front':[0,-.05,0],'upper_inner_rear':[0,.05,0],'upper_ball':[sign*.29,0,0]}
                names={k:corner+'_'+k for k in points}
                nodes.update({names[k]:dict(position=[scale*v for v in p]) for k,p in points.items()})
                corners[corner]=dict(hardpoint_nodes=names)
            targets,report=wishbone_support_targets(SimpleNamespace(nodes=nodes),corners,2.)
            self.assertEqual(set(targets.values()),{6.});self.assertEqual(len(report),2)
            self.assertTrue(all(abs(r['reach_to_pivot_span']-2.9)<1e-10 for r in report))

    def test_frame_locator_fit_changes_only_existing_chassis_constraints(self):
        from vehicle_conditioning import condition_frame_locators
        nodes={str(i):dict(position=p,options={'nodeWeight':2.}) for i,p in enumerate(
            ([0,0,0],[1,0,0],[0,1,0],[0,0,1],[-1,-1,-1]))}
        rows=[['id1:','id2:']]+[['0',str(i),dict(beamSpring=100.,beamDamp=1.,beamDeform=10,beamStrength=20)] for i in range(1,5)]
        rows.append(['1','2',dict(beamSpring=200.,beamDamp=2.,beamDeform=30,beamStrength=40)])
        part=dict(beams=rows,cadMountPatches={'pivot':dict(mode='joint',parents=['0'],frame_supports=['1','2','3','4'])})
        before=copy.deepcopy(part)
        selected,report=condition_frame_locators(part,nodes,list(nodes))
        self.assertEqual(len(selected),4);self.assertFalse(report['material_response_qualified'])
        self.assertEqual([r[:2] for r in part['beams']],[r[:2] for r in before['beams']])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertTrue(all(o['beamStrength']==1e30 for o in selected))

    def fixture(self):
        g=SimpleNamespace(nodes={n:dict(position=[i,0,0],options=dict(nodeWeight=m))
                               for i,(n,m) in enumerate([('ball',.5),('axis_a',2.5),('axis_b',1.8)])},
                          mass_allocations={'arm':{'ball':.2},'upright':{'ball':.3,'axis_a':2.5,'axis_b':1.8}},reports={},joints=[])
        corners={'RL':dict(hardpoint_nodes={'ball':'ball'},nodes=dict(axis_in='axis_a',axis_out='axis_b'),reaction_nodes={'nodeArm':'ball'})}
        return g,corners

    def test_final_shared_mass_is_counted_once_and_ballast_is_owned(self):
        g,corners=self.fixture();old=copy.deepcopy(g.nodes)
        result=allocate_support_mass(g,corners,[],{'loaded_node_mass_policy':'reported_ballast'})
        self.assertAlmostEqual(result['added_mass_kg'],1.7)
        self.assertAlmostEqual(g.mass_allocations['arm']['ball'],.8)
        self.assertAlmostEqual(g.mass_allocations['upright']['ball'],1.2)
        for n,node in g.nodes.items():
            self.assertEqual(node['position'],old[n]['position'])
            self.assertGreaterEqual(node['options']['nodeWeight'],2)
            self.assertAlmostEqual(node['options']['nodeWeight'],sum(v.get(n,0) for v in g.mass_allocations.values()))
        self.assertFalse(result['material_mass_equivalent'])

    def test_preserve_policy_reports_low_masses_without_changing_them(self):
        g,corners=self.fixture();before=copy.deepcopy(g.nodes)
        result=allocate_support_mass(g,corners,[],{'loaded_node_mass_policy':'preserve_cad'})
        self.assertEqual(g.nodes,before);self.assertEqual(result['added_mass_kg'],0)
        self.assertEqual(result['nodes']['ball']['simulated_mass_kg'],.5)
        self.assertEqual(result['below_target_nodes'],['axis_b','ball'])

    def test_axle_target_is_honored_without_raising_unrelated_nodes(self):
        g,corners=self.fixture()
        allocate_support_mass(g,corners,[],{'minimum_wheel_support_node_kg':3.,'loaded_node_mass_policy':'reported_ballast'})
        self.assertEqual(g.nodes['axis_a']['options']['nodeWeight'],3.)
        self.assertEqual(g.nodes['axis_b']['options']['nodeWeight'],3.)
        self.assertEqual(g.nodes['ball']['options']['nodeWeight'],2.)

    def test_unowned_mass_is_rejected(self):
        g,corners=self.fixture();g.nodes['ball']['options']['nodeWeight']=.6
        with self.assertRaisesRegex(ValueError,'ownership'):allocate_support_mass(g,corners,[],{})

    def test_role_target_changes_shared_mass_once_and_retains_other_floors(self):
        g,corners=self.fixture()
        report=allocate_support_mass(g,corners,[],{'loaded_hardpoint_mass_targets_kg':{'ball':6.},'loaded_node_mass_policy':'reported_ballast'})
        self.assertEqual(g.nodes['ball']['options']['nodeWeight'],6.)
        self.assertAlmostEqual(g.mass_allocations['arm']['ball'],2.4)
        self.assertAlmostEqual(g.mass_allocations['upright']['ball'],3.6)
        self.assertEqual(g.nodes['axis_a']['options']['nodeWeight'],2.5)
        self.assertAlmostEqual(report['added_mass_kg'],5.7)
        for targets in ({'typo':6.},{'ball':1.},{'ball':float('nan')}):
            g,corners=self.fixture()
            with self.assertRaises(ValueError):allocate_support_mass(g,corners,[],{'loaded_hardpoint_mass_targets_kg':targets})


class ConditionedGenerationTests(unittest.TestCase):
    def test_preserve_cad_keeps_rotating_wheel_mass_and_reports_support_shortfalls(self):
        from unittest.mock import patch
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        project,frame,spec,cad=fixture('primary')
        spec['parameters']['loaded_node_mass_policy']='preserve_cad'
        with patch('components.read_geometry',side_effect=cad):
            graph,part,wheels,*_=generate(project,frame,spec)
        self.assertEqual(graph.numerical_mass['added_mass_kg'],0.)
        self.assertTrue(graph.numerical_mass['below_target_nodes'])
        for wheel in wheels.values():
            self.assertEqual(wheel['mass_allocation']['support_mass_source'],'cad_carrier_mass_only')
            self.assertEqual(wheel['mass_allocation']['added_per_axle_node_kg'],0.)
            self.assertAlmostEqual(wheel['wheel_mass_kg'],wheel['cad_wheel_mass_kg'])

    def test_fresh_graph_accounts_for_added_mass_and_preserves_moving_boundaries(self):
        from unittest.mock import patch
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        from frame_harness.build import node_table
        project,frame,spec,cad=fixture('primary')
        spec['parameters'].update(loaded_node_mass_policy='reported_ballast',assembled_rigid_conditioning=True)
        with patch('components.read_geometry',side_effect=cad):
            graph,part,wheels,*_=generate(project,frame,spec)
        self.assertGreater(graph.numerical_mass['added_mass_kg'],0)
        for corner,wheel in wheels.items():
            self.assertEqual(wheel['mass_allocation']['support_mass_source'],'separate_reported_ballast')
            self.assertEqual(wheel['mass_allocation']['added_per_axle_node_kg'],0.)
            self.assertAlmostEqual(wheel['wheel_mass_kg'],wheel['cad_wheel_mass_kg'])
        nodes=node_table(part)
        for n in graph.numerical_mass['nodes']:self.assertGreaterEqual(nodes[n]['options']['nodeWeight'],2-1e-9)
        self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.2)
        self.assertTrue(graph.fixed_attachment_contract)
        self.assertTrue(all('wishbone' not in owner and 'trailing' not in owner for owner in graph.fixed_attachment_contract))
        for owner,report in graph.rigid_refits.items():
            self.assertEqual(set(report['nodes']),set(graph.mass_allocations[owner]))
        mass=sum(n['options']['nodeWeight'] for n in nodes.values())+sum(v['wheel_mass_kg'] for v in wheels.values())
        # The analytic fixture's seed frame mass is intentionally not CAD mass.
        expected=sum(cad(v)[1][0] for v in project['Components'] if v['Id']!='frame')+sum(n['options']['nodeWeight'] for n in node_table(frame).values())
        self.assertAlmostEqual(mass,expected+graph.numerical_mass['added_mass_kg'],places=6)
        self.assertAlmostEqual(sum(r[-1]['brakeTorque']/r[-1]['radius'] for r in part['pressureWheels'][1:]),mass*9.81,places=6)


if __name__=='__main__':unittest.main()
