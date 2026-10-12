-- Component fixtures have no wheel or powertrain requirements. Time/loads are
-- measured on physics steps; render updates only perform evidence captures.
local M={}
local job,running,t,file,samples,nextSample,byName,beamIds,mounts,initial,components,origin,phase,lastProgress
local firstCut,allCut,events,componentOrder,fixtureGearbox,fixtureControl,startup,steps
local naturalLoads,naturalBroken,naturalForce,naturalComplete
local rackSamples,rackHydro,rackAxis,rackSpec,rackActuators
local telemetryFailure
local releaseHistory,releaseBeams,releaseForces,nextReleaseSample
local function finite(value) return value==value and value~=math.huge and value~=-math.huge end
local function diagnosticNumber(value) return finite(value) and value or tostring(value) end
local function position(cid) return obj:getNodePosition(cid)+obj:getPosition() end
local function capture(label)
  obj:queueGameEngineLua(string.format('vehicleharness_bridge.capture(%q,%g,%q)',label,t,job.id))
end
local function finish(status,reason)
  if not running then return end
  running=false;if file then file:flush();file:close();file=nil end
  jsonWriteFile(job.output..'/mount_events.json',{job_id=job.id,session_id=job.session_id,events=events},true)
  jsonWriteFile(job.output..'/startup_powertrain.json',{job_id=job.id,samples=startup},true)
  if job.scenario=='mount_load_release' then
    jsonWriteFile(job.output..'/release_diagnostics.json',{job_id=job.id,session_id=job.session_id,
      load_application=job.mount_load_application or 'mass_distributed',samples=releaseHistory,
      energy_scope='Axial spring energy relative to initial lengths; excludes torsion, contact and aerodynamic energy'},true)
  end
  if rackSpec then jsonWriteFile(job.output..'/rack_motion.json',{job_id=job.id,samples=rackSamples},true) end
  jsonWriteFile(job.output..'/completion.json',{job_id=job.id,session_id=job.session_id,status=status,reason=reason,samples=samples,simulated_seconds=t,telemetry_failure=telemetryFailure,travel_guard='detached_translation_removed_v1'},true)
  capture('final')
  obj:queueGameEngineLua(string.format('vehicleharness_bridge.completed(%q,%q,%q)',status,reason or '',job.id))
