import unittest
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.spatial import ConvexHull

from frame_harness.cad import Body, audit_body, polygon_properties, volume_properties
from frame_harness.calibration import fit_masses, surface_distances, graph_response, graph_identity
from frame_harness.calibration import run_calibration
from frame_harness.calibration import fit_yield_capacities
from frame_harness.damage import component_count
from frame_harness.models import ParameterSet, TestScenario
from frame_harness.projection import axial_columns
from frame_harness.reference import element_matrix
from frame_harness.acceptance import evaluate_acceptance
from frame_harness.build import SOURCES, build_candidate, sha256, spring_fixture, write_json
from frame_harness.models import HarnessProject
from frame_harness.runner import spawn_height


def box():
    vertices=np.array([[x,y,z] for x in (-1.,1.) for y in (-1.,1.) for z in (-1.,1.)])
    faces=ConvexHull(vertices).simplices.copy()
    for i,f in enumerate(faces):
        a,b,c=vertices[f]
        if np.dot(np.cross(b-a,c-a),a)<0: faces[i]=f[::-1]
    return Body('cube',vertices,faces)


class CadTests(unittest.TestCase):
    def test_mass_allocation_is_permutation_and_reflection_invariant(self):
        rng=np.random.default_rng(321)
        half=rng.uniform([.1,-1,-.4],[.6,1,.4],size=(16,3))
        points=np.vstack([half,half*[-1,1,1]])
        weights=np.tile(rng.uniform(.2,3,16),2);mass=weights.sum();center=weights@points/mass
        rr=points-center;inertia=sum(m*(np.dot(p,p)*np.eye(3)-np.outer(p,p)) for m,p in zip(weights,rr))
        fitted,report=fit_masses(points,mass,center,inertia)
        order=rng.permutation(len(points));reordered,_=fit_masses(points[order],mass,center,inertia)
        np.testing.assert_allclose(fitted[order],reordered,atol=1e-8,rtol=0)
        np.testing.assert_allclose(fitted[:16],fitted[16:],atol=1e-8,rtol=0)
        self.assertLess(report['balance']['maximum_moment_residual'],1e-9)
    def test_closed_volume_inertia_and_translation(self):
        b=box(); p=volume_properties(b)
        self.assertAlmostEqual(p['volume_m3'],8)
        np.testing.assert_allclose(p['center_m'],0,atol=1e-12)
        np.testing.assert_allclose(p['inertia_per_density'],np.eye(3)*16/3,atol=1e-12)
        b.vertices+=np.array([20,30,40])
        shifted=volume_properties(b)
        np.testing.assert_allclose(shifted['center_m'],[20,30,40])
        np.testing.assert_allclose(shifted['inertia_per_density'],p['inertia_per_density'])

    def test_open_mesh_not_silently_capped(self):
        b=box(); b.faces=b.faces[1:]
        _,report=audit_body(b)
        self.assertFalse(report['valid'])
        self.assertNotIn('volume_m3',report)

    def test_zero_volume_export_sheet_is_cancelled_without_changing_mass(self):
        b=box();original=volume_properties(b)
        # A double-sided triangular fin shares a solid boundary edge.
        start=len(b.vertices);b.vertices=np.vstack((b.vertices,[[2.,0,0]]))
        a,c=b.faces[0,:2];b.faces=np.vstack((b.faces,[[a,c,start],[c,a,start]]))
        repaired,report=audit_body(b)
        self.assertTrue(report['valid'])
        self.assertEqual(report['cancelled_opposite_facets'],2)
        self.assertAlmostEqual(report['volume_m3'],original['volume_m3'])

    def test_sections_preserve_material_holes(self):
        outer=np.array([[-2,-2],[2,-2],[2,2],[-2,2]],dtype=float)
        inner=outer/2
        area,center,second=polygon_properties([outer,inner[::-1]])
        self.assertAlmostEqual(area,12)
        np.testing.assert_allclose(center,0,atol=1e-12)
        np.testing.assert_allclose(second,np.eye(2)*20,atol=1e-12)

    def test_surface_distance_uses_faces_not_only_vertices(self):
        b=Body('triangle',np.array([[0.,0,0],[10,0,0],[0,10,0]]),np.array([[0,1,2]]))
        np.testing.assert_allclose(surface_distances(np.array([[2.,2,1],[12,0,0]]),b),[1,2])

    def test_mass_fit_preserves_known_moments(self):
        points=np.vstack((box().vertices,[[0.,0,0]]))
        masses=np.r_[np.ones(8),16.]
        target=sum(m*(np.dot(p,p)*np.eye(3)-np.outer(p,p)) for m,p in zip(masses,points))
        fitted,report=fit_masses(points,24,np.zeros(3),target)
        self.assertTrue(report['accepted'])
        self.assertAlmostEqual(sum(fitted),24)
        self.assertLess(report['inertia_relative_error'],.001)
        self.assertTrue(np.all(fitted>0))


