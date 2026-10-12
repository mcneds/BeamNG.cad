import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from vehicle_templates import TemplateModel,Mechanism
from synthetic_vehicle import recipe
from suspension_loads import ride_reference


class RideReferenceTests(unittest.TestCase):
    def test_sag_and_alignment_share_height_without_moving_cad(self):
        from vehicle_alignment import solve
        model=TemplateModel(recipe('primary'));original={c:{k:v.tolist() for k,v in model.corner_points(c).items()} for c in ('FL','FR')}
        model.data['parameters'].update(level_axle_ride_height=True,ride_sag_m=.03,front_alignment_toe_in_deg=0.)
        alignment=solve(model)
        for corner in ('FL','FR'):
            travel,_,_=ride_reference(model,corner,alignment)
            self.assertAlmostEqual(alignment[corner]['reference_hub_height_m'],model.corner_points(corner)['hub'][2]+travel)
        self.assertEqual({c:{k:v.tolist() for k,v in model.corner_points(c).items()} for c in ('FL','FR')},original)
        model.data['parameters']['front_ride_hub_height_m']=0.
        with self.assertRaisesRegex(ValueError,'not both'):ride_reference(model,'FL',{})

    def test_axle_spring_default_is_opt_in_and_keeps_explicit_auto(self):
        from coilover_springs import settings_for_corner
        roles={'rl_spring_damper':dict(Id='left',CoiloverSpring={'Mode':'dual_rate'}),
               'rr_spring_damper':dict(Id='right',CoiloverSpring=None)}
        self.assertIsNone(settings_for_corner(roles,'RR',{})[0])
        settings,source=settings_for_corner(roles,'RR',{'mirror_missing_coilover_settings':True})
        self.assertEqual(settings,{'Mode':'dual_rate'});self.assertTrue(source['inherited'])
        self.assertIsNone(roles['rr_spring_damper']['CoiloverSpring'])
        roles['rr_spring_damper']['CoiloverSpring']={'Mode':'auto'}
        self.assertEqual(settings_for_corner(roles,'RR',{'mirror_missing_coilover_settings':True})[0],{'Mode':'auto'})

    def test_different_captured_articulation_uses_common_axle_height(self):
        definition=recipe('ball_radius_toe');model=TemplateModel(definition)
        for corner,height in [('FL',.02),('FR',-.02)]:
            _,pose=Mechanism(model,corner).solve(height)
            definition['hardpoints'][corner]={k:v.tolist() for k,v in pose.items()}
        model=TemplateModel(definition);before=copy.deepcopy(definition)
        # An unconstrained mating pose must not silently become loaded ride height.
        self.assertNotIn('level_axle_ride_height',model.data['parameters'])
        heights=[];lengths=[]
        for corner in ('FL','FR'):
            height,extension,kind=ride_reference(model,corner,{})
            _,pose=Mechanism(model,corner).solve(height,extension)
            import numpy as np
            heights.append(pose['hub'][2]);lengths.append(np.linalg.norm(pose['shock_bottom']-pose['shock_top']))
            self.assertEqual(kind,'level_axle_plane')
        self.assertAlmostEqual(*heights,places=8);self.assertAlmostEqual(*lengths,places=8)
        self.assertEqual(definition,before)

    def test_captured_ride_position_requires_explicit_opt_out(self):
        model=TemplateModel(recipe('primary'))
        model.data['parameters']['level_axle_ride_height']=False
        self.assertEqual(ride_reference(model,'FL',{}),(0.,0.,'captured_cad_pose'))

    def test_explicit_out_of_range_height_rejected(self):
        model=TemplateModel(recipe('primary'));model.data['parameters'].update(level_axle_ride_height=True,front_ride_hub_height_m=10)
        with self.assertRaisesRegex(ValueError,'150 mm'):ride_reference(model,'FL',{})

    def test_generated_preload_crossover_and_stops_share_the_new_reference(self):
        from unittest.mock import patch
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        import numpy as np
        def settings(spec,components,moments):
            spec['parameters'].update(level_axle_ride_height=True,mirror_missing_coilover_settings=True)
            for axle,corner in [('front','FL'),('rear','RL')]:
                spec['parameters'][axle+'_ride_hub_height_m']=spec['hardpoints'][corner]['hub'][2]+.01
            for comp in components:
                if comp['MvpRole'].endswith('_spring_damper') and comp['MvpRole']!='rr_spring_damper':
                    comp['CoiloverSpring']=dict(Mode='dual_rate',MainRateNPerM=30000,TenderRateNPerM=15000,CrossoverCompressionM=.01)
        project,frame,spec,cad=fixture('ball_radius_toe',settings)
        with patch('components.read_geometry',side_effect=cad):graph,part,wheels,*_=generate(project,frame,spec)
        for corner,wheel in wheels.items():
            a,b=(wheel['nodes'][k] for k in ('shock_top','shock_bottom'))
            captured=np.linalg.norm(graph.point(a)-graph.point(b));reference=wheel['ride_reference']['reference_shock_length_m']
            rows=[r[-1] for r in part['beams'][1:] if isinstance(r,list) and set(r[:2])=={a,b}]
            spring=next(o for o in rows if o.get('beamType')=='|BOUNDED' and o['beamSpring']>0)
            stop=next(o for o in rows if o.get('beamType')=='|BOUNDED' and o['beamSpring']==0)
            crossover=next(o for o in rows if o.get('beamType')=='|SUPPORT')
            self.assertAlmostEqual(spring['beamSpring'],10000.)
            self.assertAlmostEqual((captured*spring['beamPrecompression']-reference)*spring['beamSpring'],wheel['spring_preload_n'],places=5)
            self.assertAlmostEqual(captured*stop['beamPrecompression'],reference,places=8)
            self.assertAlmostEqual(captured*crossover['beamPrecompression'],reference-.01,places=8)
            self.assertEqual(wheel['coilover_settings_source']['inherited'],corner=='RR')


if __name__=='__main__':unittest.main()
