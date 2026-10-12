-- Frame harness vehicle extension. Measurements and force application use physics time.
local M = {}
local job, nodes, beams, probes, files, buffers, initial, metadata
local running, t, steps, sampleAt, samples, flushed, maxGap, lastSample
local peakSpeed, sumSpeed2, speedCount, peakForce, events, tickDt
local peakBeamDelta, sumBeamDelta2, beamCount
local anchorCid, anchorWorld, lastGfxTime, measurementAnchor
local previousForce, yielded, yieldPending, cutIds, cutDone, captured, firstBreakCaptured, firstYieldCaptured, damageForce

local function xyz(vv) return {vv.x, vv.y, vv.z} end
local function nodePosition(cid)
  -- Drive exposes graphics-cadence position readback even in this physics hook.
  -- Keep the raw values; velocity is the independent high-rate motion channel.
  -- getNodePositionRelativeXYZ is body-relative and must not be mixed with a
  -- world origin. This is the same transform used by Drive's world-position debug view.
  if anchorCid then
    -- The vehicle origin can update independently of cached relative positions.
    -- A fixed support gives all samples the same world reference without that jitter.
    return obj:getNodePosition(cid)-obj:getNodePosition(anchorCid)+anchorWorld
  end
  return obj:getNodePosition(cid)+obj:getPosition()
