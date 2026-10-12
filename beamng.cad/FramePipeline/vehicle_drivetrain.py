"""Native CVT drivetrains with explicit physical topology and test contracts."""
from __future__ import annotations
import math


def carrier_native_inertias(contract,wheel_inertias):
    """BeamNG builds children alphabetically, not by their input port.

    splitShaft.calculateInertia indexes that array with primaryOutputID. Its
    torque/velocity updates use actual ports. Keep physical recoil budgets
    separate from this native damping-ratio normalization, and verify both.
    """
    ratio=contract['front_total_reduction']/contract['rear_total_reduction']
    branches={'rearDifferential':sum(wheel_inertias[c] for c in ('RL','RR')),
              'frontOutputGear':sum(wheel_inertias[c] for c in ('FL','FR'))/ratio**2}
    children=sorted(branches)
    contract['devices']['rearCarrierTakeoff']['inertiaChildren']=children
    return tuple(branches[name] for name in children)


def configure_carrier(part,contract,reaction_inertias,wheel_inertias,parameters):
    """Budget native splitShaft's quadratic lock against housing recoil too.

    Its built-in wheel-only inertia misses the counter-torque impulse on small
    housing nodes. At the torque cap, dT/dtheta = 2 sqrt(lockSpring * capacity).
    Bound that worst tangent and damping at the standard physics step.
    """
    configure_clutch(part,contract,reaction_inertias,wheel_inertias,parameters)
    configure_park(part,contract,reaction_inertias,wheel_inertias,parameters)
    if contract['template']!='cvt_rear_front_output':return
    ratio=contract['front_total_reduction']/contract['rear_total_reduction']
    front=1/sum(1/wheel_inertias[c] for c in ('FL','FR'))*4
    rear=1/sum(1/wheel_inertias[c] for c in ('RL','RR'))*4
    effective=1/(1/rear+1/reaction_inertias['rear']+ratio**2*(1/front+1/reaction_inertias['front']))
    frequency=float(parameters.get('carrier_frequency_hz',120.));zeta=float(parameters.get('carrier_damping_ratio',.3))
    if not 0<frequency<=150 or not 0<zeta<=.5:raise ValueError('Carrier coupling frequency/damping exceed the supported numerical budget')
    peak=max(row[1] for row in part['mainEngine']['torque'][1:])
    capacity=peak*part['gearbox']['maxGearRatio']*contract['rear_total_reduction']*1.25
    tangent=effective*(2*math.pi*frequency)**2
    spring=tangent*tangent/(4*capacity);damp=2*zeta*effective*(2*math.pi*frequency)
    # Native normalization follows child-array order, unlike the physical ports.
    _,secondary=carrier_native_inertias(contract,wheel_inertias)
    for row in part['powertrain'][1:]:
        if row[1]=='rearCarrierTakeoff':row[4].update(lockTorque=capacity,lockSpring=spring,lockDampRatio=damp/math.sqrt(spring*secondary))
    dt=.0005
    contract['carrier_coupling']=dict(effective_inertia_kg_m2=effective,reaction_inertias_kg_m2=reaction_inertias,
        wheel_inertias_kg_m2=wheel_inertias,secondary_inertia_kg_m2=secondary,capacity_nm=capacity,
        maximum_tangent_nm_rad=tangent,lock_spring_nm_rad2=spring,damping_nm_s_rad=damp,
        maximum_virtual_twist_rad=math.sqrt(capacity/spring),frequency_limit_hz=frequency,
        step_seconds=dt,step_eigenvalue=(dt*dt*tangent+2*dt*damp)/effective)
    contract['assumptions'].append('Carrier coupling is a timestep-limited virtual torsional connection including housing recoil; shaft twist and rupture are not physically calibrated.')


