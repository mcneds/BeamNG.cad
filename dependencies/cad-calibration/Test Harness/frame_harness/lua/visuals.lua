-- Owned render views leave global UI visibility, AA, and the player camera alone.
local M={}
function M.new(job,vehicle,kind)
  local self={queue={},seen={},active=nil,failed=false,final=false}
  -- This extension runs exclusively in the harness-owned process/profile.
  -- A secondary render view does not inherit the main camera's focal distance.
  local dof=scenetree.findObject('DOFPostEffect')
  if dof then dof:disable() end
  local data=core_vehicle_manager.getVehicleData(vehicle:getID())
  local graph=data and data.vdata
  local cameraCenter,cameraDistance,previousVehiclePosition
  local maximumCameraCenterError=0
  local cameraSet=false
  local function steeringProp()
    for owner,binding in pairs(job.manifest and job.manifest.rigid_render or {}) do
      if binding.steering then
        local name=binding.steering.meshes[1]
        for _,body in pairs(graph and graph.props or {}) do
          if (body.originalMesh or body.mesh)==name then return vehicle:getProp(body.pid),binding,owner end
        end
      end
    end
  end
  local function bounds()
    local lo=vec3(math.huge,math.huge,math.huge);local hi=-lo;local origin=vehicle:getPosition()
    for i=0,vehicle:getNodeCount()-1 do
      local p=vehicle:getNodePosition(i)+origin
      lo.x=math.min(lo.x,p.x);lo.y=math.min(lo.y,p.y);lo.z=math.min(lo.z,p.z)
      hi.x=math.max(hi.x,p.x);hi.y=math.max(hi.y,p.y);hi.z=math.max(hi.z,p.z)
    end
    return (lo+hi)*.5, math.max((hi-lo):length()*.5,.05)
  end
  local function pose(view)
    local center,radius=bounds()
    local forward=vehicle:getDirectionVector();local right=forward:cross(vec3(0,0,1)):normalized()
    local offset=view=='front' and forward or (view=='side' and right or (right-forward+vec3(0,0,.8)):normalized())
    if view=='steering' then
      local prop,binding=steeringProp();assert(prop,'Steering diagnostic has no native prop')
      local matrix=prop:getLiveTransformWorld()
      -- Like the native prop editor, add the vehicle translation: the API's
      -- "World" matrix rotates globally but its position is vehicle-relative.
      center=matrix:getColumn(3)+vehicle:getPosition();radius=math.max(binding.steering.Radius,.08)
      offset=(matrix:getColumn(2)+vec3(0,0,.12)):normalized()
    end
    if view:sub(1,9)=='coilover:' then
      local owner=view:sub(10);local binding=job.manifest.coilover_render[owner]
      local vehicleCenter=center
      local named={};for _,n in pairs(graph.nodes) do if n.name then named[n.name]=n.cid end end
      local origin=vehicle:getPosition()
      local a=vehicle:getNodePosition(named[binding.top])+origin
      local b=vehicle:getNodePosition(named[binding.bottom])+origin
      center=(a+b)*.5;radius=math.max((a-b):length()*.65,.15)
      -- Look from this corner's outside, below the roof. One fixed oblique
      -- direction looks through the roof/body on the opposite pair of corners.
      local side=center-vehicleCenter;side=side-forward*side:dot(forward);side.z=0
      if side:length()<.001 then side=right end
      local front=job.manifest.component_roles[owner]:sub(1,1)=='f'
      offset=(side:normalized()+forward*(front and .65 or -.65)+vec3(0,0,.15)):normalized()
    end
    local distance=radius/math.sin(math.rad(45)/2)*1.2
    return center,center+offset*distance,distance
  end
  function self.camera(dt)
    local center,_,distance=pose('oblique');local blend=math.min(1,dt*4)
    local vehiclePosition=vehicle:getPosition()
    -- Smooth changes within the vehicle's frame, not its world translation.
    -- Smoothing absolute position trails a fast vehicle by speed / 4 metres,
    -- which can put it outside the camera's otherwise correctly sized view.
    if cameraCenter and previousVehiclePosition then
      cameraCenter=cameraCenter+(vehiclePosition-previousVehiclePosition)
    end
    previousVehiclePosition=vec3(vehiclePosition)
    cameraCenter=cameraCenter and (cameraCenter+(center-cameraCenter)*blend) or center
    maximumCameraCenterError=math.max(maximumCameraCenterError,(cameraCenter-center):length())
    cameraDistance=cameraDistance and math.max(distance,cameraDistance+(distance-cameraDistance)*blend) or distance
    local pos=cameraCenter+vec3(1,-1,.8):normalized()*cameraDistance
    if not cameraSet then core_camera.setByName(0,'free');cameraSet=true end
    core_camera.globalCameraFunction('free','setPosition',pos)
    core_camera.globalCameraFunction('free','setRotation',quatFromDir(cameraCenter-pos))
    core_camera.globalCameraFunction('free','setFOV',45)
  end
  local function writeStatus()
    jsonWriteFile(job.output..'/capture_status.json',{job_id=job.id,session_id=job.session_id,
      done=self.final and not self.active and #self.queue==0,success=not self.failed,required=self.seen},true)
  end
  local function renderState()
    local state={antialias=settings.getValue('GraphicAntialias'),antialias_type=settings.getValue('GraphicAntialiasType'),
      physics_enabled=be:getEnabled(),simulation_time_scale=be:getSimulationTimeScale()}
    for _,name in ipairs({'DOFPostEffect','MotionBlurFX','PostFxMotionBlur','ScreenBlurFX'}) do
      local effect=scenetree.findObject(name)
      if effect then local ok,value=pcall(function() return effect:isEnabled() end);if ok then state[name]=value end end
    end
    return state
  end
  local function auditMeshes()
    if kind~='vehicle' or not job.manifest or not job.manifest.component_meshes then return end
    local counts={};local missing={};local props={};local transforms={}
    for _,body in pairs(graph and graph.flexbodies or {}) do
      local mesh=body.fid and vehicle:getFlexmesh(body.fid)
      counts[body.mesh]=mesh and mesh:getVertexCount() or 0
    end
    for _,body in pairs(graph and graph.props or {}) do
      local prop=body.pid and vehicle:getProp(body.pid)
      props[body.originalMesh or body.mesh]=prop~=nil and prop:getMeshName()~=''
      if prop then
        local function xyz(p) return {p.x,p.y,p.z} end
        local matrix=prop:getLiveTransformWorld()
        transforms[body.originalMesh or body.mesh]={base_translation=xyz(prop:getBaseTranslationGlobal()),
          columns={xyz(matrix:getColumn(0)),xyz(matrix:getColumn(1)),xyz(matrix:getColumn(2)),xyz(matrix:getColumn(3))},
          ref_name=graph.nodes[body.idRef].name,ref_position=xyz(vehicle:getNodePosition(body.idRef)),
          vehicle_position=xyz(vehicle:getPosition())}
      end
    end
    for _,names in pairs(job.manifest.component_meshes) do
      for _,name in ipairs(names) do if (not counts[name] or counts[name]<=0) and props[name]~=true then missing[#missing+1]=name end end
    end
    table.sort(missing)
    jsonWriteFile(job.output..'/render_meshes.json',{job_id=job.id,session_id=job.session_id,vertices=counts,props=props,prop_transforms=transforms,missing=missing,success=#missing==0},true)
  end
  function self.capture(label,physicsTime)
    if self.seen[label] then return end
    self.seen[label]=true;if label=='final' then self.final=true end
    local views=kind=='frame' and {'front','side','oblique'} or {'oblique'}
    if label:sub(1,9)=='steering-' then views={'steering'} end
    local coil=label:match('^coilover%-(.+)%-%-[^-]+$')
    if coil then views={'coilover:'..coil} end
    for _,view in ipairs(views) do
      self.queue[#self.queue+1]={label=label,view=view,time=physicsTime}
    end
    if kind=='vehicle' and label=='final' then
      self.seen['final-side']=true
      self.queue[#self.queue+1]={label='final-side',view='side',time=physicsTime}
    end
    writeStatus()
  end
  local function release()
    if self.active then
      -- Keep this job's render view and temporal exposure history between captures.
      -- Recreating it for each angle can produce washed-out intermediate images.
      for _,effect in ipairs(self.active.restoreEffects or {}) do
        if effect.enabled then effect.object:enable() else effect.object:disable() end
      end
      be:setSimulationTimeScale(self.active.timeScale)
      be:setEnabled(self.active.physics);self.active=nil
    end
  end
  function self.dispose()
    release();self.queue={}
    if self.render then RenderViewManagerInstance:destroyView(self.render);self.render=nil end
  end
  function self.draw()
    if not graph or kind~='frame' then return end
    local origin=vehicle:getPosition()
    local instrument=string.sub(job.scenario.name,1,6)=='spring'
    local broken=jsonReadFile(job.output..'/visual_state.json') or {}
    if instrument then
      for _,beam in pairs(graph.beams) do
        if not broken[tostring(beam.cid)] then
          debugDrawer:drawLine(vehicle:getNodePosition(beam.id1)+origin,vehicle:getNodePosition(beam.id2)+origin,ColorF(1,.5,0,1))
        end
      end
    end
    for _,node in pairs(graph.nodes) do
      local load=job.scenario.load_vectors[node.name]
      if instrument or node.fixed or load then
        local p=vehicle:getNodePosition(node.cid)+origin
        debugDrawer:drawSphere(p,.015,node.fixed and ColorF(.2,.6,1,1) or ColorF(1,.6,.1,1))
        if load then debugDrawer:drawLine(p,p+vec3(load[1],load[2],load[3])*.3,ColorF(1,.1,.1,1)) end
      end
    end
  end
  local function configureView(view,a)
    local rotation=a.rotation
    local matrix=QuatF(rotation.x,rotation.y,rotation.z,rotation.w):getMatrix();matrix:setPosition(a.pos)
    view.luaOwned=true;view.renderCubemap=false;view.cameraMatrix=matrix
    view.resolution=Point2I(1280,720);view.viewPort=RectI(0,0,1280,720)
    view.namedTexTargetColor=a.targetName;view.renderEditorIcons=false
    view.useManualEV=a.exposure~=nil;view.manualEV=a.exposure or 0
    view.frustum=Frustum.construct(false,math.rad(45),1280/720,.01,2000);view.fov=45
  end
  local function readbackQuality(filename)
    local bitmap=GBitmap()
    if not bitmap:loadFile(filename) then return {usable=false,reason='Cannot decode saved capture'} end
    local white,black,count=0,0,0;local color=ColorI(0,0,0,255)
    local width,height=bitmap:getWidth(),bitmap:getHeight()
    for y=0,35 do for x=0,63 do
      if not bitmap:getColor(math.floor((x+.5)*width/64),math.floor((y+.5)*height/36),color) then
        return {usable=false,reason='Cannot sample saved capture'}
      end
      count=count+1
      if math.min(color.red,color.green,color.blue)>=250 then white=white+1 end
      if math.max(color.red,color.green,color.blue)<=5 then black=black+1 end
    end end
    return {usable=white/count<.99 and black/count<.99,white_fraction=white/count,black_fraction=black/count}
  end
  function self.update(dt)
    if self.active then
      self.active.elapsed=self.active.elapsed+dt;self.active.frames=self.active.frames+1
      if self.active.frames==1 then
        -- Freeze first, then frame the settled graphics state. The physics VM
        -- and render interpolation can still have one queued update when the
        -- capture request first reaches the GE VM.
        local a=self.active
        a.center,a.pos=pose(a.request.view);a.rotation=quatFromDir(a.center-a.pos)
        configureView(a.render,a)
        return
      end
      -- Time alone is insufficient on a slow workstation: the old 0.5 s wait
      -- sometimes captured only four frames of an uninitialized HDR history.
      if self.active.elapsed<1 or self.active.frames<8 then return end
      local a=self.active
      if a.retryAt and a.elapsed<a.retryAt then return end
      if a.request.label=='final' and not a.attempts then auditMeshes() end
      if a.request.view=='steering' and not a.attempts then
        local record=jsonReadFile(job.output..'/'..a.request.label..'-input.json')
        assert(record and record.job_id==job.id and record.session_id==job.session_id,'Steering capture input identity differs')
        record.props={}
        local function xyz(p) return {p.x,p.y,p.z} end
        local named={};for _,n in pairs(graph.nodes) do if n.name then named[n.name]=n.cid end end
        for _,binding in pairs(job.manifest.rigid_render or {}) do
          if binding.steering then
            for _,name in ipairs(binding.steering.meshes) do
              for _,body in pairs(graph.props or {}) do
                if (body.originalMesh or body.mesh)==name then
                  local prop=vehicle:getProp(body.pid);local matrix=prop:getLiveTransformWorld();local refs={}
                  for _,n in ipairs(binding.nodes) do refs[n]=xyz(vehicle:getNodePosition(named[n])+vehicle:getPosition()) end
                  record.props[name]={columns={xyz(matrix:getColumn(0)),xyz(matrix:getColumn(1)),xyz(matrix:getColumn(2)),xyz(matrix:getColumn(3)+vehicle:getPosition())},reference_nodes=refs,coordinate_space='world'}
                end
              end
            end
          end
        end
        jsonWriteFile(job.output..'/'..a.request.label..'.json',record,true)
      end
      local ok,result=pcall(function() return a.render:saveToDisk(a.filename) end)
      local success=ok and result and FS:fileExists(a.filename)
      local quality=success and readbackQuality(a.filename) or nil
      local readable=success
      success=success and quality.usable
      a.attempts=a.attempts or {}
      a.attempts[#a.attempts+1]={elapsed=a.elapsed,frames=a.frames,save_call_ok=ok,save_result=tostring(result),file_exists=FS:fileExists(a.filename),quality=quality}
      -- GPU readback can transiently fail even after the render view has drawn.
      -- Retry the identical frozen pose, without replaying or advancing physics.
      -- Evidence remains mandatory after the bounded three attempts.
      if not success and #a.attempts<3 then
        if readable then
          -- Preserve the rejected readback, then let this view's exposure
          -- history settle further at the SAME frozen physics pose.
          FS:copyFile(a.filename,a.filename..'.attempt-'..#a.attempts..'.png')
          a.retryAt=a.elapsed+1
          jsonWriteFile(a.filename..'.json',{job_id=job.id,success=false,retrying=true,attempts=a.attempts},true)
          return
        end
        -- A failed target can remain unreadable indefinitely. Allocate a fresh
        -- target for the same frozen pose/exposure; never repeat the physics run.
        RenderViewManagerInstance:destroyView(a.render)
        a.targetName='cadHarness-'..job.id..'-retry-'..#a.attempts
        a.render=RenderViewManagerInstance:getOrCreateView(a.targetName);self.render=a.render
        configureView(a.render,a)
        a.retryAt=a.elapsed+.5
        jsonWriteFile(a.filename..'.json',{job_id=job.id,success=false,retrying=true,attempts=a.attempts},true)
        return
      end
      self.failed=self.failed or not success
      local captureState=renderState()
      release()
      jsonWriteFile(a.filename..'.json',{job_id=job.id,success=success,requested_physics_time=a.request.time,
        save_call_ok=ok,save_result=tostring(result),file_exists=FS:fileExists(a.filename),render_frames=a.frames,
        manual_ev=a.exposure,quality=quality,camera_center={a.center.x,a.center.y,a.center.z},camera_position={a.pos.x,a.pos.y,a.pos.z},render_state=captureState,
        live_camera_max_center_error_m=maximumCameraCenterError,
        render_state_before=a.renderStateBefore,render_state_restored=renderState(),attempts=a.attempts},true)
      writeStatus();return
    end
    if #self.queue==0 then return end
    local request=table.remove(self.queue,1)
    local center,pos=pose(request.view);local rotation=quatFromDir(center-pos)
    local view=self.render or RenderViewManagerInstance:getOrCreateView('cadHarness-'..job.id)
    self.render=view
    self.active={render=view,physics=be:getEnabled(),timeScale=be:getSimulationTimeScale(),elapsed=0,frames=0,request=request,center=center,
      pos=pos,rotation=rotation,targetName='cadHarness-'..job.id,
      filename=job.output..'/'..request.label:gsub(':','-')..(kind=='frame' and ('-'..request.view) or '')..'.png'}
    self.active.renderStateBefore=renderState();self.active.restoreEffects={}
    -- UI blur rectangles and motion-vector histories belong to the main view.
    -- Current Drive uses PostFxMotionBlur; MotionBlurFX is a legacy effect and
    -- can report disabled while the current effect is still active.
    -- Restore all existing effects on completion, failed readback and disposal.
    for _,name in ipairs({'ScreenBlurFX','PostFxMotionBlur','MotionBlurFX'}) do
      local effect=scenetree.findObject(name)
      if effect then
        self.active.restoreEffects[#self.active.restoreEffects+1]={object=effect,enabled=effect:isEnabled()}
        effect:disable()
      end
    end
    -- Match the native pause semantics without UI hooks or pause sounds.
    -- Disabling physics alone leaves a nonzero graphics simulation timescale.
    be:setSimulationTimeScale(0)
    be:setEnabled(false)
    local exposureObject=scenetree.findObject('PostEffectLocalExposureObject')
    local exposure=exposureObject and exposureObject.manualEV or nil
    self.active.exposure=exposure;configureView(view,self.active)
  end
  return self
end
return M