class ReferenceTests(unittest.TestCase):
    def test_mount_yield_envelope_preserves_global_onsets_and_exposes_conflicts(self):
        forces={'flex':np.array([1.,.02,.01,0]),'torsion':np.array([.02,1.,.01,0]),
                'mount':np.array([.01,.01,1.,.1]),'same_mount':np.array([.01,.01,1.,.1])}
        targets={k:{'first_yield_force_n':v} for k,v in zip(forces,[100,200,800,900])}
        capacity,report=fit_yield_capacities(np.full(4,20.),forces,targets)
        for name,force in forces.items():
            onset=1/np.max(abs(force)/capacity)
            self.assertGreaterEqual(onset,targets[name]['first_yield_force_n']*(1-1e-12))
            if name!='mount':self.assertAlmostEqual(onset,targets[name]['first_yield_force_n'])
        self.assertIsNone(report['active_beam_indices']['mount'])
        self.assertIsNotNone(report['active_beam_indices']['same_mount'])

    def test_independent_yield_loads_do_not_make_other_case_yield_early(self):
        forces={'flex':np.array([1.,.1,.2]),'torsion':np.array([.1,1.,.2])}
        targets={'flex':{'first_yield_force_n':100},'torsion':{'first_yield_force_n':200}}
        capacity,report=fit_yield_capacities(np.ones(3)*150,forces,targets)
        for name,force in forces.items():
            self.assertAlmostEqual(1/np.max(abs(force)/capacity),targets[name]['first_yield_force_n'])
        self.assertEqual(len(set(report['active_beam_indices'].values())),2)

    def test_analytical_axial_bending_and_torsion(self):
        length,area,iy,iz,j,e,nu=2.,.001,1e-6,2e-6,3e-6,205e9,.29
        k=element_matrix(length,area,iy,iz,j,e,nu)
        free=k[6:,6:]; shear=e/(2*(1+nu))
        for axis,expected in ((0,length/(e*area)),(1,length**3/(3*e*iz)+length/(.9*shear*area)),(2,length**3/(3*e*iy)+length/(.9*shear*area)),(3,length/(shear*j))):
            force=np.eye(6)[axis]
            actual=np.linalg.solve(free,force)[axis]
            self.assertAlmostEqual(actual/expected,1,places=10)
        np.testing.assert_allclose(k,k.T,atol=1e-12)
        self.assertEqual(np.count_nonzero(np.linalg.eigvalsh(k)>1e-5),6)

    def test_axial_graph_analytical_load(self):
        xyz=np.array([[0.,0,0],[1,0,1],[0,1,1],[0,0,1]])
        ends=np.array([[0,3],[1,3],[2,3]])
        columns,_,_=axial_columns(xyz,ends)
        s=TestScenario('test',8,0,['a','b','c'],['p'],1)
        compliance,force=graph_response(columns,np.array([1000.,1000,1000]),['a','b','c','p'],s)
        self.assertAlmostEqual(compliance,.001)
        self.assertAlmostEqual(abs(force[0]),1)

    def test_cut_does_not_confuse_first_break_with_separation(self):
        self.assertEqual(component_count(3,[(0,1),(1,2),(0,2)]),1)
        self.assertEqual(component_count(3,[(0,1),(1,2)]),1)
        self.assertEqual(component_count(3,[(0,1)]),2)

    def test_cut_load_uses_detached_mass_for_a_readable_separation(self):
        from frame_harness.damage import cut_separating_force
        nodes={'a':{'mass':1.},'b':{'mass':9.}}
        beams=[{'a':'a','b':'b'}]
        force=cut_separating_force(nodes,beams,[['a','b']],{'a':[0,-1,0]},2.)
        self.assertAlmostEqual(force*(41/3)/nodes['a']['mass'],2.)
        balanced=cut_separating_force(nodes,beams,[['a','b']],{'a':[0,-.5,0],'b':[0,.5,0]},2.)
        self.assertAlmostEqual(balanced*(41/3)*(.5/1+.5/9),2.)
        with self.assertRaisesRegex(ValueError,'separate positive-mass'):
            cut_separating_force(nodes,beams,[],{'a':[0,-1,0]},2.)
        with self.assertRaisesRegex(ValueError,'do not separate'):
            cut_separating_force(nodes,beams,[['a','b']],{'a':[0,-1,0],'b':[0,-9,0]},2.)

    def test_calibration_override_conflict_rejected(self):
        with self.assertRaises(ValueError):
            ParameterSet(calibration='saved.json',spring_scale=2).validate()
        with self.assertRaises(ValueError):
            TestScenario('cut',5,0,cut_edges=[['a','b']]).validate()