end
local function finite(x) return x == x and math.abs(x) < 1e30 end
local function row(key, values)
  local text = {}
  for i,value in ipairs(values) do text[i] = type(value)=='number' and string.format('%.10g',value) or tostring(value) end
  buffers[key][#buffers[key]+1] = table.concat(text,',')..'\n'
end
local function flush()
  for key,f in pairs(files) do
    if #buffers[key] > 0 then f:write(table.concat(buffers[key])); buffers[key]={}; f:flush() end
  end
  jsonWriteFile(job.output..'/progress.json',{job_id=job.id,session_id=job.session_id,simulated_seconds=t},false)
  local broken={}
  for _,beam in ipairs(beams) do if obj:beamIsBroken(beam.cid) then broken[tostring(beam.cid)]=true end end
  jsonWriteFile(job.output..'/visual_state.json',broken,false)
  local skin=controller.getController('cadSkin')
  jsonWriteFile(job.output..'/skin_state.json',skin and skin.getState and skin.getState() or {controller_present=false},false)
  flushed=t
end
local function finish(state, reason)
  if not running then return end
  running=false
  if job.scenario.capture then obj:queueGameEngineLua(string.format('frameharness_bridge.capture(%q,%g,%q)', 'final',t,job.id)) end
  flush()
  for _,f in pairs(files) do f:close() end
  jsonWriteFile(job.output..'/events.json', events, true)
  jsonWriteFile(job.output..'/completion.json', {
    job_id=job.id,session_id=job.session_id, status=state, reason=reason, simulated_seconds=t, physics_steps=steps,
    physics_dt=tickDt, trajectory_samples=samples, max_sample_gap_s=maxGap,
    actual_sample_hz=samples/math.max(t,1e-12), peak_node_speed_m_s=peakSpeed,
    node_speed_rms_m_s=math.sqrt(sumSpeed2/math.max(speedCount,1)),
    peak_beam_native_force=peakForce, peak_beam_length_change_m=peakBeamDelta,
    beam_length_change_rms_m=math.sqrt(sumBeamDelta2/math.max(beamCount,1))}, true)
  obj:queueGameEngineLua(string.format('frameharness_bridge.completed(%q,%q,%q)',state,reason or '',job.id))
end

local function loadForce(time)
  local s=job.scenario
  if time < s.settle_s or time >= s.settle_s+s.ramp_s+s.hold_s then return 0 end
  return s.force_n*math.min(1,(time-s.settle_s)/s.ramp_s)
end

local function sample(force)
  for _,node in ipairs(nodes) do
    local p=nodePosition(node.cid)
    local velocity=obj:getNodeVelocityVector(node.cid)
    row('nodes',{t,node.cid,p.x,p.y,p.z,velocity.x,velocity.y,velocity.z})
  end
  for _,beam in ipairs(beams) do
    row('beams',{t,beam.cid,obj:getBeamLength(beam.cid),obj:getBeamRestLength(beam.cid),
      obj:getBeamStress(beam.cid),obj:beamIsBroken(beam.cid) and 1 or 0})
  end
  row('loads',{t,force})
  maxGap=math.max(maxGap,t-lastSample); lastSample=t; samples=samples+1
end

local function start(manifest)
  obj:setSleepingEnabled(false)
  lastGfxTime=-1
  job=manifest; nodes={}; beams={}; probes={}; files={}; buffers={}; initial={}; events={}
  previousForce={}; yielded={}; yieldPending={}; cutIds={}; cutDone=false; captured=false; firstBreakCaptured=false; firstYieldCaptured=false; damageForce=0
  anchorCid=nil; anchorWorld=nil
  running=true; t=0; steps=0; sampleAt=0; samples=0; flushed=0; lastSample=0; maxGap=0
  peakSpeed=0; sumSpeed2=0; speedCount=0; peakForce=0; peakBeamDelta=0; sumBeamDelta2=0; beamCount=0
  tickDt=obj:getPhysicsDt()
  local headers={nodes='t,cid,x,y,z,vx,vy,vz\n',beams='t,cid,length,rest_length,native_force,broken\n',
    gfx='t,cid,x,y,z,ax,ay,az\n',loads='t,force_n\n',probes='t,cid,x,y,z,vx,vy,vz,force_n,fx,fy,fz,avx,avy,avz\n'}
  for key,header in pairs(headers) do
    local f,err=io.open(job.output..'/'..key..'.csv','w')
    if not f then error('Cannot open telemetry: '..tostring(err)) end
    files[key]=f; buffers[key]={}; f:write(header)
  end
  local byName={}
  for _,node in pairs(v.data.nodes) do
    nodes[#nodes+1]=node; byName[node.name]=node
  end
  for _,beam in pairs(v.data.beams) do beams[#beams+1]=beam end
  table.sort(nodes,function(a,b) return a.cid<b.cid end)
  table.sort(beams,function(a,b) return a.cid<b.cid end)
  measurementAnchor=nodes[1].cid
  local anchorName=job.scenario.fixed_nodes[1]
  if anchorName and byName[anchorName] then
    anchorCid=byName[anchorName].cid
    anchorWorld=obj:getNodePosition(anchorCid)+obj:getPosition()
  end
  metadata={job_id=job.id,session_id=job.session_id,nodes={},beams={},physics_dt=tickDt,coordinate_system='world XYZ, metres',
    telemetry_version=4, load_vectors=job.scenario.load_vectors,
    moving_measurement_anchor=not anchorName and nodes[1].name or nil,
    position_reference=anchorName and ('fixed support '..anchorName) or 'vehicle origin; rigid motion removed in idle analysis',
    position_readback_note='Raw node positions may repeat between graphics updates. Physics-hook timestamps do not imply independently refreshed positions. Use velocity for high-rate oscillation measurements.',
    beam_native_force_note='obj:getBeamStress; signed native axial force; verify sign using spring fixture',
    gravity=job.scenario.gravity}
  for _,node in ipairs(nodes) do
    local p=nodePosition(node.cid)
    metadata.nodes[#metadata.nodes+1]={cid=node.cid,name=node.name,mass=obj:getNodeMass(node.cid),
      initial=xyz(p),fixed=node.fixed or false}
    initial[node.cid]=p
  end
  for _,beam in ipairs(beams) do
    metadata.beams[#metadata.beams+1]={cid=beam.cid,id1=beam.id1,id2=beam.id2,
      spring=beam.beamSpring,damp=beam.beamDamp,deform=beam.beamDeform,strength=beam.beamStrength,
      initial_rest_length=obj:getBeamRestLength(beam.cid),initial_length=obj:getBeamLength(beam.cid)}
  end
  jsonWriteFile(job.output..'/metadata.json',metadata,true)
  if #nodes ~= job.expected_nodes or #beams ~= job.expected_beams then
    finish('failed','Compiled node/beam counts differ from staged JBeam'); return
  end
  for name,expected in pairs(job.nodes) do
    if not byName[name] then finish('failed','Missing compiled node '..name); return end
    if math.abs(obj:getNodeMass(byName[name].cid)-expected.mass)>1e-5 then
      finish('failed','Compiled mass differs for '..name); return
    end
  end
  for _,name in ipairs(job.scenario.fixed_nodes) do
    if not byName[name] or not byName[name].fixed then finish('failed','Unfixed support '..name); return end
  end
  for _,name in ipairs(job.scenario.load_nodes) do
    if not byName[name] then finish('failed','Missing load node '..name); return end
    probes[#probes+1]=byName[name]
  end
  local matched={}
  for _,expected in ipairs(job.beams) do
    local a,b=byName[expected.a].cid,byName[expected.b].cid
    local found=false
    for _,actual in ipairs(beams) do
      if not matched[actual.cid] and ((actual.id1==a and actual.id2==b) or (actual.id1==b and actual.id2==a)) then
        if expected.spring and math.abs(actual.beamSpring-expected.spring)>math.max(1e-5,expected.spring*1e-5) then
          finish('failed','Compiled spring differs for '..expected.a..'/'..expected.b); return
        end
        if expected.damp and math.abs(actual.beamDamp-expected.damp)>math.max(1e-5,expected.damp*1e-5) then
          finish('failed','Compiled damping differs for '..expected.a..'/'..expected.b); return
        end
        for _,key in ipairs({'deform','strength'}) do
          local field=key=='deform' and 'beamDeform' or 'beamStrength'
          if type(expected[key])=='number' and math.abs(actual[field]-expected[key])>math.max(1e-4,expected[key]*1e-5) then
            finish('failed','Compiled damage threshold differs for '..expected.a..'/'..expected.b); return
          end
        end
        matched[actual.cid]=true; found=true; break
      end
    end
    if not found then finish('failed','Missing compiled beam '..expected.a..'/'..expected.b); return end
  end
  for _,edge in ipairs(job.scenario.cut_edges or {}) do
    local a,b=byName[edge[1]],byName[edge[2]]
    local found=false
    if a and b then
      for _,beam in ipairs(beams) do
        if (beam.id1==a.cid and beam.id2==b.cid) or (beam.id1==b.cid and beam.id2==a.cid) then
          cutIds[#cutIds+1]=beam.cid; found=true
        end
      end
    end
    if not found then finish('failed','Controlled cut edge missing'); return end
  end
  obj:setGravity(job.scenario.gravity)
  if (job.expected_render_regions or 0)>0 then
    local skin=controller.getController('cadSkin')
    if not skin or not skin.getState or skin.getState().region_count~=job.expected_render_regions then
      finish('failed','Compiled CAD render controller missing or region count differs');return
    end
  end
  enablePhysicsStepHook()
  sample(0)
  sampleAt=1/job.scenario.sample_hz
end

local function onPhysicsStep(dt)
  if not running then return end
  steps=steps+1; t=t+dt
  local force=loadForce(t)
  damageForce=force
  if job.scenario.capture and not captured and t>=0.5 then
    captured=true; obj:queueGameEngineLua(string.format('frameharness_bridge.capture(%q,%g,%q)','before',t,job.id))
  end
  if not cutDone and #cutIds>0 and t>=job.scenario.cut_at_s then
    cutDone=true
    events[#events+1]={time=t,type='controlled_cut',cids=cutIds,external_force_n=force}
    for _,cid in ipairs(cutIds) do obj:breakBeam(cid) end
    if job.scenario.capture then obj:queueGameEngineLua(string.format('frameharness_bridge.capture(%q,%g,%q)','cut',t,job.id)) end
  end
  for _,node in ipairs(probes) do
    local direction=job.scenario.load_vectors and job.scenario.load_vectors[node.name] or {0,0,-1/#probes}
    local applied=vec3(direction[1]*force,direction[2]*force,direction[3]*force)
    obj:applyForceVector(node.cid,applied)
    local p=nodePosition(node.cid)
    local velocity=obj:getNodeVelocityVector(node.cid)
    local av=obj:getNodeVelocityVector(measurementAnchor)
    row('probes',{t,node.cid,p.x,p.y,p.z,velocity.x,velocity.y,velocity.z,applied:length(),applied.x,applied.y,applied.z,av.x,av.y,av.z})
  end
  for _,node in ipairs(nodes) do
    local velocity=obj:getNodeVelocityVector(node.cid)
    local speed2=velocity:squaredLength()
    if not finite(speed2) or speed2>1e8 then finish('unstable','Nonfinite or explosive node velocity'); return end
    peakSpeed=math.max(peakSpeed,math.sqrt(speed2)); sumSpeed2=sumSpeed2+speed2; speedCount=speedCount+1
  end
  for _,beam in ipairs(beams) do
    local value=obj:getBeamStress(beam.cid)
    local delta=obj:getBeamLength(beam.cid)-metadata.beams[_].initial_length
    if not finite(value) or not finite(delta) then finish('unstable','Nonfinite beam state'); return end
    peakForce=math.max(peakForce,math.abs(value)); peakBeamDelta=math.max(peakBeamDelta,math.abs(delta))
    sumBeamDelta2=sumBeamDelta2+delta*delta; beamCount=beamCount+1
    previousForce[beam.cid]={time=t,force=value,external_force_n=force}
    local restChange=math.abs(obj:getBeamRestLength(beam.cid)-metadata.beams[_].initial_rest_length)
    if job.scenario.expected_damage and not yielded[beam.cid] and not obj:beamIsBroken(beam.cid) then
      if restChange>1e-6 then
        if not yieldPending[beam.cid] then yieldPending[beam.cid]={time=t,external_force_n=force,native_force=value} end
        if t-yieldPending[beam.cid].time>=0.005 then
          local e=yieldPending[beam.cid]; e.type='persistent_deformation'; e.cid=beam.cid; e.confirmed_at=t; e.rest_change_m=restChange
          events[#events+1]=e; yielded[beam.cid]=true
          if job.scenario.capture and not firstYieldCaptured then
            firstYieldCaptured=true; obj:queueGameEngineLua(string.format('frameharness_bridge.capture(%q,%g,%q)','first-yield',t,job.id))
          end
        end
      else yieldPending[beam.cid]=nil end
    end
  end
  if t+1e-9 >= sampleAt then sample(force); sampleAt=sampleAt+1/job.scenario.sample_hz end
  if t-flushed >= 0.25 then flush() end
  if t+1e-9 >= job.scenario.duration then finish('completed') end
end

local function onBeamBroke(id,energy)
  if running then
    local controlled=false
    if cutDone and math.abs(t-job.scenario.cut_at_s)<0.002 then
      for _,cid in ipairs(cutIds) do if cid==id then controlled=true; break end end
    end
    events[#events+1]={time=t,type='beam_broke',cid=id,energy=energy,external_force_n=damageForce,
      previous_sample=previousForce[id],controlled=controlled}
    if job.scenario.capture and not firstBreakCaptured then
      firstBreakCaptured=true; obj:queueGameEngineLua(string.format('frameharness_bridge.capture(%q,%g,%q)','first-break',t,job.id))
    end
  end
end
local function onExtensionUnloaded()
  if running then finish('failed','Recorder unloaded before completion') end
end
M.start=function(manifest)
  local ok,err=pcall(start,manifest)
  if not ok then
    log('E','frameharness',tostring(err))
    if running then finish('failed',tostring(err)) end
  end
end
M.onPhysicsStep=function(dt)
  local ok,err=pcall(onPhysicsStep,dt)
  if not ok and running then finish('failed',tostring(err)) end
end
M.updateGFX=function()
  if not running or #probes==0 or t<=lastGfxTime then return end
  lastGfxTime=t
  for _,node in ipairs(probes) do
    local p=nodePosition(node.cid)
    local a=nodePosition(measurementAnchor)
    row('gfx',{t,node.cid,p.x,p.y,p.z,a.x,a.y,a.z})
  end
end
M.onBeamBroke=onBeamBroke
M.onExtensionUnloaded=onExtensionUnloaded
return M
