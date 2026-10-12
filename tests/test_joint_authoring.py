import copy
import json
import sys
import unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from joint_authoring import classify,proposals,resolve_bindings


class CapturedJointPointTests(unittest.TestCase):
    def test_distinct_native_hinge_pivots_keep_their_cad_positions(self):
        p=dict(Anchors=[dict(Id=k,ComponentId='arm',Status='resolved',Position=[0,y,0]) for k,y in [('a',-.2),('b',.2)]],
               JointWorkspace=dict(Joints=[dict(Id='hinge',Parent='frame',Child='arm',Status='approved',Kind='revolute',Center=[0,0,0],Axis=[0,1,0])],
                   Bindings=[dict(Request=k,ComponentId='arm',JointId='hinge',AnchorId=k,Point='anchor',Status='resolved') for k in ('a','b')]))
        result=resolve_bindings(p)
        self.assertEqual(result,dict(a=[0,-.2,0],b=[0,.2,0]))
        p['Anchors'][0]['Position'][0]=.01
        with self.assertRaisesRegex(ValueError,'does not lie'):resolve_bindings(p)
        p['Anchors'][0]['Position'][0]=0;p['JointWorkspace']['Joints'][0]['Status']='needs_repair'
        with self.assertRaisesRegex(ValueError,'Review joint'):resolve_bindings(p)
from attachment_contract import release_group,resolve,audit_release


def mate(kind,geometry='point',position=(.3,.6,.9),direction=(0,0,1),**options):
    return dict(Id=kind+geometry,Name=kind,Type=kind,Entities=[dict(ComponentId=o,ComponentReference=o,Kind=geometry,Point=list(position),Axis=list(direction)) for o in ('a','b')],**options)


