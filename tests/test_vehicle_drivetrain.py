from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from vehicle_drivetrain import generate


class DrivetrainTests(unittest.TestCase):
    def test_unequal_axle_inertias_and_ratios_follow_native_child_array(self):
        from vehicle_drivetrain import configure_carrier
        import math
        for template in ('cvt_rear_front_output','cvt_rear_drive'):
            part,contract=generate(template,dict(rear_reduction=9,front_reduction=6,front_output_ratio=.2),['a','b','c'],'d')
            wheels=dict(FL=.11,FR=.12,RL=.135,RR=.14)
            configure_carrier(part,contract,dict(front=.0004,rear=.001),wheels,{})
            # Native primary/secondary inertia array is alphabetical, while
            # physical output 1 still drives the rear differential.
            output=(.23/1.2**2 if template=='cvt_rear_front_output' else .275)
            inertia=output/(9*3)**2
            self.assertAlmostEqual(contract['clutch_coupling']['native_inertia_kg_m2'],inertia)
            self.assertAlmostEqual(part['clutch']['lockDampRatio']*math.sqrt(part['clutch']['lockSpring']*inertia),
                                   contract['clutch_coupling']['damping_nm_s_rad'])
            if template=='cvt_rear_front_output':
                carrier=next(r[4] for r in part['powertrain'][1:] if r[1]=='rearCarrierTakeoff')
                self.assertEqual(contract['devices']['rearCarrierTakeoff']['inertiaChildren'],['frontOutputGear','rearDifferential'])
                self.assertEqual(contract['devices']['rearDifferential']['inputIndex'],1)
                self.assertAlmostEqual(carrier['lockDampRatio']*math.sqrt(carrier['lockSpring']*.275),
                                       contract['carrier_coupling']['damping_nm_s_rad'])

    def test_locked_carrier_includes_light_housing_recoil_and_engine_capacity(self):
        from vehicle_drivetrain import configure_carrier
        import math
        part,contract=generate('cvt_rear_front_output',{},['a','b','c'],'d')
        configure_carrier(part,contract,{'front':.0004,'rear':.001},{c:.2 for c in ('FL','FR','RL','RR')},{})
        budget=contract['carrier_coupling'];row=next(r[4] for r in part['powertrain'][1:] if r[1]=='rearCarrierTakeoff')
        self.assertLess(budget['step_eigenvalue'],1.)
        self.assertLess(budget['effective_inertia_kg_m2'],.0004)
        self.assertAlmostEqual(2*math.sqrt(row['lockSpring']*row['lockTorque']),budget['maximum_tangent_nm_rad'])
        self.assertAlmostEqual(row['lockDampRatio']*math.sqrt(row['lockSpring']*.4),budget['damping_nm_s_rad'])
        clutch=contract['clutch_coupling']
        self.assertLess(clutch['step_eigenvalue'],1.)
        self.assertLess(clutch['effective_inertia_kg_m2'],clutch['native_inertia_kg_m2']*.01)
        self.assertAlmostEqual(part['clutch']['lockSpring']*2,clutch['maximum_tangent_nm_rad'])
        self.assertAlmostEqual(part['clutch']['lockDampRatio']*math.sqrt(part['clutch']['lockSpring']*clutch['native_inertia_kg_m2']),clutch['damping_nm_s_rad'])
        # Independent semi-implicit two-port perturbation at the worst tangent.
        angle=math.sqrt(row['lockTorque']/row['lockSpring'])*.9;speed=0.;initial=angle
        for _ in range(20000):
            torque=row['lockSpring']*angle*abs(angle)+budget['damping_nm_s_rad']*speed
            speed-=torque/budget['effective_inertia_kg_m2']*.0005;angle+=speed*.0005
            self.assertTrue(math.isfinite(angle));self.assertLess(abs(angle),initial*1.01)
        self.assertLess(abs(angle),initial*.001)

    def test_front_output_takes_power_before_rear_wheel_differential(self):
        part,contract=generate('cvt_rear_front_output',{},['e0','e1','e2'],'c0')
        devices=contract['devices']
        self.assertEqual(devices['frontOutputGear']['inputName'],'rearCarrierTakeoff')
        self.assertEqual(devices['rearDifferential']['inputName'],'rearCarrierTakeoff')
        self.assertEqual(devices['rearCarrierTakeoff']['inputName'],'rearReduction')
        self.assertEqual(contract['rear_total_reduction'],contract['front_total_reduction'])
        self.assertEqual(contract['front_rear_speed_ratio'],1)
        self.assertNotIn('transfercase',devices)
        self.assertEqual(part['gearbox']['oneWayViscousCoef'],0)
        self.assertEqual(part['gearbox']['oneWayViscousTorque'],0)
        self.assertEqual(part['gearbox']['friction'],0)
        import math
        self.assertAlmostEqual(part['gearbox']['dynamicFriction']*3600*math.pi/30,.5)
        self.assertEqual([r for r in part['powertrain'][1:] if r[1]=='rearCarrierTakeoff'][0][4]['splitType'],'locked')
    def test_parking_lock_includes_geared_recoil_and_native_damping_normalization(self):
        from vehicle_drivetrain import configure_carrier
        import math
        for template in ('cvt_rear_front_output','cvt_rear_drive'):
            part,contract=generate(template,dict(rear_reduction=9,front_reduction=6,front_output_ratio=.2),['a','b','c'],'d')
            wheels=dict(FL=.11,FR=.12,RL=.135,RR=.14);housing=dict(front=.0004,rear=.001)
            configure_carrier(part,contract,housing,wheels,{})
            budget=contract['parking_lock'];spring=part['gearbox']['parkLockSpring']
            damp=part['gearbox']['parkLockDampRatio']*math.sqrt(spring*budget['native_output_inertia_kg_m2'])
            self.assertAlmostEqual(damp,budget['damping_nm_s_rad'])
            self.assertLess(budget['effective_inertia_kg_m2'],housing['rear']/9**2)
            self.assertEqual(budget['capacity_nm'],2500)
            self.assertLess(budget['step_eigenvalue'],1.)
            # Independent output-angle perturbation: energy must dissipate with
            # the declared native step, including the much lighter reaction.
            angle=.01;speed=0.;energy=.5*spring*angle**2
            for _ in range(2000):
                speed-=(spring*angle+damp*speed)/budget['effective_inertia_kg_m2']*.0005
                angle+=speed*.0005
                self.assertLessEqual(.5*spring*angle**2+.5*budget['effective_inertia_kg_m2']*speed**2,energy*1.01)
            self.assertLess(abs(angle),1e-9)
    def test_rear_drive_does_not_require_front_drivetrain(self):
        _,contract=generate('cvt_rear_drive',{},['a','b','c'],'d')
        self.assertEqual(contract['driven_wheels'],['RL','RR'])
        self.assertFalse(any('front' in name.lower() for name in contract['devices']))
    def test_ratio_changes_are_explicit(self):
        _,contract=generate('cvt_rear_front_output',{'rear_reduction':9,'front_reduction':6,'front_output_ratio':.2},['a','b','c'],'d')
        self.assertAlmostEqual(contract['front_total_reduction'],10.8)
        self.assertAlmostEqual(contract['front_rear_speed_ratio'],1/1.2)
        with self.assertRaises(ValueError):generate('cvt_rear_drive',{'rear_reduction':0},['a','b','c'],'d')


if __name__=='__main__':unittest.main()
