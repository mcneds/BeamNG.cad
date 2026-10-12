"""Offline graph checks; analytic fake CAD moments are not native CAD evidence."""
import itertools
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
from synthetic_vehicle import recipe
from vehicle_templates import generate,frame_mounts,frame_mount_plan,wheel_options,Structure,reaction_nodes,wheel_reaction_nodes,brake_reaction_node
from planned_mounts import insert_mounts
from frame_harness.projection import axial_columns
from frame_harness.build import node_table,beam_table


def fixture(variant, customize=None):
    spec=recipe(variant);components=[];moments={};fixed={};halfshafts={};shafts={}
    # These existing tests isolate exact CAD moment fitting. The conditioned
    # export path is exercised separately with its explicit extra-mass account.
    spec.setdefault('parameters',{}).update(loaded_node_mass_policy='preserve_cad',assembled_rigid_conditioning=False,
                                           wishbone_representation='cad_moments',trailing_arm_representation='cad_moments')
    for item in spec['components']:
        owner=item['id'];points=[]
        for shape in item['primitives']:
            if shape['kind'] in ('tube','cylinder'):points.extend([shape['a'],shape['b']])
            else:
                center=np.array(shape['center']);size=np.array(shape['size'])
                points.extend(center+np.array(sign)*np.maximum(size,.003)/2 for sign in itertools.product((-1,1),repeat=3))
        xyz=np.array(points);center=xyz.mean(axis=0);extent=np.maximum(np.ptp(xyz,axis=0),.025)
        mass=0 if item['surface_mass_mode']=='ignore' else 10 if owner=='frame' else 18 if owner.endswith('_wheel') else 3
        inertia=np.diag([extent[1]**2+extent[2]**2,extent[0]**2+extent[2]**2,extent[0]**2+extent[1]**2])*mass/12
        moments[owner]=(mass,center,inertia)
        components.append(dict(Id=owner,MvpRole='panel' if owner.startswith('panel_') else owner,Name=owner,
                               Template='panel' if owner.startswith('panel_') else 'bulk'))
        if owner.endswith('_halfshaft'):
            shape=item['primitives'][0];halfshafts[owner]=dict(corner=owner[:2].upper(),inner=shape['a'],outer=shape['b'],plunge_m=.06)
            continue
        if owner in ('front_propshaft','cvt_output_shaft'):
            shape=item['primitives'][0]
            shafts[owner]=dict(inner_role='front_diff' if owner=='front_propshaft' else 'cvt',
                outer_role='rear_final_drive' if variant!='independent_rear' else 'rear_diff',inner=shape['a'],outer=shape['b'],plunge_m=.03)
            continue
        if owner=='frame' or any(token in owner for token in ('wishbone','upright','trailing_arm','radius_rod','tie_rod','toe_link','spring_damper','wheel')) or not mass:continue
        fixed[owner]=[(center+o).tolist() for o in ([-.02,-.02,0],[.02,-.02,0],[0,.02,0])]
    spec['fixed_mounts']=fixed;spec['halfshafts']=halfshafts;spec['shafts']=shafts
    if customize:customize(spec,components,moments)
    xyz=np.array(list(itertools.product([-.31,.31],[0,1.9],[.24,.66])))
    frame={'slotType':'main','nodes':[['id','posX','posY','posZ']]+[[str(i),*p,dict(nodeWeight=1.25,group=['frame'],collision=True,selfCollision=False)] for i,p in enumerate(xyz)],
           'beams':[['id1:','id2:']]+[[str(i),str(j),dict(beamSpring=150000,beamDamp=40,beamDeform=80000,beamStrength=160000)] for i,j in itertools.combinations(range(8),2)]}
    insert_mounts(frame,frame_mount_plan(spec,components))
    # This fake frame has no CAD calibration step. Give its tiny locator nodes
    # a stable test-only stiffness/damping block before testing assembly.
    for row in frame['beams'][1:]:
        if any(str(n).startswith('mount_') for n in row[:2]):row[2].update(beamSpring=15000,beamDamp=2)
    # Added support paths change the coupled eigenvalue even when each spring
    # is modest. Establish a safe synthetic baseline, as calibration does for
    # real CAD; the tests below exercise added joints without refitting it.
    nodes=node_table(frame);names=list(nodes);beams=beam_table(frame)
    columns,_,_=axial_columns(np.array([nodes[n]['position'] for n in names]),
        [[names.index(b['a']),names.index(b['b'])] for b in beams])
    weighted=columns/np.sqrt(np.repeat([nodes[n]['mass'] for n in names],3))[:,None]
    tangent=np.array([.0005**2*b['spring']+2*.0005*b['damp'] for b in beams])
    factor=min(1.,1.6/np.linalg.eigvalsh((weighted*tangent)@weighted.T)[-1])
    for row in frame['beams'][1:]:
        row[2]['beamSpring']*=factor;row[2]['beamDamp']*=factor
    def cad(comp):return [],moments[comp['Id']],{}
    return {'Components':components},frame,spec,cad


