-- Local CAD render patches have four supporting nodes. Once their locator
-- graph separates, interpolation across those pieces is no longer defined.
-- Remove that patch, not either intact component. This is a coarse visual
-- erosion model, not a material fracture or fragment-generation model.
local M = {type = 'auxiliary'}
local regions, byBeam, hidden, dirty, breakEvents, visibilityResults

local function visibility(mesh, alpha)
  local response=string.format('controller.getController("cadSkin").visibilityResult(%q,',mesh)
  obj:queueGameEngineLua(string.format(
    'local v=be:getObjectByID(%d); if v then local ok=v:setMeshAlpha(%g,%q,false); v:queueLuaCommand(%q..tostring(ok==true)..")") end',
    obj:getId(), alpha, mesh,response))
end

local function init(data)
  regions = data.regions or {}
  byBeam, hidden, dirty, breakEvents,visibilityResults = {}, {}, {}, 0,{}
  local names = {}
  -- Pressure wheels add anonymous nodes. Only authored nodes can be locators.
  for cid,node in pairs(v.data.nodes) do if node.name then names[node.name] = cid end end
  for index,region in ipairs(regions) do
    region.edges = {}
    local selected = {}
    for _,name in ipairs(region.nodes) do
      assert(names[name]~=nil,'Missing CAD skin locator '..tostring(name))
      selected[names[name]] = true
    end
    for cid,beam in pairs(v.data.beams) do
      if selected[beam.id1] and selected[beam.id2] then
        region.edges[#region.edges+1] = {cid=cid,a=beam.id1,b=beam.id2}
        byBeam[cid] = byBeam[cid] or {}
        byBeam[cid][#byBeam[cid]+1] = index
      end
    end
    region.first = names[region.nodes[1]]
  end
end

local function beamBroke(cid)
  breakEvents=breakEvents+1
  for _,index in ipairs(byBeam[cid] or {}) do dirty[index] = true end
end

local function updateGFX()
  for index in pairs(dirty) do
    if not hidden[index] then
      local region = regions[index]
      local reached = {[region.first]=true}
      for _=1,3 do
        for _,edge in ipairs(region.edges) do
          if not obj:beamIsBroken(edge.cid) and (reached[edge.a] or reached[edge.b]) then
            reached[edge.a],reached[edge.b] = true,true
          end
        end
      end
      local count=0
      for _ in pairs(reached) do count=count+1 end
      if count < 4 then hidden[index]=true;visibility(region.mesh,0) end
    end
  end
  dirty = {}
end

local function reset()
  for index in pairs(hidden) do visibility(regions[index].mesh,1) end
  hidden,dirty,breakEvents = {},{},0
end

M.init=init
M.reset=reset
M.beamBroken=beamBroke
M.updateGFX=updateGFX
M.visibilityResult=function(mesh,success) visibilityResults[mesh]=success end
M.getState=function()
  local mappings,removed=0,{}
  for _ in pairs(byBeam or {}) do mappings=mappings+1 end
  for index in pairs(hidden or {}) do removed[#removed+1]=regions[index].mesh end
  return {region_count=#(regions or {}),mapped_beams=mappings,break_events=breakEvents,removed=removed,visibility_results=visibilityResults}
end
return M
