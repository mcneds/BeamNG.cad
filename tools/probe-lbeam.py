"""Small owned native experiment to identify L-beam tangent forces, no vehicle changes."""
import argparse,hashlib,importlib.util,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject
from frame_harness.build import write_json
spec=importlib.util.spec_from_file_location('drive_probe',ROOT/'tools/probe-drive-execution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

RECORDER=r'''
local M={};local job,file,t,byName,original,beams,last,step
local names={'a','b','c'}
function M.start(value)
  job=value;t=0;step=0;last=-1;byName={};original={};beams={}
  for _,node in pairs(v.data.nodes) do byName[node.name]=node.cid;original[node.name]=obj:getNodePosition(node.cid) end
  for _,beam in pairs(v.data.beams) do beams[#beams+1]=beam end
  table.sort(beams,function(a,b) return a.cid<b.cid end)
  local header={'t','case'}
  for _,name in ipairs(names) do for _,key in ipairs({'x','y','z','fx','fy','fz'}) do header[#header+1]=name..'_'..key end end
  for _,beam in ipairs(beams) do header[#header+1]='beam_'..beam.cid..'_stress' end
  file=assert(io.open(job.output..'/coupon.csv','w'));file:write(table.concat(header,',')..'\n')
  jsonWriteFile(job.output..'/coupon.json',{job_id=job.id,beams=beams,original=original},true)
  enablePhysicsStepHook();obj:setSleepingEnabled(false)
end
function M.onPhysicsStep(dt)
  if not file then return end
  t=t+dt;step=step+1
  local case=math.min(18,math.floor(t/.2))
  -- Capture the force resulting from the preceding prescribed position step.
  if step%10==0 then
    local row={t,last}
    for _,name in ipairs(names) do
      local p=obj:getAbsNodePosition(byName[name]);local f=obj:getNodeForceVector(byName[name])
      for _,value in ipairs({p.x,p.y,p.z,f.x,f.y,f.z}) do row[#row+1]=value end
    end
    for _,beam in ipairs(beams) do row[#row+1]=obj:getBeamStress(beam.cid) end
    local words={};for _,value in ipairs(row) do words[#words+1]=string.format('%.12g',value) end
    file:write(table.concat(words,',')..'\n')
  end
  for i,name in ipairs(names) do
    local p=vec3(original[name]);local coordinate=math.floor((case-1)/2);local sign=case%2==1 and 1 or -1
    if case>0 and math.floor(coordinate/3)+1==i then
      local axis=coordinate%3;if axis==0 then p.x=p.x+sign*.0001 elseif axis==1 then p.y=p.y+sign*.0001 else p.z=p.z+sign*.0001 end
    end
    obj:setNodePosition(byName[name],p)
  end
  last=case
  if t>=4 then
    file:flush();file:close();file=nil
    jsonWriteFile(job.output..'/completion.json',{job_id=job.id,session_id=job.session_id,status='completed',simulated_seconds=t},true)
    obj:queueGameEngineLua(string.format('vehicleharness_bridge.completed(%q,%q,%q)','completed','',job.id))
  end
end
return M
'''

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--profile',required=True,type=Path);p.add_argument('--complete-triangle',action='store_true');p.add_argument('--parallel-normal',action='store_true');p.add_argument('--normals-last',action='store_true',help='Diagnostic native reference-beam lookup ordering');p.add_argument("--dynamic-nodes",action="store_true",help="Check whether fixed-node optimization hides angular coupling");a=p.parse_args()
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    project=HarnessProject(userpath=a.profile,runs=a.output.parent)
    with module.ProbeSession(project,'vehicle') as session:
        session.mode='null'
        target=session.root/'mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/recorder.lua';target.write_text(RECORDER,encoding='utf-8')
        (a.output/'recorder.lua').write_text(RECORDER,encoding='utf-8')
        (session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/visuals.lua').write_text("return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}",encoding='utf-8')
        model='cad_lbeam_coupon';folder=session.root/'mods/unpacked/vehicle_harness/vehicles'/model;folder.mkdir(parents=True,exist_ok=True)
        points=dict(a=[-.1,0,0],b=[.1,0,0],c=[0,.4,0],d=[0,0,.5])
        part=dict(information={'name':'CAD L-beam tangent coupon','authors':'beamng.cad'},slotType='main',
            refNodes=[['ref:','back:','left:','up:'],['a','b','c','d']],
            nodes=[['id','posX','posY','posZ']]+[[n,*v,dict(nodeWeight=1000.,fixed=(not a.dynamic_nodes or n=='d'),collision=False,selfCollision=False)] for n,v in points.items()],
            beams=[['id1:','id2:'],['a','b',dict(beamSpring=10.,beamDamp=0.,beamDeform=1e30,beamStrength=1e30)],
                ['b','c',dict(beamSpring=10.,beamDamp=0.,beamDeform=1e30,beamStrength=1e30)],
                ['a','c',{'beamType':'|LBEAM','id3:':'b','beamSpring':10000.,'beamDamp':0.,'beamDeform':1e30,'beamStrength':1e30}]])
        assets={model+'.jbeam':{model:part},'base.pc':{'format':2,'parts':{model:model}},'info.json':{'Name':'CAD L-beam coupon','Type':'Prop'}}
        if a.complete_triangle or a.parallel_normal:
            part['beams'].insert(3,['a','c',dict(beamSpring=10.,beamDamp=0.,beamDeform=1e30,beamStrength=1e30)])
        if a.complete_triangle:
            for x,y,z in [('a','b','c'),('b','c','a')]:part['beams'].append([x,y,{'beamType':'|LBEAM','id3:':z,'beamSpring':10000.,'beamDamp':0.,'beamDeform':1e30,'beamStrength':1e30}])
        if a.normals_last:
            part['beams']=part['beams'][:1]+sorted(part['beams'][1:],key=lambda row:row[-1].get('beamType')!='|LBEAM')
        for name,content in assets.items():write_json(folder/name,content);write_json(a.output/name,content)
        identity='lbeam-'+uuid.uuid4().hex;out=session.control/'results'/identity;out.mkdir(parents=True)
        job=dict(id=identity,model=model,config='base.pc',duration=4.,gravity=0.,spawn_z=2.,scenario='lbeam_tangent',
            output='/settings/vehicle_harness/results/'+identity,changed_files=['/vehicles/'+model+'/'+n for n in assets],manifest={'nodes':points})
        write_json(a.output/'job.json',job)
        try:result=session.execute(job,a.output,out,capture=False)
        finally:
            session.close_process();session.archive_recording(out,a.output,archive_root=a.output.parent);session.archive_logs(a.output)
        write_json(a.output/'result.json',dict(status=result['status'],scope='Prescribed-position numerical coupon; not vehicle qualification',recorder_sha256=hashlib.sha256(RECORDER.encode()).hexdigest()))

if __name__=='__main__':main()