class JointAuthoringTests(unittest.TestCase):
    def test_sliding_ball_retains_axial_translation_and_three_rotations(self):
        record=mate('COINCIDENT',position=(1,2,3),direction=(0,0,1))
        record['Entities'][1].update(Kind='line',Point=[1,2,-7])
        result=classify([record,copy.deepcopy(record)])
        self.assertEqual(result['Kind'],'point_on_axis')
        self.assertEqual(result['DegreesOfFreedom'],4)
        np.testing.assert_allclose(result['Center'],[1,2,3])
        np.testing.assert_allclose(result['Axis'],[0,0,1])
        record['Entities'][1]['Point'][0]+=.01
        with self.assertRaisesRegex(ValueError,'not on axis'):classify([record])

    def test_point_and_plane_coincidence_have_different_motion(self):
        self.assertEqual(classify([mate('COINCIDENT')])['Kind'],'spherical')
        self.assertEqual(classify([mate('COINCIDENT','plane')])['Kind'],'unresolved')
        self.assertEqual(classify([mate('CONCENTRIC','sphere')])['Kind'],'spherical')
        self.assertEqual(classify([mate('COINCIDENT','sphere')])['Kind'],'unresolved')

    def test_concentric_axis_and_axial_stop_form_hinge(self):
        self.assertEqual(classify([mate('CONCENTRIC','cylinder')])['Kind'],'cylindrical')
        self.assertEqual(classify([mate('CONCENTRIC','cylinder',LockRotation=True)])['Kind'],'prismatic')
        result=classify([mate('CONCENTRIC','cylinder'),mate('COINCIDENT','plane')])
        self.assertEqual(result['Kind'],'revolute');np.testing.assert_allclose(np.abs(result['Axis']),[0,0,1])

    def test_two_point_joints_form_a_hinge_and_third_noncollinear_point_locks(self):
        points=[mate('COINCIDENT',position=p) for p in [(3,2,1),(3,2,2),(4,2,1)]]
        self.assertEqual(classify(points[:2])['Kind'],'revolute')
        self.assertEqual(classify(points)['Kind'],'rigid')
        self.assertEqual(classify([points[0],copy.deepcopy(points[0])])['Kind'],'spherical')

    def test_plane_normal_controls_which_axis_is_restrained(self):
        result=classify([mate('CONCENTRIC','cylinder'),mate('COINCIDENT','plane',direction=(1,0,0))])
        self.assertEqual(result['Kind'],'prismatic')

    def test_scan_preserves_review_only_for_unchanged_constraints(self):
        w=dict(Mates=[mate('COINCIDENT')]);w['Joints']=proposals(w);w['Joints'][0]['Status']='approved'
        self.assertEqual(proposals(w)[0]['Status'],'approved')
        w['Mates'][0]['Entities'][0]['Point'][0]+=.03
        changed=proposals(w)[0];self.assertEqual(changed['Status'],'needs_repair');self.assertEqual(changed['Id'],w['Joints'][0]['Id'])
        w['Mates'][0]['Suppressed']=True
        self.assertEqual(proposals(w)[0]['Status'],'needs_repair')

    def test_repaired_ownership_regroups_mates_without_phantom_missing_joints(self):
        a=mate('CONCENTRIC','cylinder');b=mate('COINCIDENT','plane')
        a['Issue']='unresolved owner';a['Entities']=a['Entities'][:1]
        w=dict(Mates=[a,b]);w['Joints']=proposals(w)
        a.pop('Issue');a['Entities'].append(copy.deepcopy(b['Entities'][1])|dict(Kind='cylinder'))
        repaired=proposals(w)
        self.assertEqual(len(repaired),1);self.assertEqual(repaired[0]['Kind'],'revolute')
        self.assertIsNone(repaired[0]['Issue'])

    def test_missing_or_unreviewed_binding_cannot_generate_coordinates(self):
        p=dict(JointWorkspace=dict(Joints=[dict(Id='j',Status='review',Parent='a',Child='b',Center=[0,0,0])],
             Bindings=[dict(Request='FL.hub',ComponentId='b',JointId='j',Status='resolved')]))
        with self.assertRaisesRegex(ValueError,'Review joint'):resolve_bindings(p)
        p['JointWorkspace']['Joints'][0]['Status']='approved'
        self.assertEqual(resolve_bindings(p)['FL.hub'],[0,0,0])

    def test_release_sets_are_per_panel_and_ids_survive_reordering(self):
        a=dict(Id='bolt1',Template='breakable_fastener');b=dict(Id='bolt2',Template='breakable_fastener')
        self.assertNotEqual(release_group(a,'panel'),release_group(b,'panel'))
        a['ReleaseSet']=b['ReleaseSet']='clips'
        self.assertEqual(release_group(a,'panel'),release_group(b,'panel'))
        self.assertNotEqual(release_group(a,'panel'),release_group(b,'other_panel'))

    def test_release_audit_finds_hidden_braces_and_mesh_ownership(self):
        group=release_group(dict(Id='m',Template='breakable_fastener'),'panel')
        part=dict(nodes=[['id','x','y','z'],['p',0,0,0,dict(group=['panel'])],['f',.006,0,0,dict(group=['frame'])]],
                  beams=[['id1:','id2:'],['p','f',dict(breakGroup=group)]])
        mounts=[dict(id='m',child='panel',parent='frame',group=group,edges=[['p','f']])];owners=dict(p='panel',f='frame')
        self.assertEqual(audit_release(part,mounts,owners,dict(panel=['panel']))['status'],'passed')
        part['torsionbars']=[['a','b','c','d'],['p','f','p','f',{}]]
        with self.assertRaisesRegex(ValueError,'torsionbars'):audit_release(part,mounts,owners)
        del part['torsionbars'];part['nodes'][2][4]['group'].append('panel')
        with self.assertRaisesRegex(ValueError,'mesh'):audit_release(part,mounts,owners,dict(panel=['panel']))

    def test_unowned_native_constraints_are_visible_and_positioning_is_explicit(self):
        workspace=dict(Mates=[dict(Id='bad',Name='Unowned',Type='COINCIDENT',Entities=[],Issue='Missing owner')])
        workspace['Joints']=proposals(workspace)
        self.assertEqual(workspace['Joints'][0]['Kind'],'unresolved')
        workspace['Mates'][0]['PositioningOnly']=True
        self.assertEqual(proposals(workspace)[0]['Status'],'positioning_only')
        workspace['Mates'][0]['PositioningOnly']=False
        self.assertEqual(proposals(workspace)[0]['Status'],'needs_repair')

    def test_archived_native_geometry_produces_expected_motion(self):
        paths=list((ROOT/'tests/fixtures/native-joints').glob('*.json'))
        self.assertEqual(len(paths),3,'Native point, hinge and sliding-rack evidence is required')
        for path in paths:
            evidence=json.loads(path.read_text());workspace=evidence['workspace']
            with self.subTest(fixture=path.name):
                result=proposals(workspace)
                self.assertEqual(len(result),1);self.assertEqual(result[0]['Kind'],evidence['expected_kind'])
                self.assertFalse(result[0].get('Issue'))

    def test_rail_cannot_secretly_hold_a_detached_panel(self):
        part=dict(nodes=[['id','x','y','z'],['p',0,0,0],['a',-1,0,0],['b',1,0,0]],beams=[['a','b']],
                  rails={'guide':{'links:':['a','b']}},slidenodes=[['id:','railName'],['p','guide',{'attached':True}]])
        with self.assertRaisesRegex(ValueError,'slidenodes'):
            audit_release(part,[dict(id='m',child='panel',group='g',edges=[])],dict(p='panel',a='frame',b='frame'))


if __name__=='__main__':unittest.main()