end
local function key(a,b) if a<b then return a..'|'..b end return b..'|'..a end
local function state()
  local intact,broken,internal=0,0,0;local details={};local mountBeams={}
  for _,mount in ipairs(mounts) do
    local count=0
    for _,cid in ipairs(mount.cids) do mountBeams[cid]=true;if obj:beamIsBroken(cid) then count=count+1 end end
    if count==0 then intact=intact+1 end
    details[mount.id]={broken=count,total=#mount.cids}
  end
  for _,beam in pairs(v.data.beams) do if obj:beamIsBroken(beam.cid) then broken=broken+1;if not mountBeams[beam.cid] then internal=internal+1 end end end
  return intact,broken,internal,details
end
local function start(value)
  job=value;running=true;t=0;samples=0;nextSample=0;lastProgress=0;firstCut=false;allCut=false;phase=0;events={}
  byName={};beamIds={};mounts={};initial={};components={};origin=obj:getPosition()
  componentOrder={}
  fixtureGearbox=nil;fixtureControl={};startup={};steps=0
  naturalLoads={};naturalBroken=0;naturalForce=0;naturalComplete=false
  telemetryFailure=nil
  releaseHistory={};releaseBeams={};releaseForces={};nextReleaseSample=0
  if job.mount_load_application and job.mount_load_application~='mass_distributed' and job.mount_load_application~='mount_sites' then
    error('Unknown mount load application')
  end
  rackSamples={};rackHydro=nil;rackAxis=nil;rackSpec=nil;rackActuators={}
  obj:setSleepingEnabled(false)
  -- Mount tests may use a complete vehicle after a driving test in the same
  -- session. Neutralize persistent inputs and engine torque for this fixture.
  if input then for _,name in ipairs({'throttle','brake','parkingbrake','steering'}) do input.event(name,0,1) end end
  if job.manifest.kind=='exported_vehicle' and powertrain then
    fixtureGearbox=powertrain.getDevice('gearbox')
    if fixtureGearbox then
      fixtureControl.initial_gearbox_mode=fixtureGearbox.mode
      -- Arcade mode automatically selects Park with ignition off. Mount
      -- fixtures require unloaded driveline rotation, not a parking-lock load.
      controller.mainController.setGearboxMode('realistic')
      controller.mainController.shiftToGearIndex(job.fixture_gearbox_mode=='park' and 1 or 0)
      fixtureControl.gearbox_mode=fixtureGearbox.mode
      if fixtureGearbox.mode~=(job.fixture_gearbox_mode or 'neutral') then error('Fixture could not select requested gearbox mode') end
    end
  end
  if electrics and electrics.setIgnitionLevel then electrics.setIgnitionLevel(0) end
  local mass,count,fixed=0,0,0
  for _,node in pairs(v.data.nodes) do
    if node.name then byName[node.name]=node;initial[node.name]=position(node.cid) end
    mass=mass+obj:getNodeMass(node.cid);count=count+1;if node.fixed then fixed=fixed+1 end
  end
  for name,spec in pairs(job.manifest.nodes) do
    if not byName[name] then error('Missing compiled node '..name) end
    components[spec.component]=components[spec.component] or {};table.insert(components[spec.component],name)
  end
  if fixed~=#job.fixture_fixed_nodes then error('Compiled fixture pins differ') end
  for _,name in ipairs(job.fixture_fixed_nodes) do if not byName[name].fixed then error('Missing fixture support '..name) end end
  local compiled={}
  for _,beam in pairs(v.data.beams) do
    local a,b=v.data.nodes[beam.id1].name,v.data.nodes[beam.id2].name
    -- Pressure wheels generate anonymous nodes. They still participate in mass
    -- and damage measurements, but cannot identify an authored mounting edge.
    if a and b then
      local edge=key(a,b);beamIds[edge]=beamIds[edge] or {}
      table.insert(beamIds[edge],beam)
    end
    compiled[#compiled+1]={a=a,b=b,cid=beam.cid,spring=beam.beamSpring,damp=beam.beamDamp}
  end
  local matched={}
  for _,expected in ipairs(job.expected_beams) do
    local candidates=beamIds[key(expected.a,expected.b)] or {};local actual=nil
    -- Native bounded spring and damper beams may share both endpoints.
    -- Match properties one-to-one; a single compiled beam cannot satisfy two
    -- authored rows, even when those rows happen to have identical values.
    for _,candidate in ipairs(candidates) do
      local equal=not matched[candidate.cid]
      for field,value in pairs({beamSpring=expected.spring,beamDamp=expected.damp,beamDeform=expected.deform,beamStrength=expected.strength}) do
        local observed=candidate[field]
        if type(value)=='number' and (type(observed)~='number' or observed~=observed or math.abs(observed-value)>math.max(1e-3,math.abs(value)*1e-5)) then equal=false end
      end
      if equal then actual=candidate;break end
    end
    if not actual then error('Missing compiled beam with matching properties '..expected.a..'/'..expected.b) end
    matched[actual.cid]=true
  end
  for _,spec in ipairs(job.manifest.mounts) do
    local mount={id=spec.id,parent=spec.parent,child=spec.child,group=spec.group,cids={}}
    for _,edge in ipairs(spec.edges) do
      local candidates=beamIds[key(edge[1],edge[2])] or {}
      if #candidates~=1 then error('Missing or ambiguous mounting beam '..edge[1]..'/'..edge[2]) end
      mount.cids[#mount.cids+1]=candidates[1].cid
    end
    mounts[#mounts+1]=mount
    if job.scenario=='mount_load_release' and spec.group~='' then
      if not spec.per_beam_strength_n or spec.per_beam_strength_n<=0 then error('Natural release requires declared connector strength') end
      naturalLoads[spec.child]=(naturalLoads[spec.child] or 0)+spec.per_beam_strength_n*#spec.edges*2
    end
  end
  if job.scenario=='mount_load_release' then
    for _,beam in pairs(v.data.beams) do
      local a,b=v.data.nodes[beam.id1].name,v.data.nodes[beam.id2].name
      local sa,sb=job.manifest.nodes[a],job.manifest.nodes[b]
      if sa and sb then
        for child,_ in pairs(naturalLoads) do
          if sa.component==child or sb.component==child then
            releaseBeams[child]=releaseBeams[child] or {}
            table.insert(releaseBeams[child],{cid=beam.cid,a=a,b=b,spring=beam.beamSpring,
              length=(initial[b]-initial[a]):length(),internal=sa.component==child and sb.component==child})
          end
        end
      end
    end
  end
  if job.scenario=='rack_sweep' then
    rackSpec=job.manifest.steering_contract
    if not rackSpec or rackSpec.kind~='translating_rack' then error('Rack sweep requires the translating-rack contract') end
    local a,b=byName[rackSpec.actuator_nodes[1]],byName[rackSpec.actuator_nodes[2]]
    rackAxis=(initial[b.name]-initial[a.name]):normalized()
    for _,hydro in pairs(hydros.hydros or {}) do
      local beam=hydro.beamCID and v.data.beams[hydro.beamCID]
      if beam and ((beam.id1==a.cid and beam.id2==b.cid) or (beam.id2==a.cid and beam.id1==b.cid)) then rackHydro=hydro end
    end
    if not rackHydro then error('Native rack actuator is missing') end
    local declared=rackSpec.actuators or {{nodes=rackSpec.actuator_nodes,rest_length_m=rackSpec.actuator_rest_length_m,rack_motion_sign=1}}
    for _,spec in ipairs(declared) do
      local first,second=byName[spec.nodes[1]],byName[spec.nodes[2]];local found=nil
      for _,hydro in pairs(hydros.hydros or {}) do
        local beam=hydro.beamCID and v.data.beams[hydro.beamCID]
        if beam and first and second and ((beam.id1==first.cid and beam.id2==second.cid) or (beam.id1==second.cid and beam.id2==first.cid)) then
          if found then error('Duplicate native rack actuator') end
          found=hydro
        end
      end
      if not found then error('Missing declared rack actuator') end
      rackActuators[#rackActuators+1]={hydro=found,spec=spec}
    end
    local railCount,slideCount=0,0
    -- rails.cids is an engine lookup table, not a fourth authored rail.
    for _,rail in pairs(v.data.rails or {}) do if rail.cid~=nil and rail['links:'] and rail.capped then railCount=railCount+1 end end
    for _,slide in pairs(v.data.slidenodes or {}) do
      if slide.cid~=nil and slide.attached and slide.fixToRail and v.data.rails[slide.railName] then slideCount=slideCount+1 end
    end
    local actuatorNodes={}
    for _,hydro in pairs(hydros.hydros or {}) do
      local beam=hydro.beamCID and v.data.beams[hydro.beamCID]
      if beam and hydro.inputSource=='steering_input' then actuatorNodes[#actuatorNodes+1]={v.data.nodes[beam.id1].name,v.data.nodes[beam.id2].name} end
    end
    jsonWriteFile(job.output..'/rack_compiled.json',{job_id=job.id,rails=railCount,slidenodes=slideCount,actuator=rackHydro.beamCID,actuators=actuatorNodes},true)
  end
  local wheelGraphs={}
  if job.manifest.allows_generated_wheel_graph then
    for _,wheel in pairs(wheels.wheels) do
      local source=v.data.wheels[wheel.wheelID];local hub,tread=0,0
      for _ in pairs(source and source.nodes or {}) do hub=hub+1 end
      for _ in pairs(wheel.treadNodes or {}) do tread=tread+1 end
      wheelGraphs[wheel.name]={wheel_section=wheel.wheelSection,hub_nodes=hub,tread_nodes=tread}
    end
  end
  local controllerStates={}
  for name,expected in pairs(job.manifest.required_controllers or {}) do
    local instance=controller.getController(name)
    if not instance then error('Required controller failed to initialize: '..name) end
    local actual=instance.getState and instance.getState() or {}
    for key,value in pairs(expected) do if actual[key]~=value then error('Controller state differs: '..name..'/'..key) end end
    controllerStates[name]=actual
  end
  jsonWriteFile(job.output..'/compiled.json',{job_id=job.id,mass_kg=mass,node_count=count,fixed_nodes=fixed,beams=compiled,generated_wheels=wheelGraphs,controllers=controllerStates,fixture_control=fixtureControl},true)
  file=io.open(job.output..'/component.csv','w');if not file then error('Cannot open component telemetry') end
  for id,_ in pairs(components) do componentOrder[#componentOrder+1]=id end;table.sort(componentOrder)
  file:write('t,relative_speed,broken,internal_broken,intact_mounts,maximum_component_displacement,maximum_guarded_displacement')
  for _,id in ipairs(componentOrder) do file:write(',speed_'..id..',displacement_'..id) end;file:write('\n')
  enablePhysicsStepHook()
end
local function onPhysicsStep(dt)
  if not running then return end
  if fixtureGearbox and fixtureGearbox.mode~=(job.fixture_gearbox_mode or 'neutral') then finish('failed','Fixture gearbox mode changed');return end
  t=t+dt
  if rackSpec then
    local command=t>=2 and t<=12 and math.sin((t-2)*2*math.pi/10) or 0
    input.event('steering',command,1)
  end
  steps=steps+1
  if fixtureGearbox and steps<=240 and steps%4==0 then
    local devices={}
    for name,device in pairs(powertrain.getDevices()) do
      devices[name]={mode=device.mode,input_av=device.inputAV,output_av=device.outputAV1,torque=device.outputTorque1,
        inertia=device.cumulativeInertia,park_spring=device.parkLockSpring,park_damp=device.parkLockDamp,park_angle=device.parkClutchAngle}
    end
    startup[#startup+1]={t=t,devices=devices}
  end
  if job.scenario=='mount_release' then
    if t>=4 and not firstCut then
      local seen={};for _,mount in ipairs(mounts) do if mount.group~='' and not seen[mount.child] then obj:breakBeam(mount.cids[1]);seen[mount.child]=true end end
      firstCut=true
    end
    if t>=8 and not allCut then
      for _,mount in ipairs(mounts) do if mount.group~='' then obj:breakBeam(mount.cids[1]) end end
      allCut=true
    end
  end
  if job.scenario=='mount_load_release' then
    local count,total,details=0,0,{}
    for _,mount in ipairs(mounts) do
      local n=0;for _,cid in ipairs(mount.cids) do if obj:beamIsBroken(cid) then n=n+1 end end
      details[mount.id]={broken=n,total=#mount.cids}
      if mount.group~='' then count=count+n;total=total+#mount.cids end
    end
    if count>naturalBroken then
      events.natural=events.natural or {}
      events.natural[#events.natural+1]={time=t,applied_force_n=naturalForce,mounts=details}
      if naturalBroken==0 then capture('first_mount') end
      naturalBroken=count
      if count==total then naturalComplete=true;capture('release') end
    end
    naturalForce=0
    releaseForces={}
    if t>=3 and not naturalComplete then
      for child,maximum in pairs(naturalLoads) do
        local attached=false
        for _,mount in ipairs(mounts) do if mount.child==child and mount.group~='' and details[mount.id].broken<details[mount.id].total then attached=true end end
        if attached then
          local force=maximum*math.min(1,(t-3)/7);naturalForce=naturalForce+force
          releaseForces[child]=force
          local names=components[child];local mass=0
          if job.mount_load_application=='mount_sites' then
            -- Diagnostic pull applied at the fastener sites. Keep total force,
            -- ramp, strength and observation duration identical to the normal
            -- distributed panel load; this never qualifies the default test.
            names={};local seen={}
            for _,mount in ipairs(mounts) do if mount.child==child and mount.group~='' then
              for _,cid in ipairs(mount.cids) do
                local beam=v.data.beams[cid]
                for _,nodeId in ipairs({beam.id1,beam.id2}) do
                  local name=v.data.nodes[nodeId].name
                  if job.manifest.nodes[name].component==child and not seen[name] then seen[name]=true;names[#names+1]=name end
                end
              end
            end end
          end
          for _,name in ipairs(names) do mass=mass+obj:getNodeMass(byName[name].cid) end
          for _,name in ipairs(names) do obj:applyForceVector(byName[name].cid,vec3(0,0,force*obj:getNodeMass(byName[name].cid)/mass)) end
        end
      end
    end
  end
  if (job.scenario=='component_load' and t>=3 and t<7) or (job.scenario=='mount_release' and t>=8.5 and t<9) then
    local children={};for _,mount in ipairs(mounts) do children[mount.child]=true end
    for child,_ in pairs(children) do
      local names=components[child]
      local mass=0;for _,name in ipairs(names) do mass=mass+obj:getNodeMass(byName[name].cid) end
      -- Distributed inertia load: equal acceleration, not equal force on
      -- tiny numerical locator masses. Smooth the 20 N load on/off over 1 s.
      -- Release uses a short 0.5 m/s^2 pulse so separated skins stay in view.
      local force=job.scenario=='mount_release' and mass*.5 or 20*math.min(1,t-3,7-t)
      for _,name in ipairs(names) do obj:applyForceVector(byName[name].cid,vec3(force*obj:getNodeMass(byName[name].cid)/mass,0,0)) end
    end
  end
  if t>=nextSample then
    nextSample=t+.02;samples=samples+1
    local relative=0;local velocity=obj:getVelocity();local displacement=0;local guardedDisplacement=0;local perComponent={};local rejected={}
    local intact,broken,internal,details=state()
    local detachedCenters={}
    if job.scenario=='mount_load_release' then
      for child,_ in pairs(naturalLoads) do
        local detached=true
        for _,mount in ipairs(mounts) do
          if (mount.child==child or mount.parent==child) and details[mount.id].broken<details[mount.id].total then detached=false end
        end
        if detached then
          local center,oldCenter,mass=vec3(0,0,0),vec3(0,0,0),0
          for _,name in ipairs(components[child]) do
            local m=obj:getNodeMass(byName[name].cid);mass=mass+m
            center=center+position(byName[name].cid)*m;oldCenter=oldCenter+initial[name]*m
          end
          detachedCenters[child]={current=center/mass,initial=oldCenter/mass}
        end
      end
    end
    for name,spec in pairs(job.manifest.nodes) do
      local speed=(obj:getNodeVelocityVector(byName[name].cid)-velocity):length()
      local distance=(position(byName[name].cid)-initial[name]):length()
      local center=detachedCenters[spec.component]
      -- A released part can coast beyond 100 m in this zero-gravity fixture.
      -- Remove translation only after ALL incident mounts release. Rotation
      -- and deformation still contribute; speed/finite guards remain active.
      local guardedDistance=center and ((position(byName[name].cid)-center.current)-(initial[name]-center.initial)):length() or distance
      -- Preserve the actual rejected node, including NaN/Inf (as strings so
      -- the JSON remains valid). math.max alone can hide a NaN operand.
      local violation=not finite(speed) or not finite(distance) or not finite(guardedDistance) or speed>500 or (not byName[name].fixed and guardedDistance>100)
      if violation then
        rejected[#rejected+1]={node=name,component=spec.component,relative_speed_m_s=diagnosticNumber(speed),
          displacement_m=diagnosticNumber(distance),nonfinite=not finite(speed) or not finite(distance) or not finite(guardedDistance),
          guarded_displacement_m=diagnosticNumber(guardedDistance),free_flight_observer=center~=nil,
          speed_limit_exceeded=finite(speed) and speed>500,travel_limit_exceeded=not byName[name].fixed and finite(guardedDistance) and guardedDistance>100}
      end
      relative=math.max(relative,speed)
      if not byName[name].fixed then displacement=math.max(displacement,distance) end
      if not byName[name].fixed then guardedDisplacement=math.max(guardedDisplacement,guardedDistance) end
      local detail=perComponent[spec.component] or {speed=0,displacement=0}
      detail.speed=math.max(detail.speed,speed);detail.displacement=math.max(detail.displacement,distance);perComponent[spec.component]=detail
    end
    if job.scenario=='mount_load_release' and t>=nextReleaseSample then
      nextReleaseSample=t+.1;local observed={}
      for child,_ in pairs(naturalLoads) do
        local mass,kinetic,axial,connector,maxStretch=0,0,0,0,0
        local center=vec3(0,0,0);local momentum=vec3(0,0,0)
        for _,name in ipairs(components[child]) do
          local cid=byName[name].cid;local m=obj:getNodeMass(cid);local speed=obj:getNodeVelocityVector(cid)
          mass=mass+m;center=center+position(cid)*m;momentum=momentum+speed*m;kinetic=kinetic+.5*m*speed:squaredLength()
        end
        for _,beam in ipairs(releaseBeams[child] or {}) do if not obj:beamIsBroken(beam.cid) then
          local extension=(position(byName[beam.b].cid)-position(byName[beam.a].cid)):length()-beam.length
          local energy=.5*beam.spring*extension*extension
          if beam.internal then axial=axial+energy;maxStretch=math.max(maxStretch,math.abs(extension)) else connector=connector+energy end
        end end
        observed[child]={mass_kg=mass,kinetic_j=diagnosticNumber(kinetic),internal_axial_energy_j=diagnosticNumber(axial),
          connector_axial_energy_j=diagnosticNumber(connector),maximum_internal_extension_m=diagnosticNumber(maxStretch),
          center={diagnosticNumber(center.x/mass),diagnosticNumber(center.y/mass),diagnosticNumber(center.z/mass)},
          center_speed_m_s=diagnosticNumber(momentum:length()/mass),applied_force_n=releaseForces[child] or 0}
      end
      releaseHistory[#releaseHistory+1]={t=t,components=observed}
    end
    if #rejected>0 then
      table.sort(rejected,function(a,b) return a.node<b.node end)
      telemetryFailure={time=t,rejected_nodes=rejected,limits={relative_speed_m_s=500,displacement_m=100},
        internal_broken=internal,mounts=details,applied_force_n=naturalForce,natural_release_complete=naturalComplete}
      jsonWriteFile(job.output..'/telemetry_failure.json',{job_id=job.id,session_id=job.session_id,failure=telemetryFailure},true)
      -- The rejected observation is in the diagnostic, not the CSV sample count.
      samples=samples-1
      local first=rejected[1]
      local cause=first.nonfinite and 'nonfinite state' or (first.speed_limit_exceeded and 'speed limit' or 'travel limit')
      finish('failed','Component telemetry '..cause..': '..first.component..' / '..first.node);return
    end
    if rackSpec then
      local target=obj:getBeamRefLength(rackHydro.beamCID)*rackHydro.state-rackSpec.actuator_rest_length_m
      local targets={}
      for _,actuator in ipairs(rackActuators) do
        local spec=actuator.spec;local hydro=actuator.hydro
        local value=(obj:getBeamRefLength(hydro.beamCID)*hydro.state-spec.rest_length_m)*spec.rack_motion_sign
        if math.abs(value-target)>1e-6 then finish('failed','Rack actuator targets disagree');return end
        targets[#targets+1]=value
      end
      local error,housing,shift=0,0,0
      for _,name in ipairs(rackSpec.slider_nodes) do
        local delta=position(byName[name].cid)-initial[name]
        error=math.max(error,(delta-rackAxis*target):length());shift=shift+delta:dot(rackAxis)
      end
      for _,name in ipairs(rackSpec.housing_nodes) do housing=math.max(housing,(position(byName[name].cid)-initial[name]):length()) end
      rackSamples[#rackSamples+1]={t=t,target_m=target,targets_m=targets,shift_m=shift/#rackSpec.slider_nodes,error_m=error,housing_error_m=housing}
    end
    file:write(string.format('%.9g,%.9g,%d,%d,%d,%.9g,%.9g',t,relative,broken,internal,intact,displacement,guardedDisplacement))
    for _,id in ipairs(componentOrder) do file:write(string.format(',%.9g,%.9g',perComponent[id].speed,perComponent[id].displacement)) end;file:write('\n')
    if job.scenario~='mount_load_release' then
      if phase==0 and t>=4.5 then events.first={time=t,mounts=details};phase=1;capture('first_mount') end
      if phase==1 and t>=8.5 then events.release={time=t,mounts=details};phase=2;capture('release') end
    end
  end
  if t-lastProgress>1 then lastProgress=t;file:flush();jsonWriteFile(job.output..'/progress.json',{job_id=job.id,session_id=job.session_id,simulated_seconds=t},false) end
  if t>=job.duration then finish('completed') end
end
local function protected(fn)
  return function(...) local ok,err=pcall(fn,...);if not ok then finish('failed',tostring(err)) end end
end
M.start=protected(start);M.onPhysicsStep=protected(onPhysicsStep);M.updateGFX=function() end
return M
