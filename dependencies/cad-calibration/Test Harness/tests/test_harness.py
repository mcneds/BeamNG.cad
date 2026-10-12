import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from frame_harness.build import build_candidate, node_table, validate_part, write_json
from frame_harness.models import HarnessProject, ParameterSet, TestScenario
from frame_harness.report import rigid_align, settling_time, compare_runs
from frame_harness.runner import prepare_userpath, read_json, run_test, run_attempt, validate_recording, check_recording_space


class MeasurementTests(unittest.TestCase):
    def test_completion_flag_does_not_make_truncated_telemetry_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            job={"id":"test", "scenario":{"duration":1,"load_nodes":["p"]}, "expected_nodes":2,"expected_beams":1}
            completion={"job_id":"test","simulated_seconds":1,"trajectory_samples":2,"physics_steps":2}
            for name, rows in (("nodes.csv",4),("beams.csv",2),("loads.csv",2),("probes.csv",2)):
                (root/name).write_text("header\n"+"data\n"*rows)
            validate_recording(root,job,completion)
            (root/"probes.csv").write_text("header\ndata\n")
            with self.assertRaisesRegex(RuntimeError,"Incomplete telemetry"):
                validate_recording(root,job,completion)

    def test_low_disk_space_is_rejected_before_recording(self):
        with patch("frame_harness.runner.shutil.disk_usage",return_value=Mock(free=100)):
            with self.assertRaisesRegex(RuntimeError,"Insufficient disk space"):
                check_recording_space(Path("."),Path("."))

    def test_rigid_motion_is_not_deformation(self):
        reference=np.array([[0.,0,0],[1,0,0],[0,1,0],[0,0,1]])
        angle=.6
        rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
        moving=reference@rotation+np.array([10,-2,5])
        np.testing.assert_allclose(rigid_align(moving,reference),reference,atol=1e-12)
        moving[3,2]+=.1
        self.assertGreater(np.linalg.norm(rigid_align(moving,reference)-reference),.01)

    def test_settling_requires_persistent_return_to_zero(self):
        t=np.linspace(0,10,1001)
        settled=np.where(t<2,1,np.exp(-(t-2)*2))
        self.assertAlmostEqual(settling_time(t,settled,2,.05),1.5,places=1)
        self.assertIsNone(settling_time(t,np.ones_like(t),2,.05))

    def test_json_reader_ignores_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"result.json"; p.write_text('{"status":')
            self.assertIsNone(read_json(p))


