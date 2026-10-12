local M={}
function M.new(kind)
  local api={};local job,vehicleId,visuals;local phase='booting';local elapsed=0;local spawnAt=0;local heartbeat=0;local stageAt=0
  local path='/settings/'..kind..'_harness/'
  local session=jsonReadFile(path..'session.json');local sessionId=session and session.session_id
  local function status(state,reason)
    phase=state
    jsonWriteFile(path..'status.json',{state=state,reason=reason,session_id=sessionId,job_id=job and job.id},true)
  end
  local function retire()
    if visuals then visuals.dispose();visuals=nil end
    local vehicle=vehicleId and be:getObjectByID(vehicleId)
    if vehicle then vehicle:delete() end
    status('retiring')
  end
  function api.onExtensionLoaded() setExtensionUnloadMode(api,'manual');status('booting') end
  function api.onVehicleSpawned(id)
    if phase=='recording' and vehicleId==id then status('failed','Vehicle reloaded during recording');return end
    if phase~='spawning' then return end
    local vehicle=be:getObjectByID(id)
    if not vehicle or vehicle.JBeam~=job.model then return end
    vehicleId=id;visuals=require('/mods/unpacked/'..kind..'_harness/lua/ge/extensions/visuals').new(job,vehicle,kind)
    visuals.camera(1);status('recording')
    vehicle:queueLuaCommand("extensions.load('"..kind.."harness/recorder');"..kind.."harness_recorder.start("..serialize(job)..")")
  end
  function api.capture(label,physicsTime,id)
    if job and id==job.id and visuals then visuals.capture(label,physicsTime) end
  end
  function api.completed(state,reason,id)
    if job and id==job.id then status(state,reason) end
  end
  function api.onPreRender() if visuals then visuals.draw() end end
  function api.onFileChanged(filename)
    if phase=='staging' and string.find(filename,'/vehicles/',1,true) then stageAt=elapsed end
  end
  function api.onUpdate(dt)
    elapsed=elapsed+dt
    if elapsed-heartbeat>1 then
      heartbeat=elapsed
      jsonWriteFile(path..'heartbeat.json',{session_id=sessionId,job_id=job and job.id,phase=phase,
        physics_enabled=be:getEnabled(),physics_running=be:getPhysicsRunning(),time_scale=be:getSimulationTimeScale(),
        capturing=visuals and visuals.active~=nil,vehicle_id=vehicleId},false)
    end
    local control=jsonReadFile(path..'control.json')
    if control and control.session_id==sessionId then
      if control.action=='quit' then if visuals then visuals.dispose() end;shutdown(0);return end
      if control.action=='retire' and phase~='ready' and phase~='retiring' then retire() end
    end
    if phase=='booting' and elapsed>2 then core_modmanager.enableModsAfterUpdate();status('mods') end
    if phase=='mods' and core_modmanager.isReady() then
      status('loading');freeroam_freeroam.startFreeroam('/levels/smallgrid/main.level.json',nil,nil,false)
    elseif phase=='loading' and worldReadyState==2 then status('ready') end
    if phase=='retiring' and (not vehicleId or not be:getObjectByID(vehicleId)) then vehicleId=nil;status('ready') end
    if phase=='ready' and control and control.session_id==sessionId and control.action=='run' and
       (not job or control.job.id~=job.id) then
      job=control.job
      if #(job.changed_files or {})>0 then
        for _,file in ipairs(job.changed_files) do core_vehicle_manager.onFileChanged(file,'modified') end
        core_vehicles.clearCache()
      end
      -- Let the file watcher and material/JBeam hot-reload queue drain while
      -- no entity exists. Otherwise a delayed reload replaces its recorder VM.
      stageAt=elapsed;status('staging')
    end
    if phase=='staging' and elapsed-stageAt>1 then
      core_environment.setGravity(kind=='frame' and job.scenario.gravity or job.gravity)
      be:setEnabled(true);be:setSimulationTimeScale(1);status('spawning');spawnAt=elapsed
      core_vehicles.spawnNewVehicle(job.model,{config='/vehicles/'..job.model..'/'..job.config,
        pos=vec3(0,0,job.spawn_z),rot=quat(0,0,0,1),autoEnterVehicle=false,cling=false,safeSpawn=false,canSpawnAnotherVehicleCheck=false})
    end
    if phase=='spawning' and elapsed-spawnAt>40 then status('failed','Vehicle spawn timed out') end
    if visuals then
      local ok,err=pcall(function() visuals.camera(dt);visuals.update(dt) end)
      if not ok then visuals.dispose();visuals=nil;status('failed','Camera/capture error: '..tostring(err)) end
    end
  end
  return api
end
return M
