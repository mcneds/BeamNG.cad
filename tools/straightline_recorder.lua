-- Diagnostic recorder shared by unchanged stock and generated vehicles.
-- No ideal-mechanism or MVP device-name assumptions; no qualification receipt.
local M={}
local job,running,t,file,origin,forward,left,lastPos,distance,samples,steps,dtMin,dtMax
local saved={}
local speedIntegral=0
local powerFile
local compliance={}
local captureNodes={}
local function clutchEnergy(angle,spring,freeplay)
  local x=math.max(math.abs(angle)-freeplay,0)
  return spring*(x<=1 and x*x*x/3 or x*x/2-1/6)
end
local function adaptClutch()
  local base=job.adaptive_clutch
  if not base then return end
  local clutch=assert(powertrain.getDevice('clutch'));local gearbox=assert(powertrain.getDevice('gearbox'))
  local engine=assert(powertrain.getDevice('mainEngine'))
  assert(clutch.type=='centrifugalClutch' and gearbox.type=='cvtGearbox','Adaptive diagnostic requires native centrifugal clutch and CVT')
  assert(math.abs(engine.inertia-base.engine_inertia_kg_m2)<1e-10,'Compiled engine inertia differs from audited budget')
  local gearing=math.abs(gearbox.gearRatio*base.rear_reduction)
  assert(gearing>0 and gearing<=base.maximum_gearing*(1+1e-10),'CVT gearing exceeds audited budget')
  local inverseOutput=(1/base.effective_inertia_kg_m2-1/engine.inertia)/(base.maximum_gearing*base.maximum_gearing)
  local effective=1/(1/engine.inertia+gearing*gearing*inverseOutput)
  local omega=2*math.pi*base.frequency_limit_hz
  local zeta=base.damping_nm_s_rad/(2*base.effective_inertia_kg_m2*omega)
  local spring=effective*omega*omega/2;local damp=2*zeta*effective*omega
  local freeplay=clutch.clutchFreePlay*clutch.damageClutchFreePlayCoef*clutch.wearClutchFreePlayCoef
  local before=clutchEnergy(clutch.clutchAngle,clutch.lockSpring,freeplay)
  if spring>clutch.lockSpring then
    local normalized=before/spring
    local x=normalized<=1/3 and (3*normalized)^(1/3) or math.sqrt(2*normalized+1/3)
    clutch.clutchAngle=(clutch.clutchAngle<0 and -1 or 1)*(x+freeplay)
  end
  clutch.lockSpring=spring;clutch.lockSpringBase=spring;clutch.lockDamp=damp
  clutch.lockDampRatio=damp/math.sqrt(spring*clutch.cumulativeInertia)
  clutch.maxClutchAngle=math.sqrt(clutch.lockTorque/spring)+math.max(clutch.lockTorque/spring-1,0)
  local after=clutchEnergy(clutch.clutchAngle,spring,freeplay)
  local dt=base.step_seconds
  compliance={eigenvalue=(dt*dt*2*spring+2*dt*damp)/effective,energy_before=before,energy_after=after}
  assert(after<=before+1e-8,'Compliance adjustment injected spring energy')
  assert(compliance.eigenvalue<=base.step_eigenvalue+1e-10,'Compliance adjustment exceeded stability bound')
end
local function position(id) return obj:getNodePosition(id)+obj:getPosition() end
local function xyz(p) return {p.x,p.y,p.z} end
local function finish(state,reason)
  if not running then return end
  running=false
  if file then file:flush();file:close();file=nil end
  if powerFile then powerFile:flush();powerFile:close();powerFile=nil end
  for name,value in pairs(saved) do input.allowedInputSources[name]=value end
  jsonWriteFile(job.output..'/completion.json',{status=state,reason=reason,job_id=job.id,
    session_id=job.session_id,samples=samples,simulated_seconds=t,physics_steps=steps,
    physics_dt_min=dtMin,physics_dt_max=dtMax},true)
  obj:queueGameEngineLua(string.format('vehicleharness_bridge.completed(%q,%q,%q)',state,reason or '',job.id))
