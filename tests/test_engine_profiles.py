import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from vehicle_drivetrain import generate


class EngineProfileTests(unittest.TestCase):
    def build(self,**kw):
        return generate('cvt_rear_front_output',dict(engine_profile='baja_na_ch440_2026',**kw),['a','b','c'],'d')

    def test_published_net_torque_survives_native_friction_and_units(self):
        part,contract=self.build();engine=part['mainEngine'];curve=dict(engine['torque'][1:])
        # Independently transcribed source endpoints; native engine output
        # subtracts static and angular-velocity-proportional friction.
        for rpm,ftlb in [(2400,18.5),(3000,16.6),(3600,13.5)]:
            net=curve[rpm]-engine['friction']-engine['dynamicFriction']*rpm*math.pi/30
            self.assertAlmostEqual(net,ftlb*1.3558179483314)
        self.assertEqual(engine['idleRPM'],1800)
        self.assertEqual(engine['revLimiterRPM'],3750)
        self.assertEqual(engine['revLimiterSmoothOvershootRPM'],50)
        self.assertEqual(contract['engine_reference']['measured_rpm_range'],[2400,3600])
        self.assertFalse(contract['engine_reference']['idle_mandatory'])
        self.assertTrue(any('clutch engagement begins' in a for a in contract['assumptions']))

    def test_generic_unchanged_and_unsupported_conflicting_inputs_rejected(self):
        generic,_=generate('cvt_rear_drive',{},['a','b','c'],'d')
        self.assertEqual(generic['mainEngine']['idleRPM'],1200)
        for kw in [dict(engine_governor_rpm=4000),dict(engine_governor_rpm=float('nan')),dict(idle_rpm=2500),dict(engine_power_kw=14)]:
            with self.assertRaises(ValueError):self.build(**kw)
        engine=self.build(idle_rpm=1600,engine_governor_rpm=3800)[0]['mainEngine']
        self.assertEqual(engine['idleRPM'],1600)
        self.assertEqual(engine['maxRPM'],3800)

if __name__=='__main__':unittest.main()
