import itertools
import unittest
import numpy as np
from frame_harness.elastic_fit import objective
from frame_harness.projection import axial_columns
from frame_harness.calibration import mass_properties,fit_masses


class ElasticFitTests(unittest.TestCase):
    def test_sparse_operator_matches_dense_value_gradient_and_spectral_penalty(self):
        from scipy.sparse import csc_matrix
        xyz=np.array([[0.,0,0],[1,0,0],[0,1,0],[0,0,1],[.6,.4,.8]])
        edges=list(itertools.combinations(range(5),2));columns,_,_=axial_columns(xyz,edges)
        initial=np.linspace(50,140,len(edges));weighted=columns/np.sqrt(np.repeat(np.linspace(1,2,5),3))[:,None]
        matrix=columns[9:];load=np.array([0,0,-.5,0,0,-.5]);values=np.linspace(-.2,.2,len(edges))
        for limit in (60.,1e5):
            dense=objective(values,initial,weighted,[(matrix,load,.01)],limit)
            sparse=objective(values,initial,csc_matrix(weighted),[(csc_matrix(matrix),load,.01)],limit)
            np.testing.assert_allclose(sparse[0],dense[0],rtol=1e-10)
            np.testing.assert_allclose(sparse[1],dense[1],rtol=1e-9,atol=1e-9)
            np.testing.assert_allclose(sparse[2]['compliance_ratios'],dense[2]['compliance_ratios'],rtol=1e-10)
            self.assertEqual(sparse[2]['excessive_modes'],dense[2]['excessive_modes'])

    def test_weak_seed_can_reach_feasible_response_without_exceeding_modal_cap(self):
        from scipy.optimize import minimize
        from frame_harness.calibration import ELASTIC_FIT_LOG_BOUNDS
        matrix=np.ones((1,1));initial=np.array([.01]);cases=[(matrix,np.ones(1),.01)]
        def evaluate(x):return objective(x,initial,matrix,cases,1000.)
        restricted=minimize(lambda x:evaluate(x)[:2],np.zeros(1),jac=True,method='L-BFGS-B',bounds=[(-12.,6.)])
        self.assertGreater(max(evaluate(restricted.x)[2]['projected_relative_errors']),1.)
        fit=minimize(lambda x:evaluate(x)[:2],np.zeros(1),jac=True,method='L-BFGS-B',bounds=[ELASTIC_FIT_LOG_BOUNDS])
        stats=evaluate(fit.x)[2]
        self.assertTrue(fit.success);self.assertLess(max(stats['projected_relative_errors']),.001)
        self.assertEqual(stats['excessive_modes'],0);self.assertEqual(stats['projection_scale'],1.)

    def test_corresponding_mounts_preserve_cad_ratio_below_local_ceilings(self):
        from scipy.optimize import minimize
        matrix=np.eye(2);initial=np.array([100.,400.]);cases=[(matrix,v,.02,True) for v in matrix]
        pairs=[(0,1,2.)]  # Deliberately asymmetric CAD, not a symmetry assumption.
        def evaluate(x):return objective(x,initial,matrix,cases,1e6,regularizer=0,response_pairs=pairs)
        values=np.array([.1,-.15]);_,analytic,_=evaluate(values)
        numeric=[(evaluate(values+v*1e-6)[0]-evaluate(values-v*1e-6)[0])/2e-6 for v in matrix]
        np.testing.assert_allclose(analytic,numeric,atol=1e-8,rtol=1e-6)
        fit=minimize(lambda x:evaluate(x)[:2],np.zeros(2),jac=True,method='L-BFGS-B')
        stats=evaluate(fit.x)[2]
        self.assertTrue(fit.success)
        self.assertLess(max(stats['response_pair_relative_errors']),1e-6)
        self.assertLess(max(stats['compliance_ratios']),1.)
        # A shared modal projection rescales both responses, never their ratio.
        projected=objective(fit.x,initial,matrix,cases,100.,regularizer=0,response_pairs=pairs)[2]
        self.assertLess(projected['projection_scale'],1.)
        np.testing.assert_allclose(projected['response_pair_relative_errors'],stats['response_pair_relative_errors'])

    def test_shared_supports_factor_once_with_identical_response_and_gradient(self):
        from unittest.mock import patch
        from scipy.linalg import cho_factor
        matrix=np.eye(3);load=np.eye(3);initial=np.array([100.,200.,300.]);values=np.array([.1,-.2,.15])
        shared=[(matrix,v,.005) for v in load]
        independent=[(matrix.copy(),v,.005) for v in load]
        expected=objective(values,initial,matrix,independent,1e6)
        with patch('frame_harness.elastic_fit.cho_factor',wraps=cho_factor) as factor:
            actual=objective(values,initial,matrix,shared,1e6)
        self.assertEqual(factor.call_count,1)
        self.assertAlmostEqual(actual[0],expected[0]);np.testing.assert_allclose(actual[1],expected[1],atol=1e-12)
        np.testing.assert_allclose(actual[2]['compliance_ratios'],expected[2]['compliance_ratios'],atol=1e-12)

    def test_minimax_gradient_across_signed_and_ceiling_responses(self):
        matrix=np.eye(3);initial=np.array([100.,200.,300.]);values=np.array([.1,-.2,.15])
        cases=[(matrix,np.array([1.,0,0]),.008),(matrix,np.array([0.,1,0]),.008),
               (matrix,np.array([0.,0,1]),.002,True)]
        _,analytic,_=objective(values,initial,matrix,cases,1e6)
        numeric=[]
        for i in range(3):
            delta=np.eye(3)[i]*1e-6
            numeric.append((objective(values+delta,initial,matrix,cases,1e6)[0]-objective(values-delta,initial,matrix,cases,1e6)[0])/2e-6)
        np.testing.assert_allclose(analytic,numeric,atol=1e-8,rtol=1e-6)

    def test_numerical_ceiling_does_not_soften_an_already_stiffer_connection(self):
        matrix=np.array([[1.]]);weighted=matrix.copy();initial=np.array([100.]);load=np.array([1.])
        value,gradient,stats=objective(np.zeros(1),initial,weighted,[(matrix,load,.02,True)],1e6,regularizer=0)
        self.assertEqual(value,0);self.assertEqual(gradient[0],0);self.assertEqual(stats['projected_relative_errors'],[0.])
        value,gradient,_=objective(np.zeros(1),initial,weighted,[(matrix,load,.005,True)],1e6,regularizer=0)
        self.assertGreater(value,0);self.assertLess(gradient[0],0)
        h=1e-6
        numeric=(objective(np.array([h]),initial,weighted,[(matrix,load,.005,True)],1e6,regularizer=0)[0]-
                 objective(np.array([-h]),initial,weighted,[(matrix,load,.005,True)],1e6,regularizer=0)[0])/(2*h)
        self.assertAlmostEqual(gradient[0],numeric,places=7)

    def test_analytic_gradient_matches_independent_finite_differences(self):
        xyz=np.array([[0.,0,0],[1,0,0],[0,1,0],[0,0,1],[.6,.4,.8]])
        edges=list(itertools.combinations(range(5),2));columns,_,_=axial_columns(xyz,edges)
        initial=np.linspace(50,140,len(edges));weighted=columns/np.sqrt(np.repeat(np.linspace(1,2,5),3))[:,None]
        matrix=columns[9:];load=np.array([0,0,-.5,0,0,-.5]);cases=[(matrix,load,.01)]
        values=np.linspace(-.2,.2,len(edges))
        for limit in (60.,1e5):
            _,gradient,stats=objective(values,initial,weighted,cases,limit)
            numerical=[]
            for i in range(len(values)):
                delta=np.zeros(len(values));delta[i]=1e-6
                numerical.append((objective(values+delta,initial,weighted,cases,limit)[0]-objective(values-delta,initial,weighted,cases,limit)[0])/2e-6)
            np.testing.assert_allclose(gradient,numerical,rtol=2e-5,atol=1e-5)
            self.assertEqual(stats['excessive_modes']>0,limit==60.)
    def test_native_mass_scales_tessellated_inertia_consistently(self):
        audit=dict(volume_m3=.99,center_m=[1.,2,3],inertia_per_density=(np.eye(3)*.4).tolist(),native_mass_kg=10.)
        mass,center,inertia=mass_properties([audit],10.)
        self.assertEqual(mass,10.)
        np.testing.assert_allclose(center,[1,2,3])
        np.testing.assert_allclose(inertia,np.eye(3)*4/.99)
    def test_proximity_weighting_keeps_exact_moments_and_positive_nodes(self):
        points=np.array(list(itertools.product((-1.,1.),repeat=3))+[[0.,0.,0.]])
        # Several feasible distributions exist: moving mass from the center to
        # corners would alter inertia, so the fit must obey both constraints.
        masses,report=fit_masses(points,10.,np.zeros(3),np.eye(3)*10.,np.r_[np.ones(8),3.])
        self.assertTrue(report['accepted']);self.assertGreater(min(masses),0)
        self.assertAlmostEqual(sum(masses),10.)
        np.testing.assert_allclose(masses@points,np.zeros(3),atol=1e-9)
        np.testing.assert_allclose(sum(m*(np.dot(v,v)*np.eye(3)-np.outer(v,v)) for m,v in zip(masses,points)),np.eye(3)*10.,atol=1e-8)


if __name__=='__main__':unittest.main()