def configure_clutch(part,contract,reaction_inertias,wheel_inertias,parameters):
    """Apply the same recoil-aware bound at the clutch through maximum gearing."""
    gearing=contract['rear_total_reduction']*part['gearbox']['maxGearRatio']
    rear=4/sum(1/wheel_inertias[c] for c in ('RL','RR'))
    effective=1/(1/part['mainEngine']['inertia']+gearing**2*(1/rear+1/reaction_inertias['rear']))
    frequency=float(parameters.get('clutch_frequency_hz',120.));zeta=float(parameters.get('clutch_damping_ratio',.3))
    if not 0<frequency<=150 or not 0<zeta<=.5:raise ValueError('Clutch frequency/damping exceed the supported numerical budget')
    tangent=effective*(2*math.pi*frequency)**2;spring=tangent/2
    # Native centrifugalClutch becomes linear beyond one radian; the largest
    # derivative is 2*spring just before that transition, independent of capacity.
    native_output=(carrier_native_inertias(contract,wheel_inertias)[0] if contract['template']=='cvt_rear_front_output'
                   else sum(wheel_inertias[c] for c in ('RL','RR')))
    native_inertia=min(native_output/gearing**2,part['mainEngine']['inertia']*.5)
    damp=2*zeta*effective*2*math.pi*frequency
    part['clutch'].update(lockSpring=spring,lockDampRatio=damp/math.sqrt(spring*native_inertia))
    dt=.0005
    contract['clutch_coupling']=dict(effective_inertia_kg_m2=effective,native_inertia_kg_m2=native_inertia,
        maximum_tangent_nm_rad=tangent,lock_spring_nm_rad2=spring,damping_nm_s_rad=damp,
        maximum_gearing=gearing,frequency_limit_hz=frequency,step_seconds=dt,
        step_eigenvalue=(dt*dt*tangent+2*dt*damp)/effective)
    contract['assumptions'].append('Clutch numerical compliance includes geared housing recoil; engagement RPM and torque capacity are unchanged, but physical clutch twist/heat remain uncalibrated.')


def configure_park(part,contract,reaction_inertias,wheel_inertias,parameters):
    """Bound CVT output parking-lock stiffness/damping including housing recoil.

    Native CVT defaults normalize against rotating wheel inertia alone. Torque
    reaches much lighter housing reaction nodes through the final reduction,
    making that damping unstable even when the car is simply parked.
    """
    inverse=0.
    for axle,corners in (('rear',('RL','RR')),('front',('FL','FR'))):
        if axle=='front' and contract['template']!='cvt_rear_front_output':continue
        wheels=4/sum(1/wheel_inertias[c] for c in corners)
        ratio=contract[axle+'_total_reduction']
        inverse+=ratio**2*(1/wheels+1/reaction_inertias[axle])
    effective=1/inverse
    frequency=float(parameters.get('park_frequency_hz',120.));zeta=float(parameters.get('park_damping_ratio',.3))
    if not 0<frequency<=150 or not 0<zeta<=.5:raise ValueError('Parking lock frequency/damping exceed the supported numerical budget')
    spring=effective*(2*math.pi*frequency)**2;damp=2*zeta*effective*2*math.pi*frequency
    native_output=(carrier_native_inertias(contract,wheel_inertias)[0] if contract['template']=='cvt_rear_front_output'
                   else sum(wheel_inertias[c] for c in ('RL','RR')))/contract['rear_total_reduction']**2
    part['gearbox'].update(parkLockSpring=spring,parkLockDampRatio=damp/math.sqrt(spring*native_output))
    dt=.0005
    contract['parking_lock']=dict(effective_inertia_kg_m2=effective,native_output_inertia_kg_m2=native_output,
        spring_nm_rad=spring,damping_nm_s_rad=damp,capacity_nm=part['gearbox']['parkLockTorque'],
        frequency_limit_hz=frequency,step_seconds=dt,step_eigenvalue=(dt*dt*spring+2*dt*damp)/effective)
    contract['assumptions'].append('Parking lock is a numerical torsional connection including geared housing recoil; real pawl stiffness, slope-holding deflection and rupture remain uncalibrated.')


