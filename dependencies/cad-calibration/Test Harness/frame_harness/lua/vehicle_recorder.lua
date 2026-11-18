local M={}
local componentRecorder
local job,running,t,samples,file,nodes,byName,initial,origin,lastPos,forward,left,distance,braking,switchDone
local sampleAt=0
local firstBreak=false
local diagnosticSamples={}
local referenceNodes={}
local fixtureTreadNodes,fixtureMinimumClearance={},nil
local articulationIndex,articulationBase
local physicsSteps,physicsDtMin,physicsDtMax=0,math.huge,0
local startupSamples={}
local savedInputSources={}
local coiloverBeams={}
local toeLinkBeams={}
local steeringTieBeams={}
local frequencyRecorder
local steeringVisualCommand=0
local function finish(state,reason)
  if not running then return end
  running=false;if file then file:flush();file:close() end
  if frequencyRecorder then frequencyRecorder.finish();frequencyRecorder=nil end
  for _,name in ipairs({'steering','throttle','brake','parkingbrake'}) do
    input.allowedInputSources[name]=savedInputSources[name]
  end
  savedInputSources={}
  local velocitySnapshot={}
  local finalPositions={}
  local comVelocity=obj:getVelocity()
  for _,node in ipairs(nodes or {}) do if node.name then
    velocitySnapshot[node.name]=(obj:getNodeVelocityVector(node.cid)-comVelocity):length()
    local p=obj:getAbsNodePosition(node.cid);finalPositions[node.name]={p.x,p.y,p.z}
  end end
  assert(jsonWriteFile(job.output..'/motion_diagnostics.json',{job_id=job.id,motion_reference_version=job.motion_reference and job.motion_reference.version,samples=diagnosticSamples,physics_steps=physicsSteps,physics_dt_min=physicsDtMin,physics_dt_max=physicsDtMax,position_source='getAbsNodePosition',sampling_clock='updateGFX',telemetry_requested_sample_interval_s=.02,motion_decimation=1},false),'Could not publish motion diagnostics')
  -- Successful controls are needed to distinguish a session-order effect from
  -- an actual candidate regression. Keep the same bounded startup window.
  assert(jsonWriteFile(job.output..'/startup_diagnostics.json',{job_id=job.id,samples=startupSamples},false),'Could not publish startup diagnostics')
  -- The controller may shut down an owned headless process as soon as this
  -- marker appears. Publish it last, after every recording has closed.
  assert(jsonWriteFile(job.output..'/completion.json.tmp',{job_id=job.id,session_id=job.session_id,status=state,reason=reason,samples=samples,motion_samples=#diagnosticSamples,simulated_seconds=t,final_relative_node_speeds=velocitySnapshot,final_node_positions=finalPositions,fixture_minimum_clearance_m=fixtureMinimumClearance},false),'Could not publish recording completion')
  -- FS:renameFile is available in the game-engine VM, not the vehicle VM.
  obj:queueGameEngineLua(string.format([[
    if FS:renameFile(%q,%q)~=0 then
      vehicleharness_bridge.completed('failed','Could not publish recording completion',%q)
    else
      vehicleharness_bridge.capture('final',%g,%q)
      vehicleharness_bridge.completed(%q,%q,%q)
    end
  ]],job.output..'/completion.json.tmp',job.output..'/completion.json',job.id,t,job.id,state,reason or '',job.id))
end
-- Relative node positions are cached at graphics cadence. Use the current
-- physics position for measurements and physics-step fixture enforcement.
local function position(cid) return obj:getAbsNodePosition(cid) end
local function tireShape(wheel)
  local a,b=position(wheel.node1),position(wheel.node2)
  local center=(a+b)*.5;local axis=(b-a):normalized()*wheel.wheelDir
  local originalCenter=(initial[wheel.node1]+initial[wheel.node2])*.5
  local originalAxis=(initial[wheel.node2]-initial[wheel.node1]):normalized()*wheel.wheelDir
  local velocity=(obj:getNodeVelocityVector(wheel.node1)+obj:getNodeVelocityVector(wheel.node2))*.5
  local count,offset,widthLow,widthHigh=0,0,math.huge,-math.huge
  local radius,countSide={0,0},{0,0};local projected={};local angularNumerator,angularDenominator=0,0
  local treadCenters={vec3(0,0,0),vec3(0,0,0)}
  for _,node in pairs(wheel.treadNodes or {}) do
    if type(node)=='number' then node=v.data.nodes[node] end
    local delta=position(node.cid)-center;local x=delta:dot(axis);local radial=delta-axis*x
    local relative=obj:getNodeVelocityVector(node.cid)-velocity;local tangent=axis:cross(radial)
    local side=(initial[node.cid]-originalCenter):dot(originalAxis)<0 and 1 or 2
    count=count+1;offset=offset+x;widthLow=math.min(widthLow,x);widthHigh=math.max(widthHigh,x)
    radius[side]=radius[side]+radial:length();countSide[side]=countSide[side]+1
    treadCenters[side]=treadCenters[side]+delta
    angularNumerator=angularNumerator+tangent:dot(relative);angularDenominator=angularDenominator+tangent:squaredLength()
    projected[#projected+1]={tangent=tangent,relative=relative}
  end
  if count==0 then return nil end
  local spin=angularNumerator/math.max(angularDenominator,1e-12);local residual=0
  for _,sample in ipairs(projected) do residual=math.max(residual,(sample.relative-sample.tangent*spin):length()) end
  local hubCenters,hubCounts={vec3(0,0,0),vec3(0,0,0)},{0,0}
  local source=v.data.wheels[wheel.wheelID]
  for _,node in pairs(source and source.nodes or {}) do
    if type(node)=='number' then node=v.data.nodes[node] end
    local side=(initial[node.cid]-originalCenter):dot(originalAxis)<0 and 1 or 2
    hubCenters[side]=hubCenters[side]+position(node.cid)-center;hubCounts[side]=hubCounts[side]+1
  end
  local function ringAxis(centers,counts)
    if counts[1]==0 or counts[2]==0 then return nil end
    local delta=centers[2]/counts[2]-centers[1]/counts[1]
    local width=delta:length();if width<1e-8 then return nil end
    local direction=delta/width
    return {direction_world={direction.x,direction.y,direction.z},width_m=width}
  end
  return {center_offset_m=offset/count,lateral_width_m=widthHigh-widthLow,
    hub_axis=ringAxis(hubCenters,hubCounts),tread_axis=ringAxis(treadCenters,countSide),
    mean_radius_negative_x_m=radius[1]/math.max(1,countSide[1]),mean_radius_positive_x_m=radius[2]/math.max(1,countSide[2]),
    peak_velocity_residual_m_s=residual,fitted_spin_rad_s=spin,down_force_n=wheel.downForceRaw,side_slip_m_s=wheel.lastSideSlip}
end
local function start(manifest)
  componentRecorder=nil
  for _,capability in ipairs(manifest.manifest.capabilities or {}) do
    if capability=='mounts' and (manifest.scenario=='component_settle' or manifest.scenario=='component_load' or manifest.scenario=='mount_release' or manifest.scenario=='mount_load_release' or manifest.scenario=='rack_sweep') then
      componentRecorder=require('/mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/component_recorder')
      componentRecorder.start(manifest);return
    end
  end
  obj:setSleepingEnabled(false)
  job=manifest;running=true;t=0;samples=0;sampleAt=0;distance=0;braking=false;switchDone=false;nodes={};byName={};initial={};steeringVisualCommand=0
  -- Native automation filter omits user steering assists. Keep this owned
  -- recording independent of gamepad settings and physical controller input.
  savedInputSources={}
  for _,name in ipairs({'steering','throttle','brake','parkingbrake'}) do
    savedInputSources[name]=input.allowedInputSources[name]
    input.allowedInputSources[name]={cadHarness=true}
  end
  local mass=0;local count=0;local fixed=0
  firstBreak=false;diagnosticSamples={};physicsSteps=0;physicsDtMin=math.huge;physicsDtMax=0
  startupSamples={}
  fixtureTreadNodes={};fixtureMinimumClearance=nil
  articulationIndex=nil;articulationBase=nil
  for _,node in pairs(v.data.nodes) do
    nodes[#nodes+1]=node;if node.name then byName[node.name]=node end;initial[node.cid]=position(node.cid);mass=mass+obj:getNodeMass(node.cid);count=count+1
    if node.fixed then fixed=fixed+1 end
  end
  for name,_ in pairs(job.manifest.nodes) do if not byName[name] then finish('failed','Missing explicit node '..name);return end end
  frequencyRecorder=require('/mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/frequency_recorder').new(job,byName)
  coiloverBeams={};toeLinkBeams={};steeringTieBeams={}
  for corner,reference in pairs(job.motion_reference and job.motion_reference.corners or {}) do
    local a=byName[reference.points.tie_inner];local b=byName[reference.points.tie_outer]
    if a and b then
      steeringTieBeams[corner]={}
      for _,beam in pairs(v.data.beams) do
        if (beam.id1==a.cid and beam.id2==b.cid) or (beam.id1==b.cid and beam.id2==a.cid) then
          table.insert(steeringTieBeams[corner],beam)
        end
      end
    end
  end
  for corner,wheel in pairs(job.manifest.wheels) do
    local a,b=byName[wheel.nodes.shock_top],byName[wheel.nodes.shock_bottom]
    coiloverBeams[corner]={}
    if a and b then for _,beam in pairs(v.data.beams) do
      if (beam.id1==a.cid and beam.id2==b.cid) or (beam.id1==b.cid and beam.id2==a.cid) then
        table.insert(coiloverBeams[corner],beam)
      end
    end end
  end
  referenceNodes={}
  for corner,wheel in pairs(job.manifest.wheels) do if wheel.toe_link then
    local expected=wheel.toe_link
    local a,b=byName[expected.nodes[1]],byName[expected.nodes[2]]
    if not a or not b then finish('failed','Missing rear toe-link node: '..corner);return end
    for _,beam in pairs(v.data.beams) do
      if (beam.id1==a.cid and beam.id2==b.cid) or (beam.id1==b.cid and beam.id2==a.cid) then
        if toeLinkBeams[corner] then finish('failed','Ambiguous rear toe-link beam: '..corner);return end
        toeLinkBeams[corner]=beam.cid
      end
    end
    if not toeLinkBeams[corner] then finish('failed','Missing rear toe-link beam: '..corner);return end
    local actual=obj:getBeamRestLength(toeLinkBeams[corner])
    if math.abs(actual-expected.reference_length_m)>1e-6 then
      finish('failed',string.format('Rear toe-link rest length differs: %s %.9g / %.9g',corner,actual,expected.reference_length_m));return
    end
  end end
  for _,name in ipairs(job.motion_reference and job.motion_reference.nodes or {}) do
    if not byName[name] then finish('failed','Missing motion reference node '..name);return end
    referenceNodes[#referenceNodes+1]=byName[name]
  end
  local matched={}
  for _,expected in ipairs(job.expected_beams or {}) do
    local a,b=byName[expected.a],byName[expected.b];local found=false
    if a and b then
      for _,actual in pairs(v.data.beams) do
        if not matched[actual.cid] and ((actual.id1==a.cid and actual.id2==b.cid) or (actual.id1==b.cid and actual.id2==a.cid)) then
          local valid=true
          for key,field in pairs({spring='beamSpring',damp='beamDamp',deform='beamDeform',strength='beamStrength'}) do
            if type(expected[key])=='number' and math.abs(actual[field]-expected[key])>math.max(1e-4,math.abs(expected[key])*1e-5) then valid=false end
          end
          if valid then matched[actual.cid]=true;found=true;break end
        end
      end
    end
    if not found then finish('failed','Compiled beam/properties differ: '..expected.a..'/'..expected.b);return end
  end
  if fixed~=#(job.fixture_fixed_nodes or {}) then finish('failed','Compiled fixture pins differ from this test job');return end
  local compiledTorsions={}
  for _,actual in pairs(v.data.torsionbars or {}) do
    compiledTorsions[#compiledTorsions+1]={v.data.nodes[actual.id1].name,v.data.nodes[actual.id2].name,v.data.nodes[actual.id3].name,v.data.nodes[actual.id4].name,{spring=actual.spring,damp=actual.damp,cid=actual.cid}}
  end
  for _,expected in ipairs(job.manifest.torsionbars or {}) do
    local found=false
    for _,actual in ipairs(compiledTorsions) do
      if actual[1]==expected[1] and actual[2]==expected[2] and actual[3]==expected[3] and actual[4]==expected[4] and
        math.abs(actual[5].spring-expected[5].spring)<math.max(1e-5,expected[5].spring*1e-5) and
        math.abs(actual[5].damp-expected[5].damp)<math.max(1e-5,expected[5].damp*1e-5) then found=true;break end
    end
    if not found then finish('failed','Compiled angular brace differs: '..expected[1]..'/'..expected[4]);return end
  end
  for _,name in ipairs(job.fixture_fixed_nodes or {}) do if not byName[name] or not byName[name].fixed then finish('failed','Missing test support '..name);return end end
  local names={};for _,wheel in pairs(wheels.wheels) do names[wheel.name]=true end
  for _,name in ipairs(job.manifest.expected_wheel_names) do if not names[name] then finish('failed','Missing wheel '..name);return end end
  local tirePhysics={}
  for _,wheel in pairs(wheels.wheels) do
    local treadCount,hubCount,colliding,selfColliding=0,0,0,0
    for _,node in pairs(wheel.treadNodes or {}) do
      if type(node)=='number' then node=v.data.nodes[node] end
      treadCount=treadCount+1
      if job.fixture_minimum_clearance_m then fixtureTreadNodes[#fixtureTreadNodes+1]=node.cid end
      -- JBeam optimization removes collision=true; the native loader treats
      -- missing collision/staticCollision as true. False is retained.
      if node.collision~=false and node.staticCollision~=false then colliding=colliding+1 end
      if node.selfCollision then selfColliding=selfColliding+1 end
    end
    local source=v.data.wheels[wheel.wheelID]
    for _,node in pairs(source and source.nodes or {}) do hubCount=hubCount+1 end
    local lBeams=0
    for _,beam in pairs(source and source.reinfBeams or {}) do
      if type(beam)=='number' then beam=v.data.beams[beam] end
      if beam and beam.beamType==4 and beam.id3 then lBeams=lBeams+1 end
    end
    tirePhysics[wheel.name]={wheel_section=wheel.wheelSection,tread_nodes=treadCount,hub_nodes=hubCount,
      reinforcement_l_beams=lBeams,
      axle_nodes={v.data.nodes[wheel.node1].name,v.data.nodes[wheel.node2].name},wheel_direction=wheel.wheelDir,
      collision_nodes=colliding,self_collision_nodes=selfColliding,pressure_group=wheel.pressureGroup,
      pressure_pa=wheel.pressureGroupId and obj:getGroupPressure(wheel.pressureGroupId) or 0,reaction_nodes={}}
    for _,key in ipairs({'nodeArm','torqueCoupling','torqueArm','torqueArm2'}) do
      local cid=source and source[key]
      if key=='torqueCoupling' and source then cid=source.torqueCouple or cid end
      if type(cid)=='number' and v.data.nodes[cid] then tirePhysics[wheel.name].reaction_nodes[key]=v.data.nodes[cid].name end
    end
  end
  jsonWriteFile(job.output..'/tire_physics.json',tirePhysics,true)
  if job.fixture_minimum_clearance_m then
    if #fixtureTreadNodes==0 then finish('failed','Suspended fixture has no measured tread nodes');return end
    fixtureMinimumClearance=math.huge
    for _,cid in ipairs(fixtureTreadNodes) do fixtureMinimumClearance=math.min(fixtureMinimumClearance,position(cid).z-job.fixture_ground_z) end
    if fixtureMinimumClearance<job.fixture_minimum_clearance_m then finish('failed','Suspended fixture tires are too close to the ground');return end
  end
  for name,info in pairs(job.manifest.wheels) do if info.tire_contract then
    local expected=info.tire_contract;local actual=tirePhysics[name]
    if not actual or actual.wheel_section~=expected.wheel_section or actual.tread_nodes~=expected.tread_nodes or
      actual.hub_nodes~=expected.hub_nodes or actual.collision_nodes~=expected.tread_nodes or actual.self_collision_nodes~=0 or
      not actual.pressure_group or actual.pressure_pa<=0 then finish('failed','Generated tire collision/pressure contract differs: '..name);return end
    if expected.axle_nodes and (actual.axle_nodes[1]~=expected.axle_nodes[1] or actual.axle_nodes[2]~=expected.axle_nodes[2] or
      actual.wheel_direction~=expected.wheel_direction) then finish('failed','Generated wheel axle/direction differs: '..name);return end
    if expected.reinforcement_l_beams and actual.reinforcement_l_beams~=expected.reinforcement_l_beams then
      finish('failed','Generated tire cross-section reinforcement differs: '..name);return
    end
  end end
  for name,info in pairs(job.manifest.wheels) do
    for key,node in pairs(info.reaction_nodes or {}) do
      if not tirePhysics[name] or tirePhysics[name].reaction_nodes[key]~=node then
        finish('failed','Wheel torque reaction did not bind: '..name..'/'..key);return
      end
    end
  end
  local devices={};for name,device in pairs(powertrain.getDevices()) do devices[name]=device.type end
  local controllerStates={}
  for name,expected in pairs(job.manifest.required_controllers or {}) do
    local instance=controller.getController(name)
    if not instance then finish('failed','Required controller failed to initialize: '..name);return end
    local state=instance.getState and instance.getState() or {}
    for key,value in pairs(expected) do
      if state[key]~=value then finish('failed','Controller state differs: '..name..'/'..key);return end
    end
    controllerStates[name]=state
  end
  local contract=job.manifest.device_contract
  if contract then
    for name,expected in pairs(contract.devices) do
      local device=powertrain.getDevice(name)
      if not device or device.type~=expected.type then finish('failed','Missing or wrong powertrain device '..name);return end
      if expected.inputName and (not device.parent or device.parent.name~=expected.inputName) then finish('failed','Wrong powertrain parent '..name);return end
      if expected.inputIndex and device.inputIndex~=expected.inputIndex then finish('failed','Wrong powertrain port '..name);return end
      if expected.gearRatio and math.abs(device.gearRatio-expected.gearRatio)>1e-6 then finish('failed','Wrong ratio '..name);return end
      for index,node in ipairs(expected.torqueReactionNodes or {}) do
        local cid=device.torqueReactionNodes and device.torqueReactionNodes[index]
        if not cid or not v.data.nodes[cid] or v.data.nodes[cid].name~=node then finish('failed','Engine torque reaction did not bind: '..name);return end
      end
    end
  else
    for _,name in ipairs({'mainEngine','clutch','gearbox','transfercase','frontShaft'}) do if not devices[name] then finish('failed','Missing powertrain device '..name);return end end
  end
  local beamData={}
  for _,b in pairs(v.data.beams) do beamData[#beamData+1]={cid=b.cid,a=b.id1,b=b.id2,spring=b.beamSpring,damp=b.beamDamp,length=obj:getBeamLength(b.cid),rest=obj:getBeamRestLength(b.cid),beam_type=b.beamType,damp_cutoff_hz=b.dampCutoffHz,spring_expansion=b.springExpansion,damp_expansion=b.dampExpansion,short_bound=b.beamShortBound,long_bound=b.beamLongBound} end
  local actualNodes={}
  for _,node in ipairs(nodes) do actualNodes[node.name or tostring(node.cid)]={cid=node.cid,mass_kg=obj:getNodeMass(node.cid),position={node.pos.x,node.pos.y,node.pos.z},fixed=node.fixed or false,
    self_collision=node.selfCollision or false,collision=node.collision~=false,static_collision=node.staticCollision~=false} end
  local actualDevices={}
  for name,device in pairs(powertrain.getDevices()) do
    local reactions={}
    for _,cid in ipairs(device.torqueReactionNodes or {}) do reactions[#reactions+1]=v.data.nodes[cid] and v.data.nodes[cid].name or tostring(cid) end
    local inertiaChildren={}
    for _,child in ipairs(device.children or {}) do inertiaChildren[#inertiaChildren+1]=child.name end
    actualDevices[name]={type=device.type,inputName=device.inputName,inputIndex=device.inputIndex,gearRatio=device.gearRatio,lockSpring=device.lockSpring,lockDamp=device.lockDamp,parkLockSpring=device.parkLockSpring,parkLockDamp=device.parkLockDamp,cumulativeInertia=device.cumulativeInertia,torqueReactionNodes=reactions,inertiaChildren=inertiaChildren}
  end
  local steeringCompiled={hydros={},rails={},sliders={}}
  for _,hydro in pairs(hydros.hydros or {}) do
    local beam=hydro.beamCID and v.data.beams[hydro.beamCID]
    if beam and hydro.inputSource=='steering_input' then
      steeringCompiled.hydros[#steeringCompiled.hydros+1]={v.data.nodes[beam.id1].name,v.data.nodes[beam.id2].name}
    end
  end
  for name,rail in pairs(v.data.rails or {}) do
    if rail.cid~=nil and rail['links:'] then
      local links={};for _,cid in ipairs(rail['links:']) do links[#links+1]=v.data.nodes[cid].name end
      steeringCompiled.rails[name]={nodes=links,capped=rail.capped or false}
    end
  end
  for _,slide in pairs(v.data.slidenodes or {}) do
    if slide.cid~=nil and v.data.nodes[slide.id] then
      steeringCompiled.sliders[v.data.nodes[slide.id].name]={rail=slide.railName,attached=slide.attached~=false and slide.attached~=0,fixed=slide.fixToRail~=false and slide.fixToRail~=0}
    end
  end
  jsonWriteFile(job.output..'/compiled.json',{diagnostic=job.diagnostic,mass_kg=mass,node_count=count,explicit_nodes=job.manifest.nodes,actual_nodes=actualNodes,wheel_names=names,tire_physics=tirePhysics,powertrain=devices,device_graph=actualDevices,controllers=controllerStates,fixed_nodes=fixed,beams=beamData,torsionbars=compiledTorsions,steering=steeringCompiled},true)
  file=io.open(job.output..'/vehicle.csv','w');if not file then finish('failed','Cannot create telemetry file');return end
  file:write('t,speed,forward_speed,forward_distance,lateral_distance,distance,up_z,relative_node_speed,broken,rpm,cvt_ratio,throttle,brake,av_FL,av_FR,av_RL,av_RR,travel_FL,travel_FR,travel_RL,travel_RR\n')
  origin=obj:getPosition();lastPos=origin;forward=obj:getDirectionVector();left=obj:getDirectionVectorUp():cross(forward)
  controller.mainController.setGearboxMode('realistic');controller.mainController.shiftToGearIndex(job.scenario=='reverse' and -1 or 2)
  electrics.setIgnitionLevel(3)
  enablePhysicsStepHook()
end
local function onPhysicsStep(dt)
  if componentRecorder then componentRecorder.onPhysicsStep(dt);return end
  if running then physicsSteps=physicsSteps+1;physicsDtMin=math.min(physicsDtMin,dt);physicsDtMax=math.max(physicsDtMax,dt) end
  if running and frequencyRecorder then frequencyRecorder.step(dt,t) end
  -- Keep the first half-second: a light component can become unstable after
  -- initial tire inflation but before the regular motion sampling interval.
  if running and physicsSteps<=(job.drop_height_m and 6000 or 1000) and physicsSteps%4==0 then
    local speeds={};local fastest;local maximum=0
    local allMaximum=0;local allFastest;local allFastestCid;local generatedMaximum=0
    local positions=job.drop_height_m and physicsSteps>=1200 and physicsSteps<=2200 and physicsSteps%20==0 and {} or nil
    for _,node in ipairs(nodes) do
      local speed=obj:getNodeVelocityVector(node.cid):length()
      if positions then local p=position(node.cid);positions[tostring(node.cid)]={p.x,p.y,p.z} end
      if speed>allMaximum then allMaximum=speed;allFastest=node.name or ('cid_'..node.cid);allFastestCid=node.cid end
      if job.manifest.nodes[node.name] then
        local owner=job.manifest.nodes[node.name].component
        speeds[owner]=math.max(speeds[owner] or 0,speed)
        if speed>maximum then maximum=speed;fastest=node.name end
      else generatedMaximum=math.max(generatedMaximum,speed) end
    end
    local devices={};local wheelState={}
    for name,device in pairs(powertrain.getDevices()) do
      devices[name]={input_av=device.inputAV,output_av=device.outputAV1,output_av2=device.outputAV2,
        torque=device.outputTorque1,torque2=device.outputTorque2,shaft_angle=device.shaftAngle,
        lock_spring=device.lockSpring,lock_damp=device.lockDamp,inertia=device.cumulativeInertia}
    end
    for _,wheel in pairs(wheels.wheels) do wheelState[wheel.name]={av=wheel.angularVelocity,torque=wheel.propulsionTorque,brake=wheel.brakingTorque} end
    local springRest={}
    for corner,beams in pairs(coiloverBeams) do
      springRest[corner]={}
      for _,beam in ipairs(beams) do table.insert(springRest[corner],{rest=obj:getBeamRestLength(beam.cid),length=(position(beam.id1)-position(beam.id2)):length()}) end
    end
    startupSamples[#startupSamples+1]={step=physicsSteps,seconds=physicsSteps*dt,gravity=obj:getGravity(),spring_rest=springRest,fastest_node=fastest,max_speed=maximum,component_speed=speeds,devices=devices,wheels=wheelState,
      all_max_speed=allMaximum,all_fastest_node=allFastest,all_fastest_cid=allFastestCid,generated_max_speed=generatedMaximum,node_positions_by_cid=positions}
  end
  if not running or (job.scenario~='supported' and job.scenario~='articulation') then return end
  for _,cid in ipairs(fixtureTreadNodes) do fixtureMinimumClearance=math.min(fixtureMinimumClearance,position(cid).z-job.fixture_ground_z) end
  if fixtureMinimumClearance<job.fixture_minimum_clearance_m then finish('failed','Suspended fixture lost tire ground clearance');return end
  -- Chassis pins exist only in the archived staged fixture, never in the exported vehicle.
  if job.scenario=='articulation' and t>3 and t<23 then
    local corners={'FL','FR','RL','RR'};local index=math.min(4,math.floor((t-3)/5)+1)
    local pair=job.manifest.wheels[corners[index]].nodes;local a=byName[pair.axis_in];local b=byName[pair.axis_out]
    if a and b then
      -- Load the wheel center. axis_in is the negative-X endpoint on both
      -- sides, so loading only that node adds opposite camber moments left/right.
      local p=(position(a.cid)+position(b.cid))*.5
      if articulationIndex~=index then articulationIndex=index;articulationBase=p.z end
      -- Start/end at the settled pose with zero target velocity. An immediate
      -- jump from full droop to design height tests an impact, not a travel sweep.
      local phase=math.max(0,(t-3)%5)/5
      local targetZ=articulationBase+.16*math.sin(phase*math.pi)^2
      local vel=(obj:getNodeVelocityVector(a.cid)+obj:getNodeVelocityVector(b.cid))*.5
      local force=vec3(0,0,((targetZ-p.z)*12000-vel.z*150)*.5)
      obj:applyForceVector(a.cid,force);obj:applyForceVector(b.cid,force)
    end
  end
end
local function updateGFX(dt)
  if componentRecorder then componentRecorder.updateGFX(dt);return end
  if not running then return end
  t=t+dt
  if job.scenario=='articulation' then
    for owner,binding in pairs(job.manifest.coilover_render or {}) do
      local corner=job.manifest.component_roles[owner]:sub(1,2):upper()
      local order={FL=0,FR=1,RL=2,RR=3};local start=3+order[corner]*5
      for label,at in pairs({rest=start+.1,bump=start+2.5}) do
        if t>=at and t-dt<at then obj:queueGameEngineLua(string.format('vehicleharness_bridge.capture(%q,%g,%q)','coilover-'..owner..'--'..label,t,job.id)) end
      end
    end
  end
  local speed=obj:getVelocity():length();local throttle,brake,steering=0,0,0
  if t>1 and t<1.2 then electrics.setIgnitionLevel(2) end
  if t>4 then
    if job.scenario=='supported' then
      throttle=.7
      if not job.manifest.device_contract and t>9 and not switchDone then powertrain.getDevice('frontShaft'):setMode('connected');switchDone=true end
    elseif job.scenario=='acceleration' then throttle=1
    elseif job.scenario=='reverse' then
      if (obj:getPosition()-origin):dot(forward)<-5 then braking=true end
      if braking then brake=1 else throttle=.3 end
    elseif job.scenario=='braking' then
      if speed>=20/3.6 or t>24 then braking=true end
      if braking then brake=1 else throttle=1 end
    elseif job.scenario=='left_turn' or job.scenario=='right_turn' then
      throttle=speed<3 and .35 or 0;steering=job.scenario=='left_turn' and -0.7 or 0.7
    end
  end
  if job.scenario=='steering_visual' then
    local target=0
    if t<12.5 then
      brake=1
      if t>=4 and t<6.5 then target=-1 elseif t>=8 and t<10.5 then target=1 end
    elseif t<22 then
      throttle=math.max(0,math.min(.4,(3-speed)*.25));brake=math.max(0,math.min(.2,(speed-3)*.1))
      target=t<18 and -.35 or .35
    elseif t<38 then
      throttle=math.max(0,math.min(.65,(6-speed)*.25));brake=math.max(0,math.min(.2,(speed-6)*.1))
      target=t<31 and -.2 or .2
    else brake=1 end
    steeringVisualCommand=steeringVisualCommand+math.max(-dt*.75,math.min(dt*.75,target-steeringVisualCommand))
    steering=steeringVisualCommand
    for label,at in pairs({neutral=3.8,left=6,right=10,['return']=12,['low-left']=17,['low-right']=21,['medium-left']=29,['medium-right']=35}) do
      if t>=at and t-dt<at then
        local tag='steering-'..label
        jsonWriteFile(job.output..'/'..tag..'-input.json',{job_id=job.id,session_id=job.session_id,physics_time=t,
          steering_degrees=electrics.values.steering,speed_m_s=speed,command=steering},true)
        obj:queueGameEngineLua(string.format('vehicleharness_bridge.capture(%q,%g,%q)',tag,t,job.id))
      end
    end
  end
  input.event('throttle',throttle,'FILTER_AI',nil,nil,nil,'cadHarness')
  input.event('brake',brake,'FILTER_AI',nil,nil,nil,'cadHarness')
  input.event('steering',steering,'FILTER_AI',nil,nil,nil,'cadHarness')
  input.event('parkingbrake',0,'FILTER_AI',nil,nil,nil,'cadHarness')
  if t>=sampleAt then
    sampleAt=t+.02;samples=samples+1
    local pos=obj:getPosition();local vel=obj:getVelocity();local delta=pos-origin;distance=distance+(pos-lastPos):length();lastPos=pos
    local broken=0;for _,b in pairs(v.data.beams) do if obj:beamIsBroken(b.cid) then broken=broken+1 end end
    if broken>0 and not firstBreak then
      firstBreak=true;local failures={}
      for _,b in pairs(v.data.beams) do if obj:beamIsBroken(b.cid) then failures[#failures+1]={cid=b.cid,a=v.data.nodes[b.id1].name or b.id1,b=v.data.nodes[b.id2].name or b.id2,spring=b.beamSpring,damp=b.beamDamp} end end
      jsonWriteFile(job.output..'/first_breaks.json',{time=t,beams=failures},true)
    end
    local relative=0;local fastest;local perComponent={}
    for _,node in ipairs(nodes) do if job.manifest.nodes[node.name] then
      local speed=(obj:getNodeVelocityVector(node.cid)-vel):length()
      if speed>relative then relative=speed;fastest=node.name end
      local owner=job.manifest.nodes[node.name].component
      perComponent[owner]=math.max(perComponent[owner] or 0,speed)
    end end
    -- Retain alignment at every telemetry sample. A second fivefold decimation
    -- hid launch toe spikes. This is still graphics-rate evidence; short
    -- transients require the separate physics-step capture.
    do
      local axes={};for _,corner in ipairs({'FL','FR','RL','RR'}) do
        local pair=job.manifest.wheels[corner].nodes
        axes[corner]=(position(byName[pair.axis_in].cid)-position(byName[pair.axis_out].cid)):length()
      end
      local mechanismPositions={}
      for _,node in ipairs(nodes) do if node.name and job.manifest.nodes[node.name] then
        -- Keep the complete explicit graph for tangent/attachment diagnostics.
        -- Limiting this to suspension bodies hid oscillating fixed accessories.
        local p=position(node.cid);mechanismPositions[node.name]={p.x,p.y,p.z}
      end end
      local referencePositions={};local actuatorLengths={};local rackTarget=nil;local rackTargets={}
      local steeringLoads={tie_rods={}}
      local function beamLoad(beam)
        local elastic,damping=obj:getBeamStressDamp(beam.cid)
        return {nodes={v.data.nodes[beam.id1].name,v.data.nodes[beam.id2].name},
          elastic_force_n=elastic,damping_force_n=damping,length_m=(position(beam.id2)-position(beam.id1)):length()}
      end
      for corner,beams in pairs(steeringTieBeams) do
        steeringLoads.tie_rods[corner]={}
        for _,beam in ipairs(beams) do table.insert(steeringLoads.tie_rods[corner],beamLoad(beam)) end
      end
      for corner,cid in pairs(toeLinkBeams) do actuatorLengths[corner]=obj:getBeamRestLength(cid) end
      for _,node in ipairs(referenceNodes) do
        local p=position(node.cid);referencePositions[node.name]={p.x,p.y,p.z}
      end
      if job.motion_reference then
        local rack=job.motion_reference.steering
        if rack and rack.kind=='translating_rack' then
          steeringLoads.actuators={}
          local declarations=rack.actuators or {{nodes=rack.actuator_nodes,rest_length_m=rack.actuator_rest_length_m,rack_motion_sign=1}}
          for _,spec in ipairs(declarations) do
            local a=byName[spec.nodes[1]];local b=byName[spec.nodes[2]];local found=false
            for _,hydro in pairs(hydros.hydros or {}) do
              local beam=hydro.beamCID and v.data.beams[hydro.beamCID]
              if beam and a and b and ((beam.id1==a.cid and beam.id2==b.cid) or (beam.id2==a.cid and beam.id1==b.cid)) then
                local target=(obj:getBeamRefLength(hydro.beamCID)*hydro.state-spec.rest_length_m)*spec.rack_motion_sign
                if found or (rackTarget and math.abs(target-rackTarget)>1e-6) then finish('failed','Rack actuator targets disagree or are duplicated');return end
                rackTarget=rackTarget or target;found=true;rackTargets[#rackTargets+1]=target
                table.insert(steeringLoads.actuators,beamLoad(beam))
              end
            end
            if not found then finish('failed','Missing declared rack actuator');return end
          end
        end
        for corner,reference in pairs(job.motion_reference.corners) do
          local inner=reference.points.tie_inner;local outer=reference.points.tie_outer
          if inner and outer then
            for _,hydro in pairs(hydros.hydros or {}) do
              if hydro.beamCID then
                local beam=v.data.beams[hydro.beamCID]
                if beam and ((beam.id1==byName[inner].cid and beam.id2==byName[outer].cid) or (beam.id2==byName[inner].cid and beam.id1==byName[outer].cid)) then
                  actuatorLengths[corner]=obj:getBeamRefLength(hydro.beamCID)*hydro.state
                end
              end
            end
          end
        end
      end
      local deviceState={};local wheelState={}
      local springState={}
      for corner,beams in pairs(coiloverBeams) do
        springState[corner]={}
        for _,beam in ipairs(beams) do
          local elastic,damping=obj:getBeamStressDamp(beam.cid)
          local separation=position(beam.id2)-position(beam.id1)
          local length=separation:length()
          local lengthRate=(obj:getNodeVelocityVector(beam.id2)-obj:getNodeVelocityVector(beam.id1)):dot(separation)/math.max(length,1e-12)
          table.insert(springState[corner],{spring_n_m=beam.beamSpring,damping_ns_m=beam.beamDamp,
            elastic_force_n=elastic,damping_force_n=damping,spawn_reference_length_m=obj:getBeamRefLength(beam.cid),
            length_m=length,length_rate_m_s=lengthRate,beam_cid=beam.cid})
        end
      end
      for name,device in pairs(powertrain.getDevices()) do
        deviceState[name]={mode=device.mode,gear_index=device.gearIndex,ratio=device.gearRatio,
          input_av=device.inputAV,output_av=device.outputAV1,output_av2=device.outputAV2,output_torque=device.outputTorque1,clutch_ratio=device.clutchRatio}
      end
      for _,wheel in pairs(wheels.wheels) do
        wheelState[wheel.name]={propulsion_torque=wheel.propulsionTorque,braking_torque=wheel.brakingTorque,friction_torque=wheel.frictionTorque,
          tire_shape=tireShape(wheel)}
      end
      local aeroForce=obj:calcTotalAeroForces()
      local aeroTorque=obj:calcTotalAeroTorque(obj:calcCenterOfGravityRel(true))
      local torsionAngles={}
      for _,bar in pairs(v.data.torsionbars or {}) do
        torsionAngles[tostring(bar.cid)]=obj:getTorsionbarAngle(bar.cid)
      end
      diagnosticSamples[#diagnosticSamples+1]={t=t,fastest_node=fastest,component_speed=perComponent,axle_length=axes,mechanism_positions=mechanismPositions,
        torsion_angles_rad=torsionAngles,
        aero_force_world_n={aeroForce.x,aeroForce.y,aeroForce.z},aero_torque_com_world_nm={aeroTorque.x,aeroTorque.y,aeroTorque.z},
        reference_positions=referencePositions,actuator_rest_lengths=actuatorLengths,rack_target_m=rackTarget,rack_targets_m=rackTargets,steering_command=steering,
        steering_applied=electrics.values.steering_input,control_filter=input.state.steering.filter,control_source=input.state.steering.source,
        devices=deviceState,wheel_torques=wheelState,coilovers=springState,steering_loads=steeringLoads,gear=electrics.values.gear,
        brake_input=electrics.values.brake,parking_input=electrics.values.parkingbrake}
    end
    local roles=job.manifest.device_contract and job.manifest.device_contract.roles or {engine='mainEngine',transmission='gearbox'}
    local engine=powertrain.getDevice(roles.engine);local gearbox=powertrain.getDevice(roles.transmission);local av={}
    for _,wheel in pairs(wheels.wheels) do av[wheel.name]=wheel.angularVelocity or 0 end
    local row={t,speed,vel:dot(forward),delta:dot(forward),delta:dot(left),distance,obj:getDirectionVectorUp().z,relative,broken,engine.outputAV1*9.5492966,gearbox.gearRatio or 0,throttle,brake,av.FL or 0,av.FR or 0,av.RL or 0,av.RR or 0}
    for _,c in ipairs({'FL','FR','RL','RR'}) do
      local hub=byName[job.manifest.wheels[c].nodes.axis_in];local mount=byName[job.manifest.wheels[c].nodes.shock_top];local initialDelta=initial[hub.cid]-initial[mount.cid]
      row[#row+1]=(position(hub.cid)-position(mount.cid)).z-initialDelta.z
    end
    for i,value in ipairs(row) do
      if value~=value or math.abs(value)>1e10 then finish('failed','Nonfinite or unstable telemetry');return end
      row[i]=string.format('%.9g',value)
    end
    file:write(table.concat(row,',')..'\n');if samples%50==0 then file:flush();jsonWriteFile(job.output..'/progress.json',{job_id=job.id,session_id=job.session_id,simulated_seconds=t},false) end
    if relative>500 or speed>200 then finish('failed','Physics instability');return end
  end
  if t>=job.duration then finish('completed') end
end
local function protected(fn)
  return function(...)
    local ok,err=pcall(fn,...)
    if not ok then
      if running then finish('failed',tostring(err))
      elseif job then
        -- A finalization failure must remain visible even after running=false.
        obj:queueGameEngineLua(string.format('vehicleharness_bridge.completed(%q,%q,%q)','failed',tostring(err),job.id))
      end
    end
  end
end
M.start=protected(start);M.onPhysicsStep=protected(onPhysicsStep);M.updateGFX=protected(updateGFX)
return M
