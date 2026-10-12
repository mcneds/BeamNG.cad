"""Bent, CAD-owned driveshaft chains; analytic fixtures are not live acceptance."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from test_vehicle_template_graph import fixture
import components as c
import shaft_chains as s
from vehicle_templates import generate, frame_mount_plan
from vehicle_revisions import physical_snapshot
from frame_harness.build import node_table


def bent_chain(spec, components, moments):
    old=spec['shafts'].pop('front_propshaft')
    components[:]=[v for v in components if v['Id']!='front_propshaft'];moments.pop('front_propshaft')
    # Deliberately different axes, non-default IDs and unequal section masses.
    points=[old['outer'],[.10,.95,.42],old['inner']]
    parents=['rear_final_drive','bearing_a','front_diff']
    for index,owner in enumerate(('rear_section','front_section')):
        components.append(dict(Id=owner,MvpRole='front_propshaft',Name=owner,Template='bulk'))
        center=(np.array(points[index])+points[index+1])/2;mass=1.8+index*.9
        moments[owner]=(mass,center,np.eye(3)*.01)
    components.append(dict(Id='bearing_a',MvpRole='shaft_carrier',Name='Carrier',Template='bulk'))
    center=np.array(points[1]);moments['bearing_a']=(2.,center,np.eye(3)*.004)
    spec['fixed_mounts']['bearing_a']=[(center+offset).tolist() for offset in ([-.06,0,-.05],[.06,0,-.05],[0,.06,-.05])]
    spec['shaft_chains']={'front_drive':dict(role='front_propshaft',
        joints=[dict(position=p,parent_component=parent) for p,parent in zip(points,parents)],
        segments=[dict(component='rear_section',plunge_m=0.),dict(component='front_section',plunge_m=.02)])}


class ShaftChainTests(unittest.TestCase):
    def test_explicit_fixed_sections_require_valid_rigid_attachments(self):
        parts=[dict(Id=n,MvpRole='front_propshaft') for n in ('first','second')]
        spec=dict(fixed_shafts=['first','second'],fixed_mounts={n:[[0,0,0],[1,0,0],[0,1,0]] for n in ('first','second')})
        self.assertEqual(s.validate(spec,parts),{})
        for alter in (lambda d:d['fixed_mounts'].pop('first'),
                      lambda d:d['fixed_mounts'].update(first=[[0,0,0],[1,0,0],[2,0,0]]),
                      lambda d:d.update(shafts={'first':{}}),
                      lambda d:d['fixed_shafts'].append('first')):
            bad=copy.deepcopy(spec);alter(bad)
            with self.assertRaises(ValueError):s.validate(bad,parts)

    def test_unequal_sections_keep_cad_mass_shared_joint_and_separate_bindings(self):
        project,frame,spec,cad=fixture('primary',bent_chain)
        with patch.object(c,'read_geometry',side_effect=cad):
            graph,part,wheels,_,drive,meshes,bindings=generate(project,frame,spec)
        chain=graph.shaft_chains['front_drive'];nodes=node_table(part)
        a,joint,b=[v['node'] for v in chain['joints']]
        self.assertEqual(set(graph.mass_allocations['rear_section']),{a,joint})
        self.assertEqual(set(graph.mass_allocations['front_section']),{joint,b})
        self.assertAlmostEqual(nodes[joint]['mass'],(1.8+2.7)/2)
        self.assertNotEqual(bindings['rear_section'],bindings['front_section'])
        self.assertNotIn('front_section_structure',nodes[a]['options']['group'])
        self.assertNotIn('rear_section_structure',nodes[b]['options']['group'])
        self.assertLess(abs(np.dot(*(v['axis'] for v in chain['segments']))),.999)
        self.assertFalse(any({row[0],row[1]}=={a,b} for row in part['beams'][1:] if isinstance(row,list)))
        self.assertEqual(len([v for v in graph.joints if v['id']==joint+'_support']),1)
        self.assertEqual(next(v for v in graph.joints if v['id']==joint+'_support')['parent'],'bearing_a')
        for n in (a,joint,b):
            self.assertFalse(nodes[n]['options']['collision'])
            self.assertAlmostEqual(nodes[n]['mass'],sum(alloc.get(n,0) for alloc in graph.mass_allocations.values()))
        expected=sum(cad(v)[1][0] for v in project['Components'])
        actual=sum(v['mass'] for v in nodes.values())+sum(v['wheel_mass_kg'] for v in wheels.values())
        # The synthetic frame contains pre-calibration locator mass.
        self.assertAlmostEqual(actual-expected,sum(v['mass'] for v in node_table(frame).values())-cad(project['Components'][0])[1][0])
        self.assertEqual(drive['shaft_chains']['front_drive']['device'],'frontPropshaft')
        self.assertEqual([r[2] for r in part['powertrain'][1:] if r[1]=='frontPropshaft'],['frontOutputGear'])
        self.assertEqual(len([r for r in part['powertrain'][1:] if r[1]=='frontPropshaft']),1)
        self.assertEqual(set(meshes)&{'rear_section','front_section','bearing_a'},{'rear_section','front_section','bearing_a'})

    def test_legacy_straight_shaft_still_uses_original_nodes(self):
        project,frame,spec,cad=fixture('primary')
        with patch.object(c,'read_geometry',side_effect=cad):graph,*_=generate(project,frame,spec)
        self.assertEqual(graph.shaft_chains,{})
        self.assertEqual(graph.groups['front_propshaft'],['front_propshaft_inner','front_propshaft_outer'])

    def test_multiple_sections_require_explicit_order_before_frame_calibration(self):
        project,_,spec,_=fixture('primary',bent_chain);spec.pop('shaft_chains')
        with self.assertRaisesRegex(ValueError,'ordered shaft_chains'):frame_mount_plan(spec,project['Components'])

    def test_invalid_topology_does_not_get_silently_joined_or_fixed(self):
        project,_,spec,_=fixture('primary',bent_chain)
        cases={
            'missing_carrier':lambda d:d['joints'][1].pop('parent_component'),
            'wrong_parent':lambda d:d['joints'][1].update(parent_component='front_diff'),
            'collapsed':lambda d:d['joints'][1].update(position=d['joints'][0]['position']),
            'nan_point':lambda d:d['joints'][1].update(position=[0,float('nan'),0]),
            'duplicate_owner':lambda d:d['segments'][1].update(component='rear_section'),
            'missing_plunge':lambda d:d['segments'][1].pop('plunge_m'),
            'infinite_plunge':lambda d:d['segments'][1].update(plunge_m=float('inf')),
            'negative_plunge':lambda d:d['segments'][1].update(plunge_m=-.001),
            'wrong_end':lambda d:d['joints'][0].update(parent_component='cvt'),
            'missing_section':lambda d:d['segments'].pop(),
        }
        for name,alter in cases.items():
            bad=copy.deepcopy(spec);alter(bad['shaft_chains']['front_drive'])
            with self.subTest(name=name),self.assertRaises(ValueError):s.validate(bad,project['Components'])
        bad=copy.deepcopy(spec);bad['shafts']['rear_section']=spec['shafts']['cvt_output_shaft']
        with self.assertRaisesRegex(ValueError,'duplicate physical ownership'):s.validate(bad,project['Components'])

    def test_carrier_mount_changes_are_in_frame_calibration_plan(self):
        project,frame,spec,_=fixture('primary',bent_chain)
        plan=frame_mount_plan(spec,project['Components'])
        self.assertEqual(plan['bearing_a_0']['mode'],'direct')
        spec['fixed_mounts']['bearing_a'][0][0]+=.01
        with self.assertRaisesRegex(ValueError,'Mount moved'):generate(project,frame,spec)

    def test_chain_contract_is_sealed_in_physical_snapshot(self):
        contents={'vehicle.jbeam':b'{"car":{"nodes":[]}}'}
        before=physical_snapshot(contents,{'shaft_chains':{'chain':{'plunge_m':.01}}})
        after=physical_snapshot(contents,{'shaft_chains':{'chain':{'plunge_m':.02}}})
        self.assertNotEqual(before['sha256'],after['sha256'])

    def test_documented_fragment_validates_against_independent_cad_groups(self):
        project,_,spec,_=fixture('primary',bent_chain)
        fragment=json.loads((Path(__file__).resolve().parents[1]/'examples/shaft-chain-fragment.json').read_text())
        spec['shaft_chains']=fragment['shaft_chains'];spec['fixed_mounts'].update(fragment['fixed_mounts'])
        self.assertEqual(len(s.validate(spec,project['Components'])['front_drive']['segments']),2)


if __name__=='__main__':unittest.main()