def generate(template, parameters, engine_nodes, cvt_node):
    if template not in ('cvt_rear_front_output','cvt_rear_drive'):raise ValueError('Unsupported drivetrain template')
    rear=float(parameters.get('rear_reduction',8));front=float(parameters.get('front_reduction',8))
    output=float(parameters.get('front_output_ratio',1/8))
    if any(not math.isfinite(value) or value<=0 for value in (rear,front,output)):raise ValueError('Gear ratios must be finite and positive')
    # The rear housing contains the reduction and carrier takeoff. The takeoff
    # is upstream of the rear left/right differential, never a rear halfshaft.
    rows=[['type','name','inputName','inputIndex'],['combustionEngine','mainEngine','dummy',0],
          ['centrifugalClutch','clutch','mainEngine',1],['cvtGearbox','gearbox','clutch',1],
          ['shaft','rearReduction','gearbox',1,{'gearRatio':rear}]]
    parent='rearReduction'
    if template=='cvt_rear_front_output':
        rows += [['splitShaft','rearCarrierTakeoff','rearReduction',1,{'splitType':'locked','primaryOutputID':1,'lockTorque':4000,'defaultVirtualInertia':10}],
                 ['shaft','frontOutputGear','rearCarrierTakeoff',2,{'gearRatio':output}],
                 ['shaft','frontPropshaft','frontOutputGear',1],
                 ['differential','frontDifferential','frontPropshaft',1,{'diffType':'open','gearRatio':front}]]
        parent='rearCarrierTakeoff'
        for index,corner in enumerate(('FL','FR'),1):rows.append(['shaft','axle'+corner,'frontDifferential',index,{'connectedWheel':corner}])
    rows.append(['differential','rearDifferential',parent,1,{'diffType':'open','gearRatio':1}])
    for index,corner in enumerate(('RL','RR'),1):rows.append(['shaft','axle'+corner,'rearDifferential',index,{'connectedWheel':corner}])
    peak_rpm=float(parameters.get('engine_peak_rpm',3600));power=float(parameters.get('engine_power_kw',10));torque=power*1000/(peak_rpm*math.pi/30)
    cvt_loss=float(parameters.get('cvt_loss_torque_nm',.5))
    if not math.isfinite(cvt_loss) or cvt_loss<0:raise ValueError('CVT loss torque must be finite and nonnegative')
    idle=float(parameters.get('idle_rpm',1200));maximum=float(parameters.get('max_rpm',4000))
    part={'powertrain':rows,'controller':[['fileName'],['vehicleController',{}]],
          'mainEngine':dict(torque=[['rpm','torque'],[0,0],[idle,torque*.8],[peak_rpm,torque],[maximum,torque*.7]],
                            idleRPM=idle,maxRPM=maximum,inertia=.15,friction=1.5,dynamicFriction=.005,engineBrakeTorque=8,
                            burnEfficiency=.3,energyStorage='fuelTank',requiredEnergyType='gasoline',thermalsEnabled=False,
                            engineNode=engine_nodes[0],starterTorque=35,starterMaxRPM=1500,**{'torqueReactionNodes:':engine_nodes[:3]}),
          'clutch':dict(engageRPMStart=1600,engageRPMEnd=2300,lockTorque=torque*3,thermalsEnabled=False),
          # This centrifugal-clutch CVT template has no anti-rollback bearing.
          # BeamNG's default one-way viscous coupling otherwise feeds a large
          # unrequested holding torque through the final reduction at idle.
          'gearbox':dict(minGearRatio=float(parameters.get('cvt_min',.8)),maxGearRatio=float(parameters.get('cvt_max',3)),friction=0,
                        dynamicFriction=cvt_loss/(peak_rpm*math.pi/30),
                        oneWayViscousCoef=0,oneWayViscousTorque=0,parkLockTorque=2500,**{'gearboxNode:':[cvt_node]}),
          'vehicleController':dict(automaticModes='PRND',cvtHighRPM=peak_rpm,cvtLowRPM=2300,cvtAggression=.2,cvtGearRatioSmoothingIn=3,cvtGearRatioSmoothingOut=1,cvtTargetAVSmoothingIn=1,cvtTargetAVSmoothingOut=1),
          'energyStorage':[['type','name'],['fuelTank','fuelTank']],
          'fuelTank':dict(energyType='gasoline',fuelCapacity=5,startingFuelCapacity=5,fuel=dict(fuelLiquidDensity=.75))}
    devices={row[1]:dict(type=row[0],inputName=row[2],inputIndex=row[3],**({'gearRatio':row[4]['gearRatio']} if len(row)>4 and 'gearRatio' in row[4] else {})) for row in rows[1:]}
    devices['mainEngine'].pop('inputName')
    contract=dict(version=1,template=template,roles=dict(engine='mainEngine',clutch='clutch',transmission='gearbox',rear_reduction='rearReduction',rear_differential='rearDifferential'),
                  devices=devices,driven_wheels=['FL','FR','RL','RR'] if template=='cvt_rear_front_output' else ['RL','RR'],
                  front_rear_speed_ratio=1/(output*front),rear_total_reduction=rear,
                  front_total_reduction=rear*output*front if template=='cvt_rear_front_output' else None,
                  assumptions=['Synthetic ratios and locked carrier takeoff; actual vehicle hardware must be specified before physical qualification.',
                               'CVT uses a smooth viscous loss matching the specified nominal loss torque at engine peak RPM; no anti-rollback mechanism.'])
    from engine_profiles import apply as apply_engine_profile
    apply_engine_profile(part,contract,parameters)
    return part,contract