class VehicleTemplateGraphTests(unittest.TestCase):
    def test_rigid_panel_preview_is_explicit_and_does_not_make_release_mounts(self):
        def rigid_panels(spec,components,moments):
            spec['fixed_panel_components']=[v['Id'] for v in components if v['Template']=='panel' and v['Id'] in spec['fixed_mounts']]
        project,frame,spec,cad=fixture('primary',rigid_panels)
        owners=set(spec['fixed_panel_components'])
        for owner in owners:
            self.assertTrue(all(frame['cadMountPatches'][owner+'_'+str(i)]['mode']=='direct' for i in range(len(spec['fixed_mounts'][owner]))))
        with patch.object(c,'read_geometry',side_effect=cad):graph,*_=generate(project,frame,spec)
        self.assertFalse(any(mount['child'] in owners for mount in graph.mounts))
        spec['fixed_panel_components']=['engine']
        with self.assertRaisesRegex(ValueError,'Rigid panel declarations'):frame_mount_plan(spec,project['Components'])

    def test_wrapped_frame_keeps_external_collision_without_internal_panel_contact(self):
        import copy
        _,frame,_,_=fixture('primary')
        frame['nodes'][1][4]['selfCollision']=True
        frame['nodes'][2][4].update(collision=False,staticCollision=False)
        original=copy.deepcopy(frame);graph=Structure(frame)
        self.assertEqual(frame,original)
        self.assertEqual(graph.part['beams'],frame['beams'])
        for name,node in node_table(frame).items():
            actual=graph.nodes[name]
            self.assertFalse(actual['options']['selfCollision'])
            for key in ('collision','staticCollision','nodeWeight'):
                self.assertEqual(actual['options'].get(key),node['options'].get(key))
            self.assertEqual(actual['position'],node['position'])
        self.assertEqual(set(graph.collision_policy['frame_nodes']),set(node_table(frame)))

    def test_brake_reaction_prefers_effective_leverage_without_adding_mass(self):
        from types import SimpleNamespace
        points={'a':np.array([-.075,0,0]),'b':np.array([.075,0,0]),
                'lower_ball':np.array([0,0,-.09]),'upper_ball':np.array([0,.02,.18]),
                'light_tip':np.array([0,0,.5])}
        masses={n:(.001 if n=='light_tip' else 1.) for n in points}
        for sign in (1,-1):
            xyz={n:p*[sign,1,1] for n,p in points.items()}
            graph=SimpleNamespace(groups={'upright':list(xyz)},point=lambda n:xyz[n],
                nodes={n:dict(options=dict(nodeWeight=masses[n])) for n in xyz})
            self.assertEqual(brake_reaction_node(graph,'upright',['a','b']),'upper_ball')
            graph.groups['upright'].reverse()
            self.assertEqual(brake_reaction_node(graph,'upright',['a','b']),'upper_ball')
            self.assertEqual(masses,{n:v['options']['nodeWeight'] for n,v in graph.nodes.items()})

    def test_differential_reaction_levers_reflect_with_each_halfshaft(self):
        from types import SimpleNamespace
        xyz={str(i):np.array(p) for i,p in enumerate(itertools.product((-.1,.1),(-.08,.08),(-.06,.06)))}
        graph=SimpleNamespace(groups={'diff':list(xyz)},point=lambda n:xyz[n],nodes={n:{'options':{'nodeWeight':1.}} for n in xyz})
        reactions={side:wheel_reaction_nodes(graph,'diff',side) for side in (-1,1)}
        for key in ('torqueCoupling','torqueArm','torqueArm2'):
            np.testing.assert_allclose(xyz[reactions[-1][key]]*[-1,1,1],xyz[reactions[1][key]])
        graph.groups['diff'].reverse()
        self.assertEqual(wheel_reaction_nodes(graph,'diff',-1),reactions[-1])

    def test_differential_reaction_uses_complete_triangle_inertia(self):
        from types import SimpleNamespace
        from vehicle_templates import reaction_inertia
        # A heavier axis pair wins the old pair-only proxy, but leaves a much
        # weaker reaction lever. These five points admit a fourfold stronger
        # triangle with exactly the same positions and node masses.
        xyz={'a':np.array([-.075,.06,-.05]),'b':np.array([.075,.06,-.05]),
             'c':np.array([-.0525,0,0]),'d':np.array([.0525,0,0]),'e':np.array([0,0,.035])}
        masses=dict(a=.40408247,b=.40408247,c=.9296399,d=.9296399,e=1.7701492)
        graph=SimpleNamespace(groups={'diff':list(xyz)},point=lambda n:xyz[n],
            nodes={n:dict(options=dict(nodeWeight=masses[n])) for n in xyz})
        expected=reaction_inertia(graph,dict(torqueCoupling='a',torqueArm='e',torqueArm2='b'))
        for sign in (-1,1):
            chosen=wheel_reaction_nodes(graph,'diff',sign)
            self.assertAlmostEqual(reaction_inertia(graph,chosen),expected)
            graph.groups['diff'].reverse()
            self.assertEqual(wheel_reaction_nodes(graph,'diff',sign),chosen)
        self.assertEqual(masses,{n:v['options']['nodeWeight'] for n,v in graph.nodes.items()})

    def test_experimental_support_preserves_housing_moments_shell_and_frame(self):
        import copy,tempfile
        mass=14.13;center=np.array([0.,1.9,.34]);covariance=np.diag(np.array([.15,.12,.1])**2/12)
        tensor=mass*(np.trace(covariance)*np.eye(3)-covariance)
        points=center+np.vstack((np.eye(3),-np.eye(3)))*np.sqrt(3*np.diag(covariance))
        shell=dict(nodes=[['id','posX','posY','posZ']]+[['diff_'+str(i),*p,dict(nodeWeight=mass/6,collision=True)] for i,p in enumerate(points)],
            beams=[['id1:','id2:']],triangles=[['id1:','id2:','id3:'],['diff_0','diff_1','diff_2']])
        frame=dict(nodes=[['id','posX','posY','posZ'],['frame',0,0,0,dict(nodeWeight=1)]],beams=[['id1:','id2:']])
        graph=Structure(frame);before=copy.deepcopy(graph.nodes['frame'])
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'generate_component',return_value=(copy.deepcopy(shell),{'mass':{'accepted':True}})),patch.object(c,'read_geometry',return_value=([],(mass,center,tensor),None)):
            graph.geometry_component(dict(Id='diff',Name='Diff',MvpRole='rear_diff',_ExperimentalReactionSupport=True),[],temporary,None)
        self.assertEqual(graph.nodes['frame'],before)
        self.assertEqual(graph.part['triangles'],shell['triangles'])
        for row in shell['nodes'][1:]:
            self.assertEqual(graph.nodes[row[0]]['position'],row[1:4]);self.assertTrue(graph.nodes[row[0]]['options']['collision'])
        for sign in (-1,1):
            reaction=wheel_reaction_nodes(graph,'diff',sign)
            self.assertGreaterEqual(min(graph.nodes[n]['options']['nodeWeight'] for n in reaction.values()),2)
            a,b=graph.point(reaction['torqueCoupling']),graph.point(reaction['torqueArm2'])
            self.assertGreater((b[0]-a[0])*sign,0)
        names=graph.groups['diff'];weights=np.array([graph.mass_allocations['diff'][n] for n in names]);xyz=np.array([graph.point(n) for n in names])
        self.assertAlmostEqual(weights.sum(),mass);np.testing.assert_allclose(weights@xyz/mass,center,atol=1e-12)
        xyz-=center
        actual=sum(m*(p@p*np.eye(3)-np.outer(p,p)) for m,p in zip(weights,xyz))
        np.testing.assert_allclose(actual,tensor,atol=1e-12)

    def test_engine_reaction_axis_does_not_follow_arbitrary_opposite_box_corners(self):
        from types import SimpleNamespace
        xyz={str(i):np.array(p) for i,p in enumerate(itertools.product((-.11,.11),(-.08,.08),(-.065,.065)))}
        xyz['cvt']=np.array([.23,0,0]);names=[n for n in xyz if n!='cvt']
        graph=SimpleNamespace(groups={'engine':names,'cvt':['cvt']},point=lambda n:xyz[n],nodes={n:{'options':{'nodeWeight':1.}} for n in xyz})
        first,second,arm=reaction_nodes(graph,'engine','cvt');axis=xyz[second]-xyz[first]
        np.testing.assert_allclose(axis/np.linalg.norm(axis),[1,0,0],atol=1e-12)
        self.assertGreater(np.linalg.norm(np.cross(axis,xyz[arm]-xyz[first])),.01)
        graph.groups['engine']=names[::-1]
        self.assertEqual(reaction_nodes(graph,'engine','cvt'),[first,second,arm])

    def test_powertrain_housing_keeps_cad_mass_and_colliders_with_rigid_load_paths(self):
        import copy,tempfile
        project,frame,spec,cad=fixture('primary');graph=Structure(frame)
        points=np.array(list(itertools.product((-.1,.1),repeat=3)))
        part=dict(nodes=[['id','posX','posY','posZ']]+[['diff_'+str(i),*p,dict(nodeWeight=.1,collision=True)] for i,p in enumerate(points)],
                  beams=[['id1:','id2:']],triangles=[['id1:','id2:','id3:'],['diff_0','diff_1','diff_2']])
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'generate_component',return_value=(copy.deepcopy(part),{'mass':{'accepted':True}})),patch.object(c,'read_geometry',return_value=([],None,None)):
            graph.geometry_component(dict(Id='diff',Name='Diff',MvpRole='front_diff'),[],temporary,None)
        for row in part['nodes'][1:]:
            self.assertEqual(graph.nodes[row[0]]['position'],row[1:4]);self.assertEqual(graph.nodes[row[0]]['mass'],.1)
        self.assertEqual(graph.part['triangles'],part['triangles'])
        self.assertEqual(len(graph.spectral_edges),28)
        self.assertEqual(len(graph.part['torsionbars']),1)
        from frame_harness.projection import axial_columns
        stiffness=np.zeros((24,24))
        index={row[0]:i for i,row in enumerate(part['nodes'][1:])}
        for a,b,options in graph.new_beams:
            column,_,_=axial_columns(points,[(index[a],index[b])])
            stiffness+=options['beamSpring']*column@column.T
        self.assertEqual(sum(np.linalg.eigvalsh(stiffness)<1e-4),6)

    def test_compact_solid_uses_rigid_load_paths_without_a_powertrain_role(self):
        import copy,tempfile
        points=np.array(list(itertools.product((-.03,.03),(-.035,.035),(-.02,.02))))
        part=dict(nodes=[['id','posX','posY','posZ']]+[['solid_'+str(i),*p,dict(nodeWeight=.1,collision=True)] for i,p in enumerate(points)],
                  beams=[['id1:','id2:']],triangles=[['id1:','id2:','id3:'],['solid_0','solid_1','solid_2']])
        report={'mass':{'accepted':True},'settings':{'wrap':{'selected_method':'exact_convex_solid'}}}
        _,frame,_,_=fixture('primary')
        for template,method,expected in [('bulk','exact_convex_solid',True),('panel','exact_convex_solid',False),('bulk','alpha_wrap',False)]:
            with self.subTest(template=template,method=method):
                graph=Structure(copy.deepcopy(frame));evidence=copy.deepcopy(report);evidence['settings']['wrap']['selected_method']=method
                with tempfile.TemporaryDirectory() as temporary,patch.object(c,'generate_component',return_value=(copy.deepcopy(part),evidence)),patch.object(c,'read_geometry',return_value=([],None,None)):
                    graph.geometry_component(dict(Id='solid',Name='Solid',MvpRole='accessory',Template=template),[],temporary,None)
                self.assertEqual(bool(graph.spectral_edges),expected)
                self.assertEqual(graph.part['triangles'],part['triangles'])
                self.assertAlmostEqual(sum(graph.mass_allocations['solid'].values()),.8)
                for row in part['nodes'][1:]:self.assertEqual(graph.nodes[row[0]]['position'],row[1:4])

    def test_loaded_housing_mass_fit_preserves_independent_solid_box_moments(self):
        import copy,tempfile
        from frame_harness.calibration import fit_masses
        half=np.array([.3,.15,.1]);total=12.;center=np.zeros(3)
        covariance=np.diag(half**2/3);inertia=total*(np.trace(covariance)*np.eye(3)-covariance)
        mounts=np.array([[-.15,-.08,-.1],[.15,-.08,-.1],[0,.08,-.1]])
        xyz=np.vstack((np.array(list(itertools.product((-1,1),repeat=3)))*half,
                       np.zeros((1,3)),np.eye(3)*half,-np.eye(3)*half,mounts))
        names=['diff_'+str(i) for i in range(len(xyz)-3)]+['diff_mount_'+str(i) for i in range(3)]
        original,_=fit_masses(xyz,total,center,inertia)
        part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*p,dict(nodeWeight=float(w),collision=True)] for n,p,w in zip(names,xyz,original)],
                  beams=[['id1:','id2:']],triangles=[['id1:','id2:','id3:'],names[:3]])
        graph=Structure(dict(nodes=[['id','posX','posY','posZ']],beams=[['id1:','id2:']]))
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'generate_component',return_value=(copy.deepcopy(part),{'mass':{'accepted':True}})),patch.object(c,'read_geometry',return_value=([],(total,center,inertia),{})):
            graph.geometry_component(dict(Id='diff',Name='Diff',MvpRole='front_diff'),mounts.tolist(),temporary,None)
        weights=np.array([graph.nodes[n]['options']['nodeWeight'] for n in names])
        self.assertGreater(min(weights[-3:]),min(original[-3:]))
        self.assertGreater(min(weights),0);self.assertAlmostEqual(sum(weights),total,places=10)
        np.testing.assert_allclose(weights@xyz/total,center,atol=1e-10)
        actual=sum(w*(p@p*np.eye(3)-np.outer(p,p)) for w,p in zip(weights,xyz))
        np.testing.assert_allclose(actual,inertia,atol=1e-10)
        self.assertEqual(graph.part['triangles'],part['triangles'])
        np.testing.assert_array_equal([graph.nodes[n]['position'] for n in names],xyz)

    def test_joint_budget_preserves_spectrally_designed_rigid_block(self):
        project,frame,spec,cad=fixture('primary');graph=Structure(frame)
        component=next(v for v in project['Components'] if v['Id']=='fl_upright')
        p=spec['hardpoints']['FL'];required={k:p[k] for k in ('upper_ball','lower_ball','tie_outer')}
        with patch.object(c,'read_geometry',side_effect=cad):names,_=graph.rigid_component(component,required)
        before={(a,b):dict(options) for a,b,options in graph.new_beams}
        for child in names:
            for parent in graph.frame_ids[:4]:graph.beam(parent,child,beamSpring=2000000)
        part=graph.finish()
        after={(row[0],row[1]):row[2] for row in part['beams'][1:] if isinstance(row,list)}
        for edge,options in before.items():self.assertEqual(after[edge],options)
        self.assertTrue(any(after[(parent,names[0])]['beamSpring']<2000000 for parent in graph.frame_ids[:4]))
        self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.2)

    def test_braking_force_budget_tracks_vehicle_mass_and_front_bias(self):
        for mass in (150.,900.):
            front=wheel_options(10.,True,{},mass);rear=wheel_options(10.,False,{},mass)
            torque=2*(front['brakeTorque']+rear['brakeTorque'])
            self.assertAlmostEqual(torque/.28,mass*9.81)
            self.assertAlmostEqual(front['brakeTorque']/(front['brakeTorque']+rear['brakeTorque']),.6)
            self.assertTrue(front['collision']);self.assertFalse(front['selfCollision'])
    def test_tire_resolution_preserves_cad_mass_and_radial_inertia(self):
        for rays in (12,16,24,32):
            options=wheel_options(17.4,True,dict(tire_rays=rays),280.)
            mass=2*rays*(options['hubNodeWeight']+options['nodeWeight'])
            inertia=2*rays*(options['hubNodeWeight']*options['hubRadius']**2+options['nodeWeight']*options['radius']**2)
            self.assertAlmostEqual(mass,17.4)
            self.assertAlmostEqual(inertia,17.4*(.45*.16**2+.55*.28**2))
        for rays in (True,8,16.5,33):
            with self.assertRaises(ValueError):wheel_options(17.4,True,dict(tire_rays=rays),280.)
    def test_native_recipe_declarations_generate_distinct_parent_child_mounts(self):
        for variant in ('primary','independent_rear'):
            project,frame,spec,cad=fixture(variant)
            # A declared static camber/toe must reach the native axle as well
            # as the ideal linkage model, for trailing arms and uprights.
            tilted='RL' if variant=='primary' else 'FR'
            spec['hardpoints'][tilted]['hub_axis'][1]+=.001
            spec['hardpoints'][tilted]['hub_axis'][2]+=.002
            with self.subTest(variant=variant),patch.object(c,'read_geometry',side_effect=cad):
                graph,part,wheels,checks,contract,meshes,bindings=generate(project,frame,spec)
                self.assertEqual(len(wheels),4)
                for name,patch_data in frame['cadMountPatches'].items():
                    self.assertEqual(len(patch_data['parents']),{'short':3,'joint':1,'direct':0}[patch_data['mode']])
                for corner in wheels:
                    row=next(r for r in part['pressureWheels'][1:] if r[0]==corner)
                    start,end=map(graph.point,row[3:5]);hub=np.array(spec['hardpoints'][corner]['hub'])
                    self.assertGreater(abs(start[0]),abs(end[0]))
                    np.testing.assert_allclose((start+end)/2,hub,atol=1e-9)
                    axis=np.array(spec['hardpoints'][corner]['hub_axis'])-hub
                    np.testing.assert_allclose(np.cross(end-start,axis),0,atol=1e-12)
                    self.assertAlmostEqual(np.linalg.norm(end-start),.15)
                    self.assertGreater((end[0]-start[0])*row[7],0)
                    self.assertEqual(wheels[corner]['tire_contract']['axle_nodes'],row[3:5])
                    self.assertEqual(checks[corner]['degrees_of_freedom'],1)
                    self.assertGreater(wheels[corner]['spring_n_m'],0)
                    carrier=corner.lower()+('_upright' if wheels[corner]['template']=='double_wishbone' else '_trailing_arm')
                    allocation=graph.mass_allocations[corner.lower()+'_wheel']
                    if any(allocation.values()):
                        budget=graph.reports[carrier]['rigidity_mass_budget']
                        self.assertAlmostEqual(budget['additional_mass_kg'],sum(allocation.values()))
                        self.assertAlmostEqual(budget['component_mass_kg'],graph.reports[carrier]['target_mass_kg'])
                        for name,mass in budget['assembled_node_masses_kg'].items():
                            self.assertAlmostEqual(mass,graph.nodes[name]['options']['nodeWeight'])
                    sprung=wheels[corner]['effective_sprung_mass_kg'];ratio=wheels[corner]['motion_ratio']
                    self.assertGreater(sprung,0)
                    self.assertGreater(wheels[corner]['effective_unsprung_mass_kg'],wheels[corner]['wheel_mass_kg'])
                    self.assertAlmostEqual(wheels[corner]['spring_preload_n']*ratio,9.81*sprung)
                    self.assertAlmostEqual(wheels[corner]['spring_n_m']*ratio**2/sprung,(2*np.pi*1.5)**2)
                    self.assertAlmostEqual(wheels[corner]['damper_ns_m']*ratio**2/(2*sprung*2*np.pi*1.5),.65)
                    eyes=[wheels[corner]['nodes'][key] for key in ('shock_top','shock_bottom')]
                    length=np.linalg.norm(graph.point(eyes[0])-graph.point(eyes[1]))
                    coilover=[r[-1] for r in part['beams'][1:] if isinstance(r,list) and set(r[:2])==set(eyes)]
                    force=0.;damping=0.
                    for options in coilover:
                        rest=length*options.get('beamPrecompression',1)
                        force+=options['beamSpring']*(rest-length);damping+=options['beamDamp']
                        if options.get('beamLimitSpring',0):
                            # Stops must be inactive at design height and engage
                            # at physical travel limits regardless of preload.
                            self.assertGreater(length,rest-options['shortBoundRange'])
                            self.assertLess(length,rest+options['longBoundRange'])
                            self.assertAlmostEqual(rest-options['shortBoundRange'],length-.08*checks[corner]['motion_ratio'])
                            self.assertAlmostEqual(rest+options['longBoundRange'],length+.08*checks[corner]['motion_ratio'])
                    self.assertAlmostEqual(force,wheels[corner]['spring_preload_n'])
                    self.assertAlmostEqual(damping,wheels[corner]['damper_ns_m'])
                    reaction=wheels[corner]['reaction_nodes']
                    self.assertEqual(reaction['nodeArm'],wheels[corner]['brake_reaction_node'])
                    if corner in contract['driven_wheels']:
                        owner=wheels[corner]['drive_reaction_owner']
                        triangle=[reaction[key] for key in ('torqueCoupling','torqueArm2','torqueArm')]
                        self.assertTrue(set(triangle)<=set(graph.groups[owner]))
                        a,b,cpoint=[graph.point(n) for n in triangle]
                        self.assertGreater((b[0]-a[0])*row[7],0);self.assertGreater(np.linalg.norm(np.cross(b-a,cpoint-a)),.0001)
                        row=next(r for r in part['pressureWheels'][1:] if r[0]==corner)
                        for key,node in reaction.items():
                            if key!='nodeArm':self.assertEqual(row[-1][key+':'],node)
                    else:self.assertEqual(set(reaction),{'nodeArm'})
                for name in node_table(frame):
                    self.assertEqual(graph.mass_allocations['frame'][name],node_table(frame)[name]['options']['nodeWeight'])
                    self.assertAlmostEqual(node_table(part)[name]['options']['nodeWeight'],sum(v.get(name,0) for v in graph.mass_allocations.values()))
                self.assertEqual(sum(row[-1].get('beamType')=='|BOUNDED' for row in part['beams'][1:] if isinstance(row,list)),8+len(spec['halfshafts'])+len(spec['shafts']))
                self.assertEqual(len(part['hydros']),3)
                for corner in ('FL','FR'):
                    group=corner.lower()+'_tie_rod_structure'
                    supports=[n for n in graph.groups[graph.frame_owner] if group in graph.nodes[n]['options']['group']]
                    self.assertGreaterEqual(len(supports),3)
                    delta=np.array([graph.point(n)-np.array(spec['hardpoints'][corner]['tie_inner']) for n in supports])
                    self.assertEqual(np.linalg.matrix_rank(delta,tol=1e-8),3)
                    for arm in ('upper','lower'):
                        ball=corner+'_'+arm+'_ball';wishbone=corner.lower()+'_'+arm+'_wishbone';upright=corner.lower()+'_upright'
                        self.assertIn(ball,graph.mass_allocations[wishbone]);self.assertIn(ball,graph.mass_allocations[upright])
                        expected=sum(v.get(ball,0) for v in graph.mass_allocations.values())
                        self.assertAlmostEqual(node_table(part)[ball]['options']['nodeWeight'],expected)
                        joint=next(j for j in graph.joints if j['id']==corner+'_'+arm+'_ball_joint')
                        self.assertEqual(joint['kind'],'shared_ball');self.assertEqual(joint['nodes'],[ball])
                        self.assertIn(wishbone+'_structure',graph.nodes[ball]['options']['group'])
                        self.assertIn(upright+'_structure',graph.nodes[ball]['options']['group'])
                for owner,declaration in (spec['halfshafts']|spec['shafts']).items():
                    self.assertNotIn(owner,spec['fixed_mounts'])
                    allocation=graph.mass_allocations[owner]
                    self.assertEqual(sum(allocation.values()),3)
                    parents={j['parent'] for j in graph.joints if j['id'] in (owner+'_inner',owner+'_outer')}
                    self.assertNotIn('frame',parents)
                    self.assertEqual(len(parents),2)
                # Moving mass from the wheel rings onto their axle endpoints
                # must not change corner balance or the design-height preload.
                import copy
                from suspension_loads import configure
                from vehicle_templates import TemplateModel
                expected=copy.deepcopy(wheels)
                for corner in wheels:
                    allocation=graph.mass_allocations.pop(corner.lower()+'_wheel')
                    for name,mass in allocation.items():graph.nodes[name]['options']['nodeWeight']-=mass
                    wheels[corner]['wheel_mass_kg']+=sum(allocation.values())
                roles={v['MvpRole']:v for v in project['Components']}
                options={corner:dict(spring={},damper={'shortBoundRange':.08*checks[corner]['motion_ratio']}) for corner in wheels}
                configure(graph,wheels,roles,TemplateModel(spec),spec,options)
                for corner in wheels:
                    for key in ('static_support_mass_kg','effective_unsprung_mass_kg','effective_sprung_mass_kg',
                                'spring_n_m','damper_ns_m','spring_preload_n'):
                        self.assertAlmostEqual(wheels[corner][key],expected[corner][key],places=5,msg=corner+'/'+key)
    def test_changed_mounts_require_fresh_frame_calibration(self):
        project,frame,spec,cad=fixture('primary');spec['hardpoints']['RL']['hinge_inner'][0]+=.02
        with patch.object(c,'read_geometry',side_effect=cad),self.assertRaisesRegex(ValueError,'Mount moved'):
            generate(project,frame,spec)


if __name__=='__main__':unittest.main()