class ExperimentTests(unittest.TestCase):
    def test_fixture_does_not_touch_source_and_has_correct_supports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/"source"; source.mkdir()
            sentinel=source/"keep.txt"; sentinel.write_text("unchanged")
            run=root/"run"; run.mkdir()
            project=HarnessProject(source=source)
            manifest=build_candidate(project,run,ParameterSet(),TestScenario.named("spring"))
            self.assertEqual(sentinel.read_text(),"unchanged")
            self.assertEqual(manifest["beam_count"],3)
            nodes=manifest["nodes"]
            self.assertTrue(nodes["a"]["options"]["fixed"])
            self.assertFalse(nodes["p"]["options"].get("fixed",False))

    def test_missing_fixture_node_fails_before_launch(self):
        part={"nodes":[["id","posX","posY","posZ"],["one",0,0,0]]}
        with self.assertRaisesRegex(ValueError,"Fixture nodes missing"):
            validate_part(part,TestScenario.named("flex"))

    def test_unowned_user_folder_is_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/"personal.txt").write_text("keep")
            with self.assertRaisesRegex(ValueError,"non-harness"):
                prepare_userpath(HarnessProject(userpath=root))
            self.assertEqual((root/"personal.txt").read_text(),"keep")

    def test_negative_and_nonfinite_parameters_rejected(self):
        for value in (-1,0,float("nan"),float("inf")):
            with self.assertRaises(ValueError): ParameterSet(spring_scale=value).validate()

    def test_invalid_fixture_timing_and_load_nodes_rejected(self):
        scenario=TestScenario.named("flex")
        scenario.ramp_s=0
        with self.assertRaises(ValueError): scenario.validate()
        scenario=TestScenario.named("flex")
        scenario.load_nodes.append(scenario.fixed_nodes[0])
        with self.assertRaisesRegex(ValueError,"fixed support"): scenario.validate()

    def test_missing_input_is_a_saved_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            result=run_test(HarnessProject(source=root/"absent",runs=root/"runs"),TestScenario.named("flex"),ParameterSet(calibration=str(root/'absent.json')))
            self.assertEqual(result.status,"failed")
            self.assertIn("FileNotFoundError",result.failure_reason)
            self.assertTrue((Path(result.path)/"error.log").exists())

    def test_frame_recordings_require_a_calibrated_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError, 'calibrated artifact is required'):
                build_candidate(HarnessProject(source=root/'source'),root/'run',ParameterSet(),TestScenario.named('flex'))

    def test_comparison_rejects_different_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); paths=[]
            for i in range(2):
                p=root/str(i); p.mkdir(); paths.append(p)
                write_json(p/"result.json",{"status":"completed"})
                write_json(p/"experiment.json",{"scenario":{"name":"flex","force":100+i},"parameters":{"name":str(i)}})
                write_json(p/"metrics.json",{"held_deflection_m":.1})
                write_json(p/"build_manifest.json",{"nodes":{}})
            with self.assertRaisesRegex(ValueError,"different loads"):
                compare_runs(paths,root/"comparison")

    def test_repeated_path_is_not_independent_evidence(self):
        with self.assertRaisesRegex(ValueError,"multiple repeats"):
            compare_runs([Path("same-run"),Path("same-run")],Path("comparison"))

    def test_launch_failures_save_diagnostics_and_close_owned_process(self):
        for mode in ("exit", "timeout", "load-failure"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                project=HarnessProject(userpath=root/"user",runs=root/"runs",startup_timeout=0)
                run=root/"run"; run.mkdir()
                scenario=TestScenario.named("spring")
                manifest=build_candidate(project,run,ParameterSet(),scenario)
                prepare_userpath(project)
                process=Mock(returncode=7,pid=12345)
                process.poll.return_value=7 if mode=="exit" else None
                def fake_launch(*args,**kwargs):
                    if mode=="load-failure":
                        write_json(project.userpath/"current/settings/frame_harness/status.json",
                                   {"state":"failed","reason":"Vehicle failed to load","session_id":read_json(project.userpath/"current/settings/frame_harness/session.json")["session_id"],"job_id":run.name+"-0"})
                    return process
                with patch("frame_harness.runner.subprocess.Popen",side_effect=fake_launch):
                    state, target=run_attempt(project,run,scenario,manifest,0)
                self.assertEqual(state["status"],"failed")
                self.assertIn({"exit":"exited", "timeout":"Vehicle startup timed out", "load-failure":"Vehicle failed"}[mode],state["reason"])
                self.assertTrue((target/"attempt_result.json").is_file())
                if mode!="exit": process.wait.assert_called_once_with(5)

    def test_retry_records_failure_then_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            project=HarnessProject(game=root/"game",runs=root/"runs",userpath=root/"user")
            project.executable.parent.mkdir(parents=True)
            project.executable.touch()
            def fake_attempt(project,run,scenario,manifest,attempt,session):
                target=run/f"attempt-{attempt}"; target.mkdir()
                state={"status":"failed","reason":"startup","failure_kind":"infrastructure"} if attempt==0 else {"status":"completed"}
                write_json(target/"attempt_result.json",state)
                return state,target
            with patch("frame_harness.runner.run_attempt",side_effect=fake_attempt) as attempt:
                result=run_test(project,TestScenario.named("spring"),analyze=False)
            self.assertEqual(attempt.call_count,2)
            self.assertEqual(result.status,"completed")
            self.assertIsNone(result.failure_reason)
            self.assertEqual(read_json(Path(result.path)/"telemetry_location.json")["directory"],"attempt-1")


if __name__=="__main__": unittest.main()
