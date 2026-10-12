-- Diagnostic only: separate lanes, production per-vehicle recorders, no receipts.
local M={}
function M.new(kind)
  assert(kind=='vehicle','Multi-car probe only supports vehicles')
  local api={};local job;local phase='booting';local elapsed=0;local stageAt=0
  local path='/settings/vehicle_harness/'
  local session=jsonReadFile(path..'session.json');local sessionId=session.session_id
  local vehicles,slots,finished,armed={},{},{},{}
  local pending;local nextIndex=1;local spawnAt=0
  local function status(state,reason)
    phase=state
    jsonWriteFile(path..'status.json',{state=state,reason=reason,session_id=sessionId,job_id=job and job.id},true)
  end
  function api.onExtensionLoaded() setExtensionUnloadMode(api,'manual');status('booting') end
  function api.onVehicleSpawned(id)
    if phase=='recording' and vehicles[id] then status('failed','Vehicle reloaded during recording');return end
    if phase~='spawning' or not pending then return end
    local vehicle=be:getObjectByID(id)
    if not vehicle or vehicle.JBeam~=pending.model then return end
    vehicles[id]=pending;slots[pending.id]=id;pending=nil
  end
  function api.capture() end -- This probe deliberately has no rendered qualification.
  function api.armed(id)
    if phase~='arming' or not slots[id] then return end
    armed[id]=true
    for _,child in ipairs(job.children) do if not armed[child.id] then return end end
    be:setSimulationTimeScale(1);be:setEnabled(true);status('recording')
  end
  function api.completed(state,reason,id)
    if not slots[id] then return end
    if state~='completed' then status('failed',id..': '..tostring(reason));return end
    finished[id]=true
    for _,child in ipairs(job.children) do if not finished[child.id] then return end end
    local result={job_id=job.id,session_id=sessionId,status='completed',children=slots,simulated_seconds=job.duration}
    assert(jsonWriteFile(job.output..'/completion.json.tmp',result,false))
    assert(FS:renameFile(job.output..'/completion.json.tmp',job.output..'/completion.json')==0)
    be:setEnabled(false);status('completed')
  end
  function api.onFileChanged(filename)
    if phase=='staging' and string.find(filename,'/vehicles/',1,true) then stageAt=elapsed end
  end
  function api.onUpdate(dt)
    elapsed=elapsed+dt
    local control=jsonReadFile(path..'control.json')
    if control and control.session_id==sessionId then
      if control.action=='quit' then shutdown(0);return end
      if control.action=='retire' and phase~='ready' and phase~='retiring' then
        be:setEnabled(false)
        for id in pairs(vehicles) do local v=be:getObjectByID(id);if v then v:delete() end end
        status('retiring')
      end
    end
    if phase=='booting' and elapsed>2 then core_modmanager.enableModsAfterUpdate();status('mods') end
    if phase=='mods' and core_modmanager.isReady() then
      status('loading');freeroam_freeroam.startFreeroam('/levels/smallgrid/main.level.json',nil,nil,false)
    elseif phase=='loading' and worldReadyState==2 then status('ready') end
    if phase=='retiring' then
      for id in pairs(vehicles) do if be:getObjectByID(id) then return end end
      vehicles={};slots={};finished={};armed={};pending=nil;collectgarbage('collect');status('ready')
    end
    if phase=='ready' and control and control.session_id==sessionId and control.action=='run' and
       (not job or job.id~=control.job_id) then
      job=jsonReadFile(control.job_file);assert(job and job.id==control.job_id,'Batch payload identity differs')
      nextIndex=1;vehicles={};slots={};finished={};armed={};pending=nil
      assert(#job.children>=1 and #job.children<=2,'Bounded two-car diagnostic')
      if #(job.changed_files or {})>0 then
        for _,file in ipairs(job.changed_files) do core_vehicle_manager.onFileChanged(file,'modified') end
        core_vehicles.clearCache()
      end
      be:setSimulationTimeScale(0);be:setEnabled(false);stageAt=elapsed;status('staging')
    end
    if phase=='staging' and elapsed-stageAt>1 then
      core_environment.setGravity(job.gravity);be:setPhysicsDeterministic(true);be:setSimulationTimeScale(0)
      spawnAt=elapsed;status('spawning')
    end
    if phase=='spawning' then
      if elapsed-spawnAt>90 then status('failed','Multi-car spawn timed out');return end
      if not pending and nextIndex<=#job.children then
        pending=job.children[nextIndex];nextIndex=nextIndex+1
        core_vehicles.spawnNewVehicle(pending.model,{config='/vehicles/'..pending.model..'/'..pending.config,
          pos=vec3(pending.lane_x,0,pending.spawn_z),rot=quat(0,0,0,1),autoEnterVehicle=false,
          cling=false,safeSpawn=false,canSpawnAnotherVehicleCheck=false})
      elseif not pending and nextIndex>#job.children then
        status('arming');spawnAt=elapsed
        for id,child in pairs(vehicles) do
          be:getObjectByID(id):queueLuaCommand("extensions.load('vehicleharness/recorder');vehicleharness_recorder.start("..
            serialize(child)..");obj:queueGameEngineLua("..string.format('%q','vehicleharness_bridge.armed('..string.format('%q',child.id)..')')..")")
        end
      end
    end
    if phase=='arming' and elapsed-spawnAt>30 then status('failed','Recorder readiness timed out') end
    if phase=='recording' then
      for id,child in pairs(vehicles) do
        local v=be:getObjectByID(id)
        if not v then status('failed','Recorded vehicle missing');return end
        local p=v:getPosition()
        if math.abs(p.x-child.lane_x)>20 or math.abs(p.y)>20 then status('failed','Vehicle left isolated lane');return end
      end
    end
  end
  return api
end
return M