end
local function start(j)
  job=j;running=true;t=0;samples=0;steps=0;dtMin=math.huge;dtMax=0;distance=0
  speedIntegral=0;compliance={};captureNodes={}
  origin=obj:getPosition();lastPos=origin
  forward=obj:getDirectionVector();forward.z=0;forward:normalize()
  left=vec3(0,0,1):cross(forward)
  obj:setSleepingEnabled(false)
  saved={}
  for _,name in ipairs({'steering','throttle','brake','parkingbrake'}) do
    saved[name]=input.allowedInputSources[name]
    input.allowedInputSources[name]={cadHarness=true}
  end
  local clutchOverride
  if job.native_clutch_defaults then
    local clutch=assert(powertrain.getDevice('clutch'))
    assert(clutch.type=='centrifugalClutch','Native-default diagnostic requires centrifugalClutch')
    clutchOverride={previous_spring=clutch.lockSpring,previous_damp=clutch.lockDamp,
      previous_spring_base=clutch.lockSpringBase,previous_damp_ratio=clutch.lockDampRatio,
      warning='Diagnostic ignores the candidate housing recoil bound; no qualification'}
    clutch.lockSpringBase=nil;clutch.lockSpringCoef=1;clutch.lockDampRatio=.15
    clutch:calculateInertia()
    clutchOverride.native_spring=clutch.lockSpring;clutchOverride.native_damp=clutch.lockDamp
    assert(clutch.lockSpring>0 and clutch.lockDamp>=0,'Invalid native defaults')
  end
  local nodes,beams,devices,controllers,wheelData={},{},{},{},{}
  local mass=0
  for _,n in pairs(v.data.nodes) do
    local m=obj:getNodeMass(n.cid);mass=mass+m
    nodes[#nodes+1]={id=n.cid,name=n.name,mass_kg=m,position=xyz(position(n.cid))}
    for _,name in ipairs(job.capture_node_names or {}) do
      if name==n.name then
        assert(captureNodes[name]==nil,'Duplicate captured node name')
        captureNodes[name]=n.cid
      end
    end
  end
  for _,name in ipairs(job.capture_node_names or {}) do assert(captureNodes[name]~=nil,'Missing captured node '..name) end
  for _,b in pairs(v.data.beams) do
    beams[#beams+1]={id=b.cid,a=b.id1,b=b.id2,spring=b.beamSpring,damp=b.beamDamp,type=b.beamType}
  end
  for name,d in pairs(powertrain.getDevices()) do
    devices[name]={type=d.type,input_name=d.inputName,input_index=d.inputIndex,
      gear_ratio=d.gearRatio,gear_index=d.gearIndex,mode=d.mode,
      torque_reaction_nodes=d.torqueReactionNodes,cumulative_inertia=d.cumulativeInertia,
      lock_spring=d.lockSpring,lock_damp=d.lockDamp}
  end
  for name,c in pairs(controller.getAllControllers()) do controllers[#controllers+1]={name=name,type=c.type} end
  for _,w in pairs(wheels.wheels) do
    wheelData[#wheelData+1]={name=w.name,node1=w.node1,node2=w.node2,wheelDir=w.wheelDir,
      torsion_reactor=w.torsionReactor and w.torsionReactor.name,
      torsion_reactor_index=w.torsionReactorIdx}
  end
  jsonWriteFile(job.output..'/compiled.json',{job_id=job.id,model=job.model,config=v.config,
    mass_kg=mass,nodes=nodes,beams=beams,devices=devices,controllers=controllers,wheels=wheelData,
    diagnostic_clutch_override=clutchOverride},true)
  file=assert(io.open(job.output..'/straight.csv','w'))
  powerFile=assert(io.open(job.output..'/powertrain.csv','w'))
  powerFile:write('physics_t,gfx_t,speed,engine_av,clutch_input_av,clutch_output_av,clutch_torque,clutch_angle,clutch_ratio,clutch_spring,clutch_damp,cvt_ratio,cvt_output_av,throttle,brake,compliance_eigenvalue,energy_before_adjustment,energy_after_adjustment\n')
  file:write('t,speed,forward_speed,forward_distance,lateral_distance,distance,heading_rad,up_z,steering_command,steering_applied,throttle_command,throttle_applied,brake_applied,parking_applied,broken,x,y,z\n')
  controller.mainController.setGearboxMode('realistic')
  controller.mainController.shiftToGearIndex(job.gear_index or 2)
  electrics.setIgnitionLevel(3)
  enablePhysicsStepHook()
end
function M.start(j)
  local ok,err=pcall(start,j)
  if not ok then finish('failed',tostring(err)) end
end
function M.onPhysicsStep(dt)
  if running then
    steps=steps+1;dtMin=math.min(dtMin,dt);dtMax=math.max(dtMax,dt)
    if steps%20==0 then
      local engine=powertrain.getDevice('mainEngine');local clutch=powertrain.getDevice('clutch');local gearbox=powertrain.getDevice('gearbox')
      local e=electrics.values
      local row={steps*dt,t,obj:getVelocity():length(),engine and engine.outputAV1 or 0,
        clutch and clutch.inputAV or 0,clutch and clutch.outputAV1 or 0,
        clutch and clutch.torqueDiff or 0,clutch and clutch.clutchAngle or 0,
        clutch and clutch.clutchRatio or 0,clutch and clutch.lockSpring or 0,
        clutch and clutch.lockDamp or 0,gearbox and gearbox.gearRatio or 0,
        gearbox and gearbox.outputAV1 or 0,e.throttle or 0,e.brake or 0,
        compliance.eigenvalue or 0,compliance.energy_before or 0,compliance.energy_after or 0}
      for i,value in ipairs(row) do
        if value~=value or math.abs(value)==math.huge then finish('failed','Nonfinite powertrain telemetry');return end
        row[i]=string.format('%.12g',value)
      end
      powerFile:write(table.concat(row,',')..'\n')
    end
  end
end
local function update(dt)
  t=t+dt
  if t>1 and t<1.2 then electrics.setIgnitionLevel(2) end
  local throttle=t>4 and 1 or 0
  local brake=0
  if job.target_speed and t>4 then
    local target=math.min(job.target_speed,t-4)
    local error=target-obj:getVelocity():length()
    local kp=job.speed_kp or .5;local ki=job.speed_ki or .2
    local demand=kp*error+speedIntegral
    if (demand<1 or error<0) and (demand>0 or error>0) then
      speedIntegral=math.max(-.3,math.min(1,speedIntegral+error*dt*ki))
    end
    throttle=math.max(0,math.min(1,kp*error+speedIntegral))
    if error<-.5 then brake=math.min(.3,-.25*error) end
  end
  if job.coast_at and t>=job.coast_at then throttle=0 end
  input.event('throttle',throttle,'FILTER_AI',nil,nil,nil,'cadHarness')
  input.event('brake',brake,'FILTER_AI',nil,nil,nil,'cadHarness')
  input.event('steering',0,'FILTER_AI',nil,nil,nil,'cadHarness')
  input.event('parkingbrake',0,'FILTER_AI',nil,nil,nil,'cadHarness')
  if job.fixed_cvt_ratio and t>=job.fixed_cvt_after then
    local gearbox=assert(powertrain.getDevice('gearbox'))
    assert(gearbox.type=='cvtGearbox','Fixed-ratio diagnostic requires a CVT')
    gearbox:setGearRatio(job.fixed_cvt_ratio)
  end
  adaptClutch()
  local p=obj:getPosition();local delta=p-origin;local vel=obj:getVelocity()
  distance=distance+(p-lastPos):length();lastPos=p;samples=samples+1
  local direction=obj:getDirectionVector()
  local heading=math.atan2(direction:dot(left),direction:dot(forward))
  local broken=0
  for _,b in pairs(v.data.beams) do if obj:beamIsBroken(b.cid) then broken=broken+1 end end
  local e=electrics.values
  local row={t,vel:length(),vel:dot(forward),delta:dot(forward),delta:dot(left),distance,heading,
    obj:getDirectionVectorUp().z,0,e.steering_input or 0,throttle,e.throttle or 0,
    e.brake or 0,e.parkingbrake or 0,broken,p.x,p.y,p.z}
  for i,value in ipairs(row) do row[i]=string.format('%.12g',value) end
  file:write(table.concat(row,',')..'\n')
  if samples%5==1 then
    local wheelState={};local hydroState={};local deviceState={}
    for _,w in pairs(wheels.wheels) do
      wheelState[w.name]={axis=xyz(position(w.node2)-position(w.node1)),
        center=xyz((position(w.node1)+position(w.node2))*.5),av=w.angularVelocity,
        down_force=w.downForceRaw,side_slip=w.lastSideSlip,
        propulsion_torque=w.propulsionTorque,braking_torque=w.brakingTorque,
        engine_reaction_torque=w.coreData and w.coreData.engineReactionTorque,
        torsion_reactor=w.torsionReactor and w.torsionReactor.name}
    end
    for _,h in pairs(hydros.hydros or {}) do
      local b=h.beamCID and v.data.beams[h.beamCID]
      if b and h.inputSource=='steering_input' then
        hydroState[#hydroState+1]={a=b.id1,b=b.id2,a_world=xyz(position(b.id1)),b_world=xyz(position(b.id2))}
      end
    end
    for name,d in pairs(powertrain.getDevices()) do
      deviceState[name]={gear_index=d.gearIndex,ratio=d.gearRatio,input_av=d.inputAV,output_av=d.outputAV1,mode=d.mode,
        torque=d.outputTorque1,clutch_angle=d.clutchAngle,clutch_ratio=d.clutchRatio}
    end
    local record={t=t,wheels=wheelState,hydros=hydroState,devices=deviceState,gear=e.gear,
      steering_applied=e.steering_input,steering_source=input.state.steering.source,
      steering_filter=input.state.steering.filter,esc=e.escActive,tcs=e.tcsActive}
    if job.capture_node_names then
      record.reference_positions={}
      for name,id in pairs(captureNodes) do record.reference_positions[name]=xyz(position(id)) end
    end
    local f=assert(io.open(job.output..'/motion.jsonl','a'));f:write(jsonEncode(record)..'\n');f:close()
    jsonWriteFile(job.output..'/progress.json',{simulated_seconds=t},false)
  end
  if t>=job.duration then finish('completed') end
end
function M.updateGFX(dt)
  if not running then return end
  local ok,err=pcall(update,dt)
  if not ok then finish('failed',tostring(err)) end
end
return M
