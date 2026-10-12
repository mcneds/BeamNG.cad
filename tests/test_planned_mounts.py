import sys
from pathlib import Path
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from planned_mounts import insert_mounts,reference_fixtures,reference_response_pairs,complete_mirror_graph


class MountSupportTests(unittest.TestCase):
    def test_symmetric_hull_closes_helper_edges_before_properties_are_fitted(self):
        part={'nodes':[['id','posX','posY','posZ'],['l',-1.,0.,0.,{'nodeWeight':1.}],
                       ['r',1.,0.,0.,{'nodeWeight':1.}],['helper',-1.,0.,1.,{'nodeWeight':.1}]],
              'beams':[['id1:','id2:'],['l','helper',{'beamSpring':123.,'beamStrength':456.}]]}
        report=complete_mirror_graph(part,0,create_nodes=True)
        self.assertEqual(report['added_nodes'],1);self.assertEqual(report['added_beams'],1)
        self.assertEqual(part['beams'][-1],['r','helper_mirror',{'beamSpring':123.,'beamStrength':456.}])
        self.assertEqual(complete_mirror_graph(part,0,create_nodes=True)['added_nodes'],0)
        part['nodes'].append(['unpaired_mount',.4,.2,.3,{'nodeWeight':.1}])
        part['beams'].append(['l','unpaired_mount',{'beamSpring':7.}])
        count=len(part['nodes']);report=complete_mirror_graph(part,0)
        self.assertEqual(len(part['nodes']),count);self.assertEqual(report['added_beams'],0)

    def test_support_selection_and_short_links_are_reflection_invariant(self):
        points=[list(axis*sign) for axis in np.eye(3) for sign in (-1,1)]
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        patches=insert_mounts(part,{'left':[-.2,.1,.3],'right':[.2,.1,.3],'middle':[0,.2,.3]})
        nodes={r[0]:np.array(r[1:4]) for r in part['nodes'][1:]}
        for first,second in [('left','right'),('middle','middle')]:
            for key in ('parents','frame_supports'):
                actual=sorted(tuple(np.round(nodes[n]*[-1,1,1],12)) for n in patches[first][key])
                expected=sorted(tuple(np.round(nodes[n],12)) for n in patches[second][key])
                self.assertEqual(actual,expected)

    def test_offset_fixed_mount_reference_preserves_force_and_moment(self):
        points=[list(axis*sign) for axis in np.eye(3) for sign in (-1,1)]
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        point=np.array([.15,.2,.3]);other=point+[.03,0,0]
        patches=insert_mounts(part,{'body_a':dict(position=point.tolist(),mode='direct'),
                                  'body_b':dict(position=other.tolist(),mode='direct')})
        # Several physical mounts can use exactly the same supporting nodes.
        patches['body_b']['frame_supports']=patches['body_a']['frame_supports'].copy()
        fixtures=reference_fixtures(part,[])
        self.assertEqual(len(fixtures),6)
        for name,position in [('body_a',point),('body_b',other)]:
            for i,direction in enumerate(np.eye(3)):
                loads=fixtures['mount_support_'+name+'_'+str(i)]['load_vectors']
                resultant=np.sum(list(loads.values()),axis=0)
                np.testing.assert_allclose(resultant/np.linalg.norm(resultant),direction,atol=1e-12)
                self.assertAlmostEqual(sum(np.linalg.norm(v) for v in loads.values()),1.)
                moment=sum(np.cross(points[int(node)],force) for node,force in loads.items())
                np.testing.assert_allclose(moment,np.cross(position,resultant),atol=1e-12)

    def test_fixed_bodies_use_loaded_pivots_before_light_collider_nodes(self):
        points=[list(axis*sign*.25) for axis in np.eye(3) for sign in (-1,1)]
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':.05}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        # The fixed-body name sorts before the pivot names, deliberately.
        plan={'A_body':dict(position=[0,0,0],mode='direct')}
        for i,p in enumerate([[.6,.6,.6],[.6,-.6,-.6],[-.6,.6,-.6],[-.6,-.6,.6]]):
            plan['loaded_'+str(i)]=dict(position=p,mode='joint')
        patches=insert_mounts(part,plan);body=patches['A_body']
        loaded={patch['parents'][0] for patch in patches.values() if patch['mode']=='joint'}
        self.assertEqual(set(body['frame_supports']),loaded)
        self.assertEqual(body['support_source'],'loaded_skeleton')
        self.assertGreater(body['minimum_direction_eigenvalue'],1.)

    def test_only_existing_corresponding_corner_loads_are_paired(self):
        fixtures={name:{} for name in ('flex','torsion','mount_FL_lower_0','mount_FR_lower_0',
            'mount_support_RL_shock_top_2','mount_support_RR_shock_top_2','mount_support_FL_missing_1','mount_engine_0')}
        self.assertEqual(reference_response_pairs(fixtures),[
            ['mount_FL_lower_0','mount_FR_lower_0'],['mount_support_RL_shock_top_2','mount_support_RR_shock_top_2']])

    def test_structural_pivots_have_real_frame_nodes_and_local_reference_couples(self):
        points=[list(axis*sign) for axis in np.eye(3) for sign in (-1,1)]
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        plan={name:dict(position=[x,.1,.2],mode='joint',reference_pair='rear_hinge') for name,x in [('inner',-.1),('outer',.1)]}
        patches=insert_mounts(part,plan);fixtures=reference_fixtures(part,['0','2','4'])
        self.assertEqual(len(fixtures),8);self.assertEqual(len(part['beams'])-1,13)
        self.assertIn(['mount_inner_0','mount_outer_0'],[r[:2] for r in part['beams'][1:]])
        nodes={r[0]:r[1:4] for r in part['nodes'][1:]}
        for name,patch in patches.items():self.assertEqual(nodes[patch['parents'][0]],plan[name]['position'])
        for name,fixture in fixtures.items():
            forces=np.array(list(fixture['load_vectors'].values()))
            if not name.startswith('mount_support_'):
                np.testing.assert_allclose(forces.sum(axis=0),0,atol=1e-15)
                np.testing.assert_allclose(forces[:,0],0,atol=1e-15)
            else:self.assertAlmostEqual(np.linalg.norm(forces.sum(axis=0)),1.)
            self.assertAlmostEqual(np.linalg.norm(forces,axis=1).sum(),1.)
            self.assertFalse(set(fixture['fixed_nodes'])&set(fixture['load_nodes']))

    def test_direct_mount_has_no_unused_mass_or_springs_and_mode_is_sealed(self):
        from calibration_worker import validate_fixed_mounts
        points=[list(axis*sign) for axis in np.eye(3) for sign in (-1,1)]
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        plan={'hinge':dict(position=[0,0,0],mode='direct')}
        patch=insert_mounts(part,plan)['hinge']
        self.assertEqual(patch['parents'],[]);self.assertGreaterEqual(len(patch['frame_supports']),4)
        self.assertEqual(len(part['nodes']),7);self.assertEqual(len(part['beams']),1)
        validate_fixed_mounts(part,plan)
        with self.assertRaisesRegex(ValueError,'Mount representation changed'):
            validate_fixed_mounts(part,{'hinge':[0,0,0]})

    def test_loaded_pivots_connect_to_existing_interior_frame_supports(self):
        points=[list(axis*sign) for axis in np.eye(3) for sign in (-1,1)]
        # The interior point is deliberately outside the nearest support set.
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        part['nodes'].append(['internal',10,0,0,dict(nodeWeight=2,collision=False)])
        insert_mounts(part,{'pivot':dict(position=[.1,.2,.3],mode='joint')})
        self.assertIn(['mount_pivot_0','internal'],[r[:2] for r in part['beams'][1:]])

    def test_release_parent_loads_reach_the_loaded_frame_skeleton(self):
        points=[list(axis*sign) for axis in np.eye(3) for sign in (-1,1)]
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        patches=insert_mounts(part,{'pivot':dict(position=[.1,.2,.3],mode='joint'),'panel':[.2,.2,.2]})
        edges={frozenset(r[:2]) for r in part['beams'][1:]}
        for parent in patches['panel']['parents']:
            self.assertIn(frozenset([parent,patches['pivot']['parents'][0]]),edges)
        fixtures=reference_fixtures(part,['0','2','4'])
        for axis in range(3):self.assertEqual(set(fixtures['mount_support_panel_'+str(axis)]['load_nodes']),set(patches['panel']['parents']))

    def test_nearly_parallel_nearest_members_do_not_become_a_floppy_mount(self):
        points=[[1,0,0],[1,.001,0],[1,0,.001],[1,.001,.001]]
        points += [list(axis*sign*1.2) for axis in np.eye(3) for sign in (-1,1)]
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':1}] for i,p in enumerate(points)],'beams':[['id1:','id2:']]}
        patch=insert_mounts(part,{'loaded_joint':[0,0,0]})['loaded_joint']
        supports=np.array([points[int(n)] for n in patch['frame_supports']]);unit=supports/np.linalg.norm(supports,axis=1)[:,None]
        stiffness=150000*unit.T@unit
        # 100 N from any direction stays under 1 mm with the surrounding
        # structure held fixed. Rank-only selection misses this by orders of magnitude.
        self.assertLess(np.linalg.eigvalsh(np.linalg.inv(stiffness))[-1]*100,.001)


if __name__=='__main__':unittest.main()
