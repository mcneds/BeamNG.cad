-- Opt-in, bounded physics-step positions. Ordinary acceptance recordings are unchanged.
local M={}
function M.new(job,byName)
  local config=job.frequency_capture
  if not config then return nil end
  assert(config.start_s>=0 and config.duration_s>0 and config.duration_s<=8,'Invalid frequency window')
  assert(#config.nodes>=3 and #config.nodes<=80,'Invalid frequency node count')
  local ids={};local header={'physics_s','control_s'}
  for _,name in ipairs(config.nodes) do
    assert(byName[name],'Missing frequency node '..name)
    ids[#ids+1]=byName[name].cid
    for _,axis in ipairs({'x','y','z'}) do header[#header+1]=name..'_'..axis end
  end
  local file=assert(io.open(job.output..'/frequency.csv','w'))
  file:write(table.concat(header,',')..'\n')
  -- Twelve sufficient statistics reproduce the full weighted chassis fit
  -- without writing every chassis node at every physics step.
  local chassisFile,chassisRows,chassisCenter=nil,{},vec3(0,0,0)
  if config.full_chassis_registration then
    local names=job.motion_reference.chassis
    assert(#names>=3 and #names<=2000,'Invalid registration node count')
    local total=0
    for _,name in ipairs(names) do
      local source=job.manifest.nodes[name]
      assert(byName[name] and source and source.mass_kg>0,'Missing registration node')
      local rest=vec3(source.position[1],source.position[2],source.position[3])
      total=total+source.mass_kg;chassisCenter=chassisCenter+rest*source.mass_kg
      chassisRows[#chassisRows+1]={cid=byName[name].cid,rest=rest,weight=source.mass_kg}
    end
    chassisCenter=chassisCenter/total
    for _,row in ipairs(chassisRows) do row.weight=row.weight/total;row.rest=row.rest-chassisCenter end
    chassisFile=assert(io.open(job.output..'/frequency_chassis.csv','w'))
    chassisFile:write('physics_s,center_x,center_y,center_z,h00,h01,h02,h10,h11,h12,h20,h21,h22\n')
  end
  local targetFile,targetRows=nil,{}
  if config.actuator_targets then
    assert(not job.motion_reference.steering or job.motion_reference.steering.kind~='translating_rack','Frequency targets currently require equivalent ties')
    local h={'physics_s'}
    for _,corner in ipairs({'FL','FR'}) do
      local points=job.motion_reference.corners[corner].points
      local a,b=byName[points.tie_inner].cid,byName[points.tie_outer].cid
      local found=nil
      for _,hydro in pairs(hydros.hydros or {}) do
        local beam=hydro.beamCID and v.data.beams[hydro.beamCID]
        if beam and ((beam.id1==a and beam.id2==b) or (beam.id1==b and beam.id2==a)) then
          assert(not found,'Duplicate frequency steering actuator');found=hydro
        end
      end
      assert(found,'Missing frequency steering actuator '..corner)
      targetRows[#targetRows+1]={corner=corner,hydro=found}
      h[#h+1]=corner..'_target_m';h[#h+1]=corner..'_native_rest_m'
    end
    targetFile=assert(io.open(job.output..'/frequency_targets.csv','w'));targetFile:write(table.concat(h,',')..'\n')
  end
  local velocityFile=nil
  if config.velocities then
    local h={'physics_s'}
    for _,name in ipairs(config.nodes) do for _,axis in ipairs({'vx','vy','vz'}) do h[#h+1]=name..'_'..axis end end
    velocityFile=assert(io.open(job.output..'/frequency_velocities.csv','w'));velocityFile:write(table.concat(h,',')..'\n')
  end
  local loadFile,loadBeams,loadNodes,loadHeader=nil,{},{},{'physics_s'}
  if config.loads then
    local selected={};for _,name in ipairs(config.nodes) do selected[byName[name].cid]=true end
    for _,beam in pairs(v.data.beams) do
      if selected[beam.id1] and selected[beam.id2] then
        assert(#loadBeams<(config.complete_front_carriers and 400 or 250),'Frequency load capture exceeds beam bound')
        loadBeams[#loadBeams+1]={cid=beam.cid,a=v.data.nodes[beam.id1].name,b=v.data.nodes[beam.id2].name,
          spring=beam.beamSpring,damp=beam.beamDamp,beam_type=beam.beamType,rest=obj:getBeamRestLength(beam.cid)}
      end
    end
    table.sort(loadBeams,function(a,b) return a.cid<b.cid end)
    for _,beam in ipairs(loadBeams) do
      loadHeader[#loadHeader+1]='beam_'..beam.cid..'_stress';loadHeader[#loadHeader+1]='beam_'..beam.cid..'_length'
    end
    for _,name in ipairs(config.nodes) do
      loadNodes[#loadNodes+1]=name
      for _,axis in ipairs({'x','y','z'}) do loadHeader[#loadHeader+1]=name..'_force_'..axis end
    end
    loadFile=assert(io.open(job.output..'/frequency_loads.csv','w'));loadFile:write(table.concat(loadHeader,',')..'\n')
  end
  local wheelFile,wheelData=nil,{}
  local wheelNames={'FL','FR','RL','RR'}
  local wheelFields={'angularVelocity','angularVelocityBrakeCouple','propulsionTorque','brakingTorque'}
  if config.wheels then
    local h={'physics_s','throttle_input','brake_input'}
    for _,name in ipairs(wheelNames) do
      for _,wheel in pairs(wheels.wheels) do if wheel.name==name then wheelData[name]=wheel.coreData end end
      assert(wheelData[name],'Missing native wheel core '..name)
      for _,field in ipairs(wheelFields) do
        assert(tonumber(wheelData[name][field]),'Missing wheel core field '..field)
        h[#h+1]=name..'_'..field
      end
    end
    wheelFile=assert(io.open(job.output..'/frequency_wheels.csv','w'));wheelFile:write(table.concat(h,',')..'\n')
  end
  local routingFile,routingBeams=nil,{}
  local routingNodes=config.routing_nodes or {}
  local routingGroups={'chassis','fixed_attachment','wishbone','steering','coilover','other','native_total'}
  local routingExcluded={}
  if #routingNodes>0 then
    assert(#routingNodes<=16,'Routing capture exceeds node bound')
    local selected,chassis,fixed,arms,ties,shocks={},{},{},{},{},{}
    for i,name in ipairs(routingNodes) do assert(byName[name],'Missing routing node');selected[byName[name].cid]=i end
    for _,name in ipairs(job.manifest.chassis_nodes) do chassis[name]=true end
    for _,contract in pairs(job.manifest.fixed_attachment_contract or {}) do
      for _,name in ipairs(contract.nodes or {}) do fixed[name]=true end
    end
    for _,corner in ipairs({'FL','FR'}) do
      local hp=job.manifest.wheels[corner].hardpoint_nodes
      arms[hp.upper_ball]=true;arms[hp.lower_ball]=true;arms[hp.shock_bottom]=true
      ties[hp.tie_outer]=true;shocks[hp.shock_top]=hp.shock_bottom
    end
    for _,beam in pairs(v.data.beams) do
      if selected[beam.id1] or selected[beam.id2] then
        if beam.beamType==4 then routingExcluded[#routingExcluded+1]=beam.cid
        else
          assert(#routingBeams<2500,'Routing capture exceeds beam bound')
          local item={cid=beam.cid,a=beam.id1,b=beam.id2,beam_type=beam.beamType,ends={}}
          for _,pair in ipairs({{beam.id1,beam.id2,1},{beam.id2,beam.id1,-1}}) do
            local node,other= v.data.nodes[pair[1]].name,v.data.nodes[pair[2]].name
            if selected[pair[1]] then
              local group=chassis[other] and 1 or (fixed[other] and 2 or (shocks[node]==other and 5 or (ties[other] and 4 or (arms[other] and 3 or 6))))
              item.ends[#item.ends+1]={node=selected[pair[1]],group=group,sign=pair[3]}
            end
          end
          routingBeams[#routingBeams+1]=item
        end
      end
    end
    table.sort(routingBeams,function(a,b) return a.cid<b.cid end)
    local h={'physics_s'}
    for _,name in ipairs(routingNodes) do for _,group in ipairs(routingGroups) do
      for _,axis in ipairs({'x','y','z'}) do h[#h+1]=name..'_'..group..'_'..axis end
    end end
    routingFile=assert(io.open(job.output..'/frequency_routing.csv','w'));routingFile:write(table.concat(h,',')..'\n')
  end
  local elapsed,count,first,last,minimum,maximum=0,0,nil,nil,math.huge,0
  local complete=false
  local function close()
    if file then file:flush();file:close();file=nil end
    if loadFile then loadFile:flush();loadFile:close();loadFile=nil end
    if routingFile then routingFile:flush();routingFile:close();routingFile=nil end
    if wheelFile then wheelFile:flush();wheelFile:close();wheelFile=nil end
    if velocityFile then velocityFile:flush();velocityFile:close();velocityFile=nil end
    if chassisFile then chassisFile:flush();chassisFile:close();chassisFile=nil end
    if targetFile then targetFile:flush();targetFile:close();targetFile=nil end
  end
  return {
    step=function(dt,controlTime)
      elapsed=elapsed+dt
      if elapsed<config.start_s then return end
      if elapsed>=config.start_s+config.duration_s then complete=true;close();return end
      assert(count<20000,'Frequency recording exceeded sample cap')
      minimum=math.min(minimum,dt);maximum=math.max(maximum,dt)
      local row={string.format('%.9f',elapsed),string.format('%.9f',controlTime)}
      for _,cid in ipairs(ids) do
        -- Local getters hold graphics-rate snapshots; this absolute accessor
        -- was verified to return fresh values on every physics callback.
        local p=obj:getAbsNodePosition(cid)
        row[#row+1]=string.format('%.12g',p.x);row[#row+1]=string.format('%.12g',p.y);row[#row+1]=string.format('%.12g',p.z)
      end
      file:write(table.concat(row,',')..'\n');count=count+1;first=first or elapsed;last=elapsed
      if targetFile then
        local values={string.format('%.9f',elapsed)}
        for _,item in ipairs(targetRows) do
          local hydro=item.hydro
          local target=obj:getBeamRefLength(hydro.beamCID)*hydro.state
          assert(target>0 and target<math.huge,'Invalid hydro target')
          values[#values+1]=string.format('%.17g',target)
          values[#values+1]=string.format('%.17g',obj:getBeamRestLength(hydro.beamCID))
        end
        targetFile:write(table.concat(values,',')..'\n')
      end
      if chassisFile then
        local center=vec3(0,0,0);local h={0,0,0,0,0,0,0,0,0}
        -- Subtract a nearby current origin before accumulating covariance to
        -- avoid cancellation at large map coordinates.
        local origin=obj:getAbsNodePosition(chassisRows[1].cid)
        for _,item in ipairs(chassisRows) do
          local current=obj:getAbsNodePosition(item.cid)-origin
          center=center+current*item.weight
          local a={item.rest.x,item.rest.y,item.rest.z};local b={current.x,current.y,current.z}
          for i=1,3 do for j=1,3 do local k=(i-1)*3+j;h[k]=h[k]+item.weight*a[i]*b[j] end end
        end
        center=center+origin
        local values={string.format('%.9f',elapsed),string.format('%.17g',center.x),string.format('%.17g',center.y),string.format('%.17g',center.z)}
        for _,value in ipairs(h) do values[#values+1]=string.format('%.17g',value) end
        chassisFile:write(table.concat(values,',')..'\n')
      end
      if velocityFile then
        local values={string.format('%.9f',elapsed)}
        for _,cid in ipairs(ids) do
          local velocity=obj:getNodeVelocityVector(cid)
          for _,value in ipairs({velocity.x,velocity.y,velocity.z}) do values[#values+1]=string.format('%.12g',value) end
        end
        velocityFile:write(table.concat(values,',')..'\n')
      end
      if loadFile then
        local loads={string.format('%.9f',elapsed)}
        for _,beam in ipairs(loadBeams) do
          loads[#loads+1]=string.format('%.12g',obj:getBeamStress(beam.cid));loads[#loads+1]=string.format('%.12g',obj:getBeamLength(beam.cid))
        end
        for _,name in ipairs(loadNodes) do
          local f=obj:getNodeForceVector(byName[name].cid)
          loads[#loads+1]=string.format('%.12g',f.x);loads[#loads+1]=string.format('%.12g',f.y);loads[#loads+1]=string.format('%.12g',f.z)
        end
        loadFile:write(table.concat(loads,',')..'\n')
      end
      if wheelFile then
        local values={string.format('%.9f',elapsed),string.format('%.12g',electrics.values.throttle or 0),string.format('%.12g',electrics.values.brake or 0)}
        for _,name in ipairs(wheelNames) do for _,field in ipairs(wheelFields) do
          values[#values+1]=string.format('%.12g',tonumber(wheelData[name][field]))
        end end
        wheelFile:write(table.concat(values,',')..'\n')
      end
      if routingFile then
        local forces,positions={},{}
        for i=1,#routingNodes do forces[i]={};for g=1,#routingGroups do forces[i][g]=vec3(0,0,0) end end
        local function position(cid)
          if not positions[cid] then positions[cid]=obj:getAbsNodePosition(cid) end
          return positions[cid]
        end
        for _,beam in ipairs(routingBeams) do
          local direction=position(beam.b)-position(beam.a);local length=direction:length()
          assert(length>1e-9,'Collapsed routing beam')
          local force=direction*(obj:getBeamStress(beam.cid)/length)
          for _,endpoint in ipairs(beam.ends) do
            forces[endpoint.node][endpoint.group]=forces[endpoint.node][endpoint.group]+force*endpoint.sign
          end
        end
        local values={string.format('%.9f',elapsed)}
        for i,name in ipairs(routingNodes) do
          forces[i][#routingGroups]=obj:getNodeForceVector(byName[name].cid)
          for _,force in ipairs(forces[i]) do for _,v in ipairs({force.x,force.y,force.z}) do values[#values+1]=string.format('%.12g',v) end end
        end
        routingFile:write(table.concat(values,',')..'\n')
      end
    end,
    finish=function()
      close()
      jsonWriteFile(job.output..'/frequency.json',{job_id=job.id,version=1,nodes=config.nodes,
        config=config,samples=count,first_s=first,last_s=last,dt_min=minimum,dt_max=maximum,
        complete=complete,position_api='getAbsNodePosition',coordinate_system='world',load_beams=loadBeams,load_nodes=loadNodes,
        routing_nodes=routingNodes,routing_groups=routingGroups,routing_beams=routingBeams,routing_excluded_lbeams=routingExcluded,
        routing_scope='Incident axial beam forces by source, in world coordinates; excludes torsionbar forces, gravity, contacts and L-beams. Compare native_total separately; not a complete force balance.',
        loads_scope='Raw native beam stress/length and node force; validate update cadence before inference'},true)
      if config.velocities then
        jsonWriteFile(job.output..'/frequency_velocities.json',{job_id=job.id,samples=count,complete=complete,nodes=config.nodes,
          scope='Native getNodeVelocityVector, metres per second, sampled at the same physics callbacks as force and position. Validate force timing and gravity convention independently.'},true)
      end
      if config.actuator_targets then
        local declarations={}
        for _,item in ipairs(targetRows) do declarations[#declarations+1]={corner=item.corner,beam_cid=item.hydro.beamCID} end
        jsonWriteFile(job.output..'/frequency_targets.json',{job_id=job.id,samples=count,complete=complete,actuators=declarations,
          scope='Equivalent tie target = native reference length times hydro state, sampled with node positions at every physics callback. Native rest length is recorded separately to audit update timing.'},true)
      end
      if config.wheels then
        jsonWriteFile(job.output..'/frequency_wheels.json',{job_id=job.id,samples=count,complete=complete,names=wheelNames,fields=wheelFields,
          scope='Native getWheelFFI coreData at each physics callback. Angular velocities are rad/s; torques are N.m commands sent to physics, not measurements of applied brake torque after native saturation. Electrics inputs may be held between controller updates.'},true)
      end
    end
  }
end
return M
