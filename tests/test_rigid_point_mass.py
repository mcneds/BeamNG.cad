import copy,itertools,sys,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from rigid_point_mass import distribute


class MinimalMemberTests(unittest.TestCase):
    def test_optional_sparse_uprights_keep_wheel_and_joint_sites(self):
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        def configure(spec,components,moments):
            spec['parameters'].update(upright_representation='hardpoint_lumped',assembled_rigid_conditioning=True,
                                      loaded_node_mass_policy='reported_ballast')
        project,frame,spec,cad=fixture('ball_radius_toe',configure)
        with patch('components.read_geometry',side_effect=cad):graph,part,wheels,*_=generate(project,frame,spec)
        for corner,wheel in wheels.items():
            owner=corner.lower()+'_upright';names=set(graph.groups[owner])
            self.assertFalse(any('_mass_' in n for n in names))
            self.assertEqual(graph.reports[owner]['auxiliary_node_count'],0)
            self.assertIn(wheel['brake_reaction_node'],names)
            self.assertNotIn(wheel['brake_reaction_node'],wheel['tire_contract']['axle_nodes'])
            self.assertTrue(set(wheel['tire_contract']['axle_nodes'])<=names)
            for point in ('upper_ball','lower_ball','tie_outer') if corner[0]=='F' else ('carrier_axis_a','carrier_axis_b','tie_outer'):
                self.assertIn(wheel['hardpoint_nodes'][point],names)
            self.assertAlmostEqual(sum(graph.mass_allocations[owner].values()),
                graph.reports[owner]['target_mass_kg']+graph.reports[owner].get('numerical_added_mass_kg',0))
            self.assertFalse(graph.reports[owner]['moments_qualified'])
        self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.2+1e-6)

    def test_exact_feasible_moments_and_reflection(self):
        xyz=np.array([[0.,0,0],[1,0,0],[0,1,0]])
        weights=np.array([1.,2.,3.]);mass=weights.sum();center=weights@xyz/mass
        inertia=sum(w*(p@p*np.eye(3)-np.outer(p,p)) for w,p in zip(weights,xyz-center))
        for R in (np.eye(3),np.diag([-1.,1,1])):
            _,actual,report=distribute((mass,R@center,R@inertia@R.T),xyz@R.T)
            np.testing.assert_allclose(actual,weights,atol=1e-5)
            self.assertAlmostEqual(actual.sum(),mass)
            self.assertFalse(report['moments_qualified'])
            self.assertLess(report['inertia_relative_error'],1e-6)

    def test_degenerate_points_rejected(self):
        with self.assertRaisesRegex(ValueError,'noncollinear'):
            distribute((3.,np.zeros(3),np.eye(3)),[[0,0,0],[1,0,0],[2,0,0]])

    def test_triangle_reuses_chassis_edge_with_only_two_new_arm_beams(self):
        from vehicle_templates import Structure
        from rigid_revision import refit
        frame=dict(nodes=[['id','posX','posY','posZ'],
                          ['a',0,0,0,dict(nodeWeight=2,group=['frame'])],
                          ['b',1,0,0,dict(nodeWeight=2,group=['frame'])]],
                   beams=[['id1:','id2:'],['a','b',dict(beamSpring=1000,beamDamp=10)]])
        original=copy.deepcopy(frame['beams'][1])
        graph=Structure(frame)
        with patch('components.read_geometry',return_value=([],(3.,np.array([.3,.3,0]),np.eye(3)*.1),{})):
            graph.rigid_component(dict(Id='arm',MvpRole='fl_upper_wishbone'),
                                  dict(a=[0,0,0],b=[1,0,0],ball=[0,1,0]),shared=('a','b'))
        self.assertEqual(set(graph.groups['arm']),{'a','b','ball'})
        self.assertEqual(len(graph.new_beams),2)
        self.assertEqual(len(graph.part['torsionbars']),1)
        graph.part['beams'].extend(graph.new_beams)
        refit(graph.part,graph.mass_allocations,'arm')
        self.assertEqual(graph.part['beams'][1],original)
        self.assertEqual(graph.reports['arm']['reused_chassis_edges'],[['a','b']])

    def test_generated_wishbones_use_only_their_mechanical_hardpoints(self):
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        def configure(spec,components,moments):
            spec['parameters'].pop('wishbone_representation')
            spec['parameters'].pop('trailing_arm_representation')
            spec['parameters'].update(assembled_rigid_conditioning=True,
                                      loaded_node_mass_policy='reported_ballast')
        project,frame,spec,cad=fixture('primary',configure)
        with patch('components.read_geometry',side_effect=cad):graph,part,wheels,*_=generate(project,frame,spec)
        for corner in ('FL','FR'):
            for arm,count in [('upper',3),('lower',4)]:
                owner=corner.lower()+'_'+arm+'_wishbone';names=graph.groups[owner]
                self.assertEqual(len(names),count)
                self.assertFalse(any('_mass_' in n for n in names))
                self.assertTrue(all(graph.nodes[n]['options']['nodeWeight']>=2-1e-9 for n in names))
                self.assertEqual(graph.reports[owner]['allocation_method'],'hardpoint_lumped')
                self.assertFalse(graph.reports[owner]['moments_qualified'])
                internal=[r for r in part['beams'][1:] if isinstance(r,list) and set(r[:2])<=set(names)]
                self.assertEqual(len({frozenset(r[:2]) for r in internal}),count*(count-1)//2)
                self.assertEqual(len(internal),count*(count-1)//2)
                self.assertTrue(all(r[-1].get('beamType','|NORMAL')=='|NORMAL' for r in internal))
                self.assertAlmostEqual(sum(graph.mass_allocations[owner].values()),
                    graph.reports[owner]['target_mass_kg']+graph.reports[owner].get('numerical_added_mass_kg',0))
        for owner in ('rl_trailing_arm','rr_trailing_arm'):
            self.assertEqual(graph.reports[owner]['allocation_method'],'hardpoint_lumped')
            self.assertFalse(any('_mass_' in n for n in graph.groups[owner]))
        for corner,wheel in wheels.items():
            self.assertTrue(np.isfinite(wheel['effective_unsprung_mass_kg']))
            self.assertGreater(wheel['effective_unsprung_mass_kg'],0)
        self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.2+1e-6)

    def test_ball_joint_trailing_arms_keep_all_six_attachment_sites(self):
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        def configure(spec,components,moments):
            spec['parameters'].pop('wishbone_representation')
            spec['parameters'].pop('trailing_arm_representation')
            spec['parameters'].update(assembled_rigid_conditioning=True,loaded_node_mass_policy='reported_ballast')
        project,frame,spec,cad=fixture('ball_radius_toe',configure)
        with patch('components.read_geometry',side_effect=cad):graph,part,wheels,*_=generate(project,frame,spec)
        for corner in ('RL','RR'):
            owner=corner.lower()+'_trailing_arm'
            sites=('trailing_ball','shock_bottom','carrier_axis_a','carrier_axis_b','radius_upper_outer','radius_lower_outer')
            expected={wheels[corner]['hardpoint_nodes'][key] for key in sites}
            self.assertEqual(set(graph.groups[owner]),expected)
            self.assertEqual(graph.reports[owner]['auxiliary_node_count'],0)
            self.assertAlmostEqual(sum(graph.mass_allocations[owner].values()),
                graph.reports[owner]['target_mass_kg']+graph.reports[owner].get('numerical_added_mass_kg',0))
        self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.2+1e-6)

    def test_rigidifiers_are_reported_mass_and_remain_inside_one_member(self):
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        def configure(spec,components,moments):
            spec['parameters'].update(wishbone_representation='rigidifier',assembled_rigid_conditioning=True,
                                      loaded_node_mass_policy='reported_ballast')
        project,frame,spec,cad=fixture('primary',configure)
        with patch('components.read_geometry',side_effect=cad):graph,part,*_=generate(project,frame,spec)
        self.assertEqual(len(graph.rigidifier_nodes),8)
        for node in graph.rigidifier_nodes:
            owners=[owner for owner,values in graph.mass_allocations.items() if node in values]
            self.assertEqual(len(owners),1);own=set(graph.groups[owners[0]])
            self.assertGreaterEqual(graph.nodes[node]['options']['nodeWeight'],2-1e-9)
            self.assertFalse(graph.nodes[node]['options']['collision'])
            self.assertFalse(graph.nodes[node]['options']['selfCollision'])
            for row in part['beams'][1:]:
                if isinstance(row,list) and node in row[:2]:self.assertTrue(set(row[:2])<=own)
            for row in part['torsionbars'][1:]:
                if node in row[:4]:self.assertTrue(set(row[:4])<=own)
            self.assertTrue(graph.reports[owners[0]]['accepted'])
        self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.2+1e-6)


if __name__=='__main__':unittest.main()
