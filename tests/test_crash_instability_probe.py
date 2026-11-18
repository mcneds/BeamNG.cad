import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('crash_probe', ROOT / 'tools/probe-crash-instability.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
spec = importlib.util.spec_from_file_location('crash_analysis', ROOT / 'tools/analyze-crash-instability.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class CrashFixtureTests(unittest.TestCase):
    def test_candidates_preserve_source_and_keep_native_expectations(self):
        part = dict(nodes=[['id', 'posX', 'posY', 'posZ'],
                           ['a', 0, 0, 0, dict(nodeWeight=1, collision=False, staticCollision=True)],
                           ['b', 1, 0, 0, dict(nodeWeight=2, collision=True, staticCollision=True)]],
                    beams=[['id1:', 'id2:'], ['a', 'b', dict(beamSpring=12, beamDamp=2)]],
                    torsionbars=[['id1:', 'id2:', 'id3:', 'id4:'],
                                 ['a', 'b', 'c', 'd', dict(spring=80, damp=4)]],
                    flexbodies=[['mesh'], ['appearance']], props=[['mesh']])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            original = json.dumps({'car': part}).encode()
            (source / 'car.jbeam').write_bytes(original)
            (source / 'appearance.dae').write_text('private CAD mesh')
            (source / 'base.pc').write_text('{}')
            for candidate in ('baseline', 'no-angular', 'angular-quarter', 'no-internal-static'):
                destination, run = root / candidate, root / (candidate + '-run')
                run.mkdir()
                manifest = dict(model='car', torsionbars=copy.deepcopy(part['torsionbars'][1:]))
                expected, changed = probe.stage(source, destination, manifest, run, candidate)
                staged = json.loads((destination / 'car.jbeam').read_text())['car']
                self.assertEqual((source / 'car.jbeam').read_bytes(), original)
                self.assertFalse((destination / 'appearance.dae').exists())
                self.assertNotIn('flexbodies', staged)
                self.assertNotIn('props', staged)
                self.assertEqual(staged['beams'], part['beams'])
                self.assertEqual(expected, probe.beam_table(staged))
                self.assertEqual(manifest['torsionbars'], staged['torsionbars'][1:])
                self.assertIn('/vehicles/car/car.jbeam', changed)
                self.assertEqual(staged['nodes'][2], part['nodes'][2])
                if candidate == 'no-internal-static':
                    self.assertFalse(staged['nodes'][1][-1]['staticCollision'])
                else:
                    self.assertEqual(staged['nodes'], part['nodes'])
                if candidate == 'angular-quarter':
                    self.assertEqual(staged['torsionbars'][1][-1], dict(spring=20, damp=1))
                if candidate == 'no-angular':
                    self.assertEqual(len(staged['torsionbars']), 1)

    def test_instrumentation_preserves_compiled_graph_validation(self):
        source = (ROOT / 'dependencies/cad-calibration/Test Harness/frame_harness/lua/vehicle_recorder.lua').read_text()
        instrumented = probe.instrument(source)
        self.assertIn('Compiled beam/properties differ', instrumented)
        self.assertIn('Compiled angular brace differs', instrumented)
        self.assertIn('Node speed exceeded 1000 m/s', instrumented)
        self.assertEqual(instrumented.count(probe.HOOK), 1)
        with self.assertRaises(ValueError):
            probe.instrument(source.replace('M.start=protected(start)', 'M.start=start'))

    def test_tangent_matches_two_mass_oscillator_and_ignores_broken_beam(self):
        nodes = {'a': dict(cid=0, mass_kg=2, position=[0, 0, 0]),
                 'b': dict(cid=1, mass_kg=3, position=[1, 0, 0]),
                 'c': dict(cid=2, mass_kg=4, position=[2, 0, 0])}
        beam = dict(cid=0, a=0, b=1, beam_type=0, spring=1200000., damp=100.)
        compiled = dict(actual_nodes=nodes, beams=[beam], torsionbars=[])
        expected = (.0005**2 * beam['spring'] + .001 * beam['damp']) * (1/2 + 1/3)
        self.assertAlmostEqual(analysis.tangent(compiled)['step_eigenvalue'], expected)
        # A remote weak surviving beam leaves a nonzero matrix after breakage.
        compiled['beams'].append(dict(cid=1, a=1, b=2, beam_type=0, spring=120., damp=0.))
        snapshot = dict(nodes={str(n['cid']): dict(p=n['position']) for n in nodes.values()},
                        beams=[dict(cid=0, broken=True), dict(cid=1, broken=False)])
        self.assertAlmostEqual(analysis.tangent(compiled, snapshot)['step_eigenvalue'],
                               .0005**2 * 120 * (1/3 + 1/4))

    def test_structural_mitigation_preserves_physical_coilover_coefficients(self):
        structure = ['a', 'b', dict(beamSpring=100, beamDamp=10, beamStrength=200)]
        coilover = ['b', 'c', dict(beamSpring=20, beamDamp=3, beamType='|BOUNDED')]
        part = dict(beams=[['id1:', 'id2:'], structure, coilover],
                    torsionbars=[['id1:', 'id2:', 'id3:', 'id4:'],
                                 ['a', 'b', 'c', 'd', dict(spring=80, damp=4)]])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, run = root / 'source', root / 'run'
            source.mkdir(); run.mkdir()
            (source / 'car.jbeam').write_text(json.dumps({'car': part}))
            for candidate, spring, damp in [('structural-half', 50, 5), ('structural-damp-quarter', 100, 2.5)]:
                destination = root / candidate
                probe.stage(source, destination, dict(model='car'), run, candidate)
                staged = json.loads((destination / 'car.jbeam').read_text())['car']
                self.assertEqual(staged['beams'][1][-1], dict(beamSpring=spring, beamDamp=damp, beamStrength=200))
                self.assertEqual(staged['beams'][2], coilover)


if __name__ == '__main__':
    unittest.main()
