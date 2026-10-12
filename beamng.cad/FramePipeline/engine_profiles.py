"""Sourced engine operating points, distinct from provisional drivetrain hardware."""
import math

RULES = 'https://www.bajasae.net/cdsweb/gen/DownloadDocument.aspx?DocumentID=f37166e7-ee6a-4994-8fe1-203d3ce51e57'
PERFORMANCE = 'https://www.bajasae.net/cdsweb/gen/DownloadDocument.aspx?DocumentID=b250342f-ea19-46c2-95ea-6deb728ddb7a'
CH440_NET_FTLB = [(2400,18.5),(2600,18.1),(2800,17.4),(3000,16.6),(3200,15.4),(3400,14.5),(3600,13.5)]


def apply(part, contract, parameters):
    profile=parameters.get('engine_profile')
    if not profile:return
    if profile!='baja_na_ch440_2026':raise ValueError('Unknown engine profile: '+str(profile))
    if any(k in parameters for k in ('engine_power_kw','engine_peak_rpm','max_rpm')):
        raise ValueError('CH440 profile replaces generic power/peak/max RPM parameters')
    idle=float(parameters.get('idle_rpm',1800))
    governor=float(parameters.get('engine_governor_rpm',3800))
    if not math.isfinite(idle) or not 500<=idle<2400:raise ValueError('CH440 idle RPM must be finite and below the published performance range')
    if not math.isfinite(governor) or not 3750<=governor<=3800:raise ValueError('Baja NA 2026 governor setting must be 3750 to 3800 RPM')
    engine=part['mainEngine'];conversion=1.3558179483314004
    measured=[(rpm,torque*conversion) for rpm,torque in CH440_NET_FTLB]
    # Below the supplied 2400 RPM point use a provisional flat torque extension.
    # Continue the last measured slope to the governor; neither is dyno evidence.
    slope=(measured[-1][1]-measured[-2][1])/200
    points=[(0,0),(idle,measured[0][1]),*measured,(governor,measured[-1][1]+slope*(governor-3600))]
    # BeamNG's table is gross torque; its native engine subtracts these losses.
    # Compensate exactly once so the full-throttle net curve matches the source.
    engine['torque']=[['rpm','torque']]+[[rpm,net+engine['friction']+engine['dynamicFriction']*rpm*math.pi/30 if rpm else 0] for rpm,net in points]
    engine.update(idleRPM=idle,maxRPM=governor,revLimiterRPM=governor-50,revLimiterType='soft',revLimiterSmoothOvershootRPM=50)
    contract['engine_reference']=dict(profile=profile,model='Kohler/Rehlko CH440 Baja restricted',displacement_cc=429,
        rules=RULES,performance=PERFORMANCE,rule_revision='2026 Revision B, 2026-05-24',
        governor_setting_rpm=governor,governor_allowed_rpm=[3750,3800],soft_limit_start_rpm=governor-50,idle_rpm=idle,
        idle_recommendation_rpm=[1750,1850],idle_mandatory=False,net_torque_nm=measured,
        measured_rpm_range=[2400,3600],physical_governor_qualified=False)
    contract['assumptions'].extend([
        'CH440 net torque uses the SAE-published restricted performance table. Outside 2400-3600 RPM the curve is extrapolated, not measured.',
        'Soft RPM limiting approximates the mechanical governor; throttle fades over the 50 RPM below the selected setting, not above the 3800 RPM rule limit. Transient overspeed remains unqualified.',
        'CH440 identity does not determine CVT weights, clutch engagement, ratios, inertia or losses; those remain separately provisional.'])
    if part['clutch']['engageRPMStart']<=idle:
        contract['assumptions'].append('Provisional clutch engagement begins at or below engine idle; neutral is required at rest until real clutch engagement settings are supplied.')