class ArtifactTests(unittest.TestCase):
    def test_spawn_height_accounts_for_reference_node_and_clears_free_cut_fixture(self):
        nodes={'ref':{'position':[0,0,.5]},'bottom':{'position':[0,1,.1]}}
        part={'refNodes':[['ref:','back:'],['ref','bottom']]}
        self.assertAlmostEqual(spawn_height(TestScenario.named('idle'),nodes,part),.42)
        self.assertEqual(spawn_height(TestScenario('cut',10,0),nodes,part),3)

    def test_calibrated_build_preserves_graph_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir()
            for name in SOURCES:(source/name).write_text('source snapshot')
            generated=root/'mochi.jbeam';part=spring_fixture(ParameterSet())
            write_json(generated,part)
            write_json(source/'mochi_raw.jbeam',part)
            artifact=root/'calibration.json'
            spec={'version':1,'source_hashes':{n:sha256(source/n) for n in SOURCES},'vehicle_file':'mochi.jbeam','vehicle_sha256':sha256(generated)}
            write_json(artifact,spec)
            scenario=TestScenario('elastic',8,0,['a','b','c'],['p'],10)
            build_candidate(HarnessProject(source=source),root/'run',ParameterSet(calibration=str(artifact)),scenario)
            actual=json.loads((root/'run'/'vehicle'/'mochi.jbeam').read_text())['mochi']
            self.assertEqual(graph_identity(actual),graph_identity(part['mochi']))
            self.assertNotIn('fixed',part['mochi']['nodes'][1])
            from frame_harness.build import node_table
            self.assertTrue(all(n['options']['collision'] is False for n in node_table(actual).values()))
            self.assertEqual(json.loads(generated.read_text()),{'mochi':part['mochi']})
            generated.write_text('{}')
            with self.assertRaisesRegex(ValueError,'modified'):
                build_candidate(HarnessProject(source=source),root/'tampered',ParameterSet(calibration=str(artifact)),scenario)


