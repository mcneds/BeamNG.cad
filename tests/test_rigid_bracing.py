import itertools,sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from rigid_bracing import reinforce,gradient,point_constraint,budget_connections
from frame_harness.projection import axial_columns


class AngularBracingTests(unittest.TestCase):
    def test_emitted_angular_levers_retain_screened_geometry(self):
        # Lexicographic energy deduplication used to emit a different ordering
        # than the one screened, making nearly parallel lever/axis pairs.
        xyz=np.array([[.675,0,.29],[.825,0,.29],[.63,0,.47],[.67,0,.2],
                      [.66,.14,.36],[.65,0,.31],[.70,0,.35],[.73,0,.33]])
        for order in (np.arange(len(xyz)),np.random.default_rng(13).permutation(len(xyz))):
            points=xyz[order]
            _,_,bars=reinforce(points,list(itertools.combinations(range(len(points)),2)),np.ones(len(points)))
            self.assertTrue(bars)
            for ids,_,_ in bars:
                a,b,c,d=points[ids];axis=c-b
                for lever in (a-b,d-c):
                    arm=np.linalg.norm(np.cross(lever,axis))/np.linalg.norm(axis)
                    self.assertGreaterEqual(arm/np.linalg.norm(lever),.4-1e-8)
                    self.assertGreaterEqual(arm,np.linalg.norm(np.ptp(points,axis=0))*.04-1e-8)

    def test_declared_actuator_halves_keep_one_scale_and_reject_stale_groups(self):
        nodes={str(i):dict(position=[float(i%2),float(i//2),0.],options=dict(nodeWeight=1. if i<2 else 2.)) for i in range(4)}
        options=[dict(beamSpring=20e6,beamDamp=20.) for _ in range(2)]
        part=dict(hydros=[['id1:','id2:'],['0','1',options[0]],['2','3',options[1]]],cadConstraintGroups={'rack':{'hydros':[['0','1'],['2','3']]}})
        report=budget_connections(part,nodes,options)
        self.assertEqual(options[0],options[1])
        self.assertLessEqual(report['final_step_eigenvalue'],3.200001)
        part['cadConstraintGroups']['rack']['hydros'][1]=['2','missing']
        with self.assertRaisesRegex(ValueError,'identify one adjustable'):budget_connections(part,nodes,options)

    def test_small_excess_is_not_over_reduced_by_an_unrelated_large_excess(self):
        # Two independent two-mass modes have known exact stability budgets.
        # An accessory needing a large reduction must not halve a rack that
        # needs only a small reduction, even when both modes are excessive.
        for large in (35.,350.):
            nodes={str(i):dict(position=[float(i%2),float(i//2),0.],options=dict(nodeWeight=1.)) for i in range(4)}
            sealed=dict(beamSpring=.8/(2*.0005**2),beamDamp=0.)
            options=[dict(beamSpring=large/(2*.0005**2),beamDamp=0.),
                     dict(beamSpring=(3.3-.8)/(2*.0005**2),beamDamp=0.)]
            part=dict(beams=[['id1:','id2:'],['0','1',options[0]],['2','3',sealed],['2','3',options[1]]])
            report=budget_connections(part,nodes,options)
            self.assertLessEqual(report['final_step_eigenvalue'],3.200001)
            self.assertEqual(sealed['beamSpring'],.8/(2*.0005**2))
            self.assertGreater(.8+2*.0005**2*options[1]['beamSpring'],3.19)

    def test_connection_budget_is_invariant_for_repeated_mechanisms_and_node_order(self):
        # Independent identical chains have a repeated excessive eigenvalue.
        # Choosing one arbitrary eigenvector must not give each copy a different
        # stiffness, nor change the answer when CAD enumeration changes.
        def build(order):
            nodes={};part=dict(beams=[['id1:','id2:']]);connections=[]
            groups=len(order)//3
            for group in range(groups):
                for i in range(3):
                    nodes[f'{group}_{i}']=dict(position=[float(i),float(group)*2,0.],options=dict(nodeWeight=1.))
                part['beams'].append([f'{group}_0',f'{group}_1',dict(beamSpring=1e5,beamDamp=1.)])
                for a,b,k in ((0,1,20e6),(1,2,8e6)):
                    options=dict(beamSpring=k,beamDamp=100.)
                    part['beams'].append([f'{group}_{a}',f'{group}_{b}',options])
                    connections.append(options)
            names=list(nodes);nodes={names[i]:nodes[names[i]] for i in order}
            report=budget_connections(part,nodes,connections)
            values=np.array([[o['beamSpring'],o['beamDamp']] for o in connections]).reshape(groups,2,2)
            # Independently check the complete tangent of each three-mass chain.
            A=np.array([[-1.,0.],[1.,-1.],[0.,1.]])
            for group in values:
                coefficients=.0005**2*group[:,0]+.001*group[:,1]+[.026,0.]
                self.assertLessEqual(np.linalg.eigvalsh((A*coefficients)@A.T)[-1],3.200001)
            self.assertLessEqual(report['final_step_eigenvalue'],3.200001)
            return values
        for count in (24,72):
            base=build(range(count));permuted=build(np.random.default_rng(3).permutation(count))
            np.testing.assert_allclose(base,np.broadcast_to(base[0],base.shape),rtol=1e-6)
            np.testing.assert_allclose(permuted,base,rtol=1e-6)

    def test_noncollision_constraint_keeps_requested_stiffness_when_assembled_step_is_safe(self):
        from vehicle_templates import Structure
        frame=dict(nodes=[['id','posX','posY','posZ'],['a',0.,0.,0.,dict(nodeWeight=1.)],
                          ['b',1.,0.,0.,dict(nodeWeight=1.)]],beams=[['id1:','id2:']])
        for requested in (5e6,12e6):
            graph=Structure(frame);graph.beam('a','b',beamSpring=requested,beamDamp=40.)
            part=graph.finish();options=next(r[2] for r in part['beams'][1:] if isinstance(r,list))
            # Independently evaluate the two-mass axial mode, including damping.
            step=2*(.0005**2*options['beamSpring']+.001*options['beamDamp'])
            self.assertLessEqual(step,3.200001)
            if requested==5e6:self.assertEqual(options['beamSpring'],requested)
            else:self.assertLess(options['beamSpring'],requested)

    def test_connection_budget_handles_zero_fixed_block_and_leaves_safe_mechanism_alone(self):
        nodes={str(i):dict(position=[float(i),0.,0.],options=dict(nodeWeight=1.)) for i in range(18)}
        for requested in (0.,20e6):
            loaded=dict(beamSpring=requested,beamDamp=0.)
            safe=dict(beamSpring=1e5,beamDamp=1.)
            part=dict(beams=[['id1:','id2:'],['0','1',loaded],['16','17',safe]])
            budget_connections(part,nodes,[loaded,safe])
            self.assertEqual(safe,dict(beamSpring=1e5,beamDamp=1.))
            self.assertLessEqual(2*.0005**2*loaded['beamSpring'],3.200001)
        report=budget_connections(dict(beams=[['id1:','id2:']]),nodes,[])
        self.assertEqual(report['final_step_eigenvalue'],0.)

    def test_solid_axial_fit_has_six_rigid_modes_and_keeps_step_margin(self):
        xyz=np.array(list(itertools.product((-.1,.1),(-.06,.06),(-.03,.03))))
        edges=list(itertools.combinations(range(len(xyz)),2));mass=np.full(len(xyz),.2)
        spring,damp,bars=reinforce(xyz,edges,mass,angular=False)
        self.assertEqual(bars,[])
        A,_,_=axial_columns(xyz,edges);A/=np.repeat(np.sqrt(mass),3)[:,None]
        eigen=np.linalg.eigvalsh((A*spring)@A.T)
        self.assertEqual(sum(eigen<1e-4),6)
        self.assertGreater(eigen[6],100000.)
        self.assertLessEqual(np.linalg.eigvalsh((A*(.0005**2*spring+.001*damp))@A.T)[-1],2.000001)
        xyz=np.array([[0.,0,0],[.4,0,0],[.4,.3,0],[0,.3,0],[.15,.1,0]])
        edges=list(itertools.combinations(range(len(xyz)),2));mass=np.ones(len(xyz))
        with self.assertRaisesRegex(ValueError,'internal mechanism'):
            reinforce(xyz,edges,mass,angular=False)

    def test_filtered_normal_damping_cannot_claim_the_memoryless_tangent_bound(self):
        nodes={str(i):dict(position=[float(i),0.,0.],options=dict(nodeWeight=1.)) for i in range(2)}
        spring=dict(beamSpring=100000.,beamDamp=10.,dampCutoffHz=60)
        part=dict(beams=[['id1:','id2:'],['0','1',spring]])
        with self.assertRaisesRegex(ValueError,'unfiltered damping'):budget_connections(part,nodes,[])
        spring['dampCutoffHz']=0
        report=budget_connections(part,nodes,[])
        self.assertAlmostEqual(report['final_step_eigenvalue'],2*(.0005**2*100000.+.001*10.))

    def test_rigid_stiffness_and_damping_do_not_depend_on_node_order_or_reflection(self):
        box=np.array(list(itertools.product((-.1,.1),(-.06,.06),(-.03,.03))))
        upright=np.array([[.675,0,.29],[.825,0,.29],[.63,0,.47],[.67,0,.2],
                          [.66,.14,.36],[.65,0,.31],[.70,0,.35],[.73,0,.33]])
        bulk=np.vstack((box,np.eye(3)*.01,-np.eye(3)*.01))
        def matrices(xyz,masses):
            edges=list(itertools.combinations(range(len(xyz)),2))
            spring,damp,bars=reinforce(xyz,edges,masses)
            columns,_,_=axial_columns(xyz,edges);angular=[]
            for ids,_,_ in bars:
                value=np.zeros_like(xyz);value[ids]=gradient(xyz[ids]);angular.append(value.ravel())
            columns=np.column_stack((columns,*angular))
            return [(columns*values)@columns.T for values in
                    (np.r_[spring,[b[1] for b in bars]],np.r_[damp,[b[2] for b in bars]])]
        for xyz in (box,upright,bulk):
            with self.subTest(nodes=len(xyz)):
                masses=np.full(len(xyz),.3);base=matrices(xyz,masses)
                order=np.random.default_rng(13).permutation(len(xyz));restore=np.argsort((order[:,None]*3+np.arange(3)).ravel())
                permuted=[v[np.ix_(restore,restore)] for v in matrices(xyz[order],masses[order])]
                sign=np.tile([-1,1,1],len(xyz))
                reflected=[v*sign[:,None]*sign[None,:] for v in matrices(xyz*[-1,1,1],masses)]
                for original,changed,mirror in zip(base,permuted,reflected):
                    self.assertLess(np.linalg.norm(original-changed)/np.linalg.norm(original),1e-6)
                    self.assertLess(np.linalg.norm(original-mirror)/np.linalg.norm(original),1e-6)

    def test_connection_torque_restraint_shares_the_explicit_step_budget(self):
        xyz=np.array([[0.,1,0],[0,0,0],[1,0,0],[1,0,1]])
        nodes={str(i):dict(position=p.tolist(),options=dict(nodeWeight=1.)) for i,p in enumerate(xyz)}
        sealed=dict(beamSpring=100000.,beamDamp=10.)
        joint=dict(spring=1e8,damp=100.)
        part=dict(beams=[['id1:','id2:'],['0','1',sealed]],
                  torsionbars=[['id1:','id2:','id3:','id4:'],['0','1','2','3',joint]])
        report=budget_connections(part,nodes,[joint])
        self.assertLess(joint['spring'],1e8);self.assertGreater(joint['spring'],0)
        self.assertEqual(sealed,dict(beamSpring=100000.,beamDamp=10.))
        columns,_,_=axial_columns(xyz,[(0,1)]);g=gradient(xyz).ravel()
        step=(.0005**2*sealed['beamSpring']+.001*sealed['beamDamp'])*columns@columns.T
        step+=(.0005**2*joint['spring']+.001*joint['damp'])*np.outer(g,g)
        self.assertLessEqual(np.linalg.eigvalsh(step)[-1],3.200001)

    def test_assembled_connection_budget_preserves_existing_frame(self):
        nodes={str(i):dict(position=[float(i),0.,0.],options=dict(nodeWeight=1.)) for i in range(2)}
        sealed=dict(beamSpring=1000000.,beamDamp=100.);added=dict(beamSpring=10000000.,beamDamp=500.)
        part=dict(beams=[['id1:','id2:'],['0','1',sealed],['0','1',added]])
        report=budget_connections(part,nodes,[added])
        self.assertEqual(sealed,dict(beamSpring=1000000.,beamDamp=100.))
        self.assertGreater(report['connection_scale'],0);self.assertLess(report['connection_scale'],1)
        measured=2*(.0005**2*(sealed['beamSpring']+added['beamSpring'])+2*.0005*(sealed['beamDamp']+added['beamDamp']))
        self.assertAlmostEqual(measured,report['final_step_eigenvalue'])
        self.assertLessEqual(measured,3.2);self.assertGreater(measured,3.19)
        with self.assertRaisesRegex(ValueError,'Sealed frame'):
            budget_connections(dict(beams=[['id1:','id2:'],['0','1',dict(beamSpring=10000000.,beamDamp=0.)]]),nodes,[])

    def test_spherical_point_has_normal_restraint_without_a_second_child_point(self):
        xyz=np.array([[0.,0,0],[.4,0,0],[.2,.3,0],[.45,.35,0]])
        ids,k,d=point_constraint(xyz,np.ones(4))
        self.assertEqual(ids[-1],3)
        g=gradient(xyz[ids]);self.assertGreater(k*g[-1,2]**2,100000)
        self.assertLessEqual(.0005**2*k*np.sum(g*g)+2*.0005*d*np.sum(g*g),4)
        # Rigid translation/rotation of the parent and joint costs no energy.
        self.assertLess(np.linalg.norm(g.sum(axis=0)),1e-5)
        for axis in np.eye(3):
            self.assertLess(abs(np.sum(g*np.cross(axis,xyz[ids]))),1e-6)

    def test_flat_arm_has_six_rigid_modes_without_thickness_or_added_mass(self):
        xyz=np.array([[0.,0,0],[.4,0,0],[.4,.3,0],[0,.3,0],[.15,.1,0]])
        edges=list(itertools.combinations(range(5),2));mass=np.ones(5)
        springs,dampers,bars=reinforce(xyz,edges,mass)
        columns,_,_=axial_columns(xyz,edges);stiffness=(columns*springs)@columns.T
        damping=(columns*dampers)@columns.T
        for ids,k,c in bars:
            g=np.zeros((5,3));g[ids]=gradient(xyz[ids]);stiffness+=k*np.outer(g.ravel(),g.ravel())
            damping+=c*np.outer(g.ravel(),g.ravel())
        eigen=np.linalg.eigvalsh(stiffness)
        self.assertEqual(sum(eigen<1e-4),6)
        self.assertLessEqual(np.sqrt(eigen[-1])/(2*np.pi),400.0001)
        self.assertLessEqual(np.linalg.eigvalsh(.0005**2*stiffness+2*.0005*damping)[-1],2.000001)
        # The interior shock attachment can now resist out-of-plane loading.
        self.assertGreater(stiffness[14,14],100000)
        for rotation in np.eye(3):
            displacement=np.cross(rotation,xyz).ravel()
            self.assertLess(abs(displacement@stiffness@displacement),1e-4)


if __name__=='__main__':unittest.main()
