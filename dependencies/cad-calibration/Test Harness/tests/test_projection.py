import copy
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from frame_harness.models import ParameterSet, TestScenario
from frame_harness.projection import axial_columns, modal_frequencies, project_springs, reduced_mass_damping
from frame_harness.report import probe_response


class ProjectionTests(unittest.TestCase):
    def test_free_two_mass_spring_frequency_and_rigid_modes(self):
        columns, _, _ = axial_columns([[0, 0, 0], [1, 0, 0]], [[0, 1]])
        frequencies = modal_frequencies(columns, [2, 3], [120])
        self.assertAlmostEqual(frequencies[-1], math.sqrt(120*(1/2+1/3))/(2*math.pi))
        np.testing.assert_allclose(frequencies[:-1], 0, atol=1e-7)
        np.testing.assert_allclose(columns.T @ np.tile([2, -1, 3], 2), 0)

    def test_local_and_modal_projection_obey_limits_without_stiffening_raw_beams(self):
        endpoints = np.array([[0, 1], [1, 2], [2, 3], [0, 2]])
        columns, _, _ = axial_columns([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 1]], endpoints)
        raw = np.array([1e7, 1e3, 1e5, 1e6])
        masses = np.array([1., 2, 3, 4])
        for mode in ("modal_global", "local_capped"):
            springs = project_springs(columns, endpoints, masses, raw, 30, mode)
            self.assertTrue(np.all((springs >= 0) & (springs <= raw)))
            self.assertLessEqual(modal_frequencies(columns, masses, springs)[-1], 30*(1+1e-12))
            if mode == "local_capped":
                incident = np.bincount(endpoints.ravel(), weights=np.repeat(springs, 2), minlength=4)
                self.assertTrue(np.all(incident <= masses*(2*np.pi*30)**2*(1+1e-12)))


    def test_damping_uses_final_spring_and_reduced_mass(self):
        np.testing.assert_allclose(reduced_mass_damping([100], [2, 3], [[0, 1]], .04), [.08*math.sqrt(120)])


class ForceMeasurementTests(unittest.TestCase):
    def test_opposing_load_motion_adds_instead_of_cancelling(self):
        scenario = TestScenario.named("torsion")
        scenario.validate()
        self.assertEqual(np.sum(list(scenario.resolved_load_vectors().values()), axis=0).tolist(), [0, 0, 0])
        from dataclasses import asdict
        metadata = {"nodes": [{"name": "sp01l", "cid": 3, "initial": [1, 0, 0]},
                               {"name": "sp01r", "cid": 8, "initial": [-1, 0, 0]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            csv = "t,cid,x,y,z,vx,vy,vz,force_n,fx,fy,fz\n3.5,3,1,0,-.001,0,0,-.002,50,0,0,-50\n3.5,8,-1,0,.001,0,0,.002,50,0,0,50\n"
            (path/"probes.csv").write_text(csv)
            response = probe_response(path, metadata, asdict(scenario))
            self.assertAlmostEqual(response["displacement"][0], .001)
            self.assertAlmostEqual(response["velocity"][0], .002)
            self.assertTrue(response["force_consistent"])
            (path/"probes.csv").write_text(csv.replace(".002,50,0,0,50", ".002,50,0,0,-50"))
            self.assertFalse(probe_response(path, metadata, asdict(scenario))["force_consistent"])

    def test_legacy_probe_columns_are_supported_in_any_order(self):
        scenario = TestScenario.named("spring")
        from dataclasses import asdict
        metadata = {"nodes": [{"name": "p", "cid": 4, "initial": [0, 0, 1]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/"probes.csv").write_text("cid,t,z,y,x,vz,vy,vx,force_n\n4,2.5,.99,0,0,0,0,0,10\n")
            response = probe_response(path, metadata, asdict(scenario))
            self.assertAlmostEqual(response["displacement"][0], .01)
            self.assertIsNone(response["force_consistent"])

    def test_nonunit_force_patterns_are_rejected(self):
        scenario = TestScenario.named("torsion")
        scenario.load_vectors["sp01l"][2] = -1
        with self.assertRaisesRegex(ValueError, "sum to one"):
            scenario.validate()