class AcceptanceTests(unittest.TestCase):
    def test_unmeasured_angular_damage_prevents_physical_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state();state['candidates']['steel']['angular_constraints']={'count':12,'damage_telemetry_qualified':False}
            result=evaluate_acceptance(state,Path(directory))['steel']
            self.assertFalse(result['accepted'])
            self.assertIn('Native torsion-bar damage telemetry is not qualified',result['reasons'])

    def test_numerical_mount_fit_does_not_qualify_mismatched_cad_stiffness(self):
        with tempfile.TemporaryDirectory() as directory:
            state=self.state();state['candidates']['steel']['local_mount_reference_qualified']=False
            result=evaluate_acceptance(state,Path(directory))['steel']
            self.assertFalse(result['accepted'])
            self.assertTrue(any('Local mounting stiffness' in reason for reason in result['reasons']))

    def state(self):
        response={'reference':{'compliance_m_n':1e-5,'first_yield_force_n':100}}
        state={'config':{'ramp_seconds':12.,'slow_ramp_seconds':24.},'instrument_accepted':True,
               'candidates':{'steel':{'offline_accepted':True,'mass':{'target_mass_kg':20},'responses':{'flex':response,'torsion':response}}},'runs':[]}
        metrics={'measured_mass_kg':20,'broken_beams':0,'max_rest_length_change_m':0,'final_shape_rms_m':.001,
                 'tail_world_speed_rms_m_s':.001,'hold_settled':True,'held_deflection_m':.001,
                 'first_yield_external_force_n':100,'first_break_external_force_n':150,'capture_complete':True,'final_components':2}
        for base in ('idle','flex','torsion'):
            for suffix in ('','-2','-3'):
                state['runs'].append({'key':'steel-'+base+suffix,'candidate':'steel','status':'completed','metrics':copy.deepcopy(metrics)})
        for base in ('flex','torsion'):
            for suffix in ('12','24','2','3'):
                state['runs'].append({'key':'steel-'+base+'-damage-'+suffix,'candidate':'steel','status':'completed','metrics':copy.deepcopy(metrics)})
        for f in (.35,.65):state['runs'].append({'key':f'mesh-cut-{f}','candidate':'steel','status':'completed','metrics':copy.deepcopy(metrics)})
        for r in state['runs']:r['path']=r['key']
        return state

    def test_acceptance_can_pass_but_requires_current_images_and_all_repeats(self):
        with tempfile.TemporaryDirectory() as directory, patch('frame_harness.acceptance.capture_evidence',return_value={'cut.png':{'sha256':'digest'}}):
            root=Path(directory);state=self.state()
            self.assertFalse(evaluate_acceptance(state,root)['steel']['accepted'])
            write_json(root/'mesh-review.json',{'capture_sha256':{'cut.png':'digest'},'cases':{'steel':True},'notes':'Inspected all prescribed rendered views.'})
            self.assertTrue(evaluate_acceptance(state,root)['steel']['accepted'])
            state['runs']=[r for r in state['runs'] if r['key']!='steel-flex-3']
            self.assertFalse(evaluate_acceptance(state,root)['steel']['accepted'])
            state=self.state();state['runs'][0]['metrics']['measured_mass_kg']=21
            self.assertFalse(evaluate_acceptance(state,root)['steel']['accepted'])
            state=self.state();state['runs'][0]['metrics']['mesh_load_valid']=False
            self.assertFalse(evaluate_acceptance(state,root)['steel']['accepted'])

    def test_no_break_is_censored_not_a_passing_strength_test(self):
        with tempfile.TemporaryDirectory() as directory, patch('frame_harness.acceptance.capture_evidence',return_value={'cut.png':{'sha256':'digest'}}):
            root=Path(directory);state=self.state()
            write_json(root/'mesh-review.json',{'capture_sha256':{'cut.png':'digest'},'cases':{'steel':True},'notes':'Reviewed.'})
            for r in state['runs']:r['metrics']['first_break_external_force_n']=None
            result=evaluate_acceptance(state,root)['steel']
            self.assertFalse(result['accepted'])
            self.assertTrue(any('threshold missing' in reason for reason in result['reasons']))


class CalibrationWorkflowTests(unittest.TestCase):
    def test_interrupted_generation_rebuilds_before_resuming_and_checks_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();part=spring_fixture(ParameterSet())['mochi']
            for name in SOURCES:(source/name).write_text('asset')
            write_json(source/'mochi_raw.jbeam',{'mochi':part})
            reference=Path(__file__).resolve().parents[1]/'examples'/'4130-reference.json'
            report={'mass':{'actual_mass_kg':1,'center_error_m':0,'inertia_relative_error':0},'offline_accepted':False}
            calls=[]
            def candidate(*args,**kwargs):
                calls.append(True)
                if len(calls)==2:raise KeyboardInterrupt
                return copy.deepcopy(part),copy.deepcopy(report)
            with patch('frame_harness.calibration.read_bodies',return_value=[box()]), \
                 patch('frame_harness.calibration.extract_member',return_value={}), \
                 patch('frame_harness.reference.build_frame',return_value={}), \
                 patch('frame_harness.reference.solve_frame',return_value={'first_yield_force_n':100,'compliance_m_n':.001}), \
                 patch('frame_harness.calibration.make_candidate',side_effect=candidate):
                project=HarnessProject(source=source)
                with self.assertRaises(KeyboardInterrupt):run_calibration(project,reference,root/'study',live=False)
                result=run_calibration(project,reference,root/'study',resume=True,live=False)
                self.assertEqual(result['status'],'offline_complete')
                self.assertEqual(len(result['candidates']),2)
                self.assertTrue((root/'study'/'4130-annealed'/'diagnostic-mod.zip').exists())
                (source/'material.json').write_text('changed')
                with self.assertRaisesRegex(ValueError,'Source, reference or implementation changed'):
                    run_calibration(project,reference,root/'study',resume=True,live=False)


if __name__=='__main__': unittest.main()
