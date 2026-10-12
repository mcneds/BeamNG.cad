"""Force-driven native L-beam/control coupons without prescribed node positions."""
import argparse,hashlib,importlib.util,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject
from frame_harness.build import write_json
spec=importlib.util.spec_from_file_location('probe',ROOT/'tools/probe-drive-execution.py');probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

RECORDER=r'''
local M={};local job,file,t,step,ids,last
local labels={'a','b','c'};local edges={{1,2,5},{2,3,7},{1,3,11}}
function M.start(value)
  job=value;t=0;step=0;ids={};last={}
  local byName={};for _,node in pairs(v.data.nodes) do byName[node.name]=node.cid end
  local header={'t'}
  for _,c in ipairs(job.coupons) do
    ids[c.name]={};last[c.name]={vec3(0,0,0),vec3(0,0,0),vec3(0,0,0)}
    for _,n in ipairs(labels) do
      ids[c.name][#ids[c.name]+1]=assert(byName[c.name..'_'..n])
      for _,key in ipairs({'x','y','z','vx','vy','vz','fx','fy','fz','ex','ey','ez'}) do header[#header+1]=c.name..'_'..n..'_'..key end
    end
  end
  file=assert(io.open(job.output..'/coupon.csv','w'));file:write(table.concat(header,',')..'\n')
  jsonWriteFile(job.output..'/compiled_coupon.json',{job_id=job.id,nodes=v.data.nodes,beams=v.data.beams},true)
  obj:setSleepingEnabled(false);enablePhysicsStepHook()
end
function M.onPhysicsStep(dt)
  if not file then return end
  t=t+dt;step=step+1;local row={t}
  for _,c in ipairs(job.coupons) do
    local nextForces={vec3(0,0,0),vec3(0,0,0),vec3(0,0,0)}
    for i,cid in ipairs(ids[c.name]) do
      local p=obj:getAbsNodePosition(cid);local v=obj:getNodeVelocityVector(cid);local f=obj:getNodeForceVector(cid);local e=last[c.name][i]
      for _,x in ipairs({p.x,p.y,p.z,v.x,v.y,v.z,f.x,f.y,f.z,e.x,e.y,e.z}) do row[#row+1]=x end
    end
    for _,edge in ipairs(edges) do
      local a,b,hz=edge[1],edge[2],edge[3];local direction=vec3(job.points[b])-vec3(job.points[a]);direction:normalize()
      local force=direction*(job.force_amplitude_n*math.sin(2*math.pi*hz*t))
      nextForces[a]=nextForces[a]-force;nextForces[b]=nextForces[b]+force
    end
    for i,cid in ipairs(ids[c.name]) do obj:applyForceVector(cid,nextForces[i]) end
    last[c.name]=nextForces
  end
  local text={};for _,x in ipairs(row) do text[#text+1]=string.format('%.12g',x) end
  file:write(table.concat(text,',')..'\n')
  if t>=job.duration then
    file:flush();file:close();file=nil
    jsonWriteFile(job.output..'/completion.json',{job_id=job.id,session_id=job.session_id,status='completed',samples=step,simulated_seconds=t},true)
    obj:queueGameEngineLua(string.format('vehicleharness_bridge.completed(%q,%q,%q)','completed','',job.id))
  end
end
return M
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    coupons=[dict(name='normal_stiff',kind='normal',spring=10010.,damping=2.),dict(name='normal_soft',kind='normal',spring=10.,damping=2.),
             dict(name='single_lbeam',kind='single_lbeam',spring=10.,damping=2.),dict(name='three_lbeams',kind='three_lbeams',spring=10.,damping=2.),
             dict(name='replacement_lbeam',kind='replacement_lbeam',spring=10.,damping=2.)]
    points=[[-.1,0,0],[.1,0,0],[0,.4,0]];mass=2.
    with probe.ProbeSession(HarnessProject(userpath=a.profile,runs=a.output.parent),'vehicle') as session:
        session.mode='null';(session.root/'mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/recorder.lua').write_text(RECORDER,encoding='utf-8')
        (a.output/'recorder.lua').write_text(RECORDER,encoding='utf-8')
        (session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/visuals.lua').write_text("return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}",encoding='utf-8')
        model='cad_lbeam_force_coupon';folder=session.root/'mods/unpacked/vehicle_harness/vehicles'/model;folder.mkdir(parents=True,exist_ok=True)
        part=dict(information={'name':'Force-driven L-beam controls','authors':'beamng.cad'},slotType='main',refNodes=[['ref:','back:','left:','up:'],['ref0','ref1','ref2','ref3']],nodes=[['id','posX','posY','posZ']],beams=[['id1:','id2:']])
        for i,p in enumerate([[0,0,0],[0,1,0],[1,0,0],[0,0,1]]):part['nodes'].append([f'ref{i}',*p,dict(nodeWeight=1000.,fixed=True,collision=False,selfCollision=False)])
        for c in coupons:
            names=[c['name']+'_'+n for n in 'abc']
            for n,p in zip(names,points):part['nodes'].append([n,*p,dict(nodeWeight=mass,collision=False,selfCollision=False)])
            for i,j in ([(0,1),(1,2)] if c['kind']=='replacement_lbeam' else [(0,1),(1,2),(0,2)]):part['beams'].append([names[i],names[j],dict(beamSpring=c['spring'],beamDamp=c['damping'],beamStrength=1e30,beamDeform=1e30)])
            if c['kind']!='normal':
                for i,j,k in ([(0,2,1)] if c['kind'] in ('single_lbeam','replacement_lbeam') else [(0,2,1),(0,1,2),(1,2,0)]):
                    part['beams'].append([names[i],names[j],{'beamType':'|LBEAM','id3:':names[k],'beamSpring':10000.,'beamDamp':0.,'beamDeform':1e30,'beamStrength':1e30}])
        assets={model+'.jbeam':{model:part},'base.pc':{'format':2,'parts':{model:model}},'info.json':{'Name':'Force-driven angular coupons','Type':'Prop'}}
        for name,value in assets.items():write_json(folder/name,value);write_json(a.output/name,value)
        identity='lbeam-force-'+uuid.uuid4().hex;out=session.control/'results'/identity;out.mkdir(parents=True)
        job=dict(id=identity,model=model,config='base.pc',duration=8.,gravity=0.,spawn_z=2.,scenario='lbeam_force',coupons=coupons,points=points,mass_kg=mass,force_amplitude_n=.2,
            output='/settings/vehicle_harness/results/'+identity,changed_files=['/vehicles/'+model+'/'+n for n in assets],manifest={'nodes':{r[0]:r[1:4] for r in part['nodes'][1:]}})
        write_json(a.output/'job.json',job)
        try:result=session.execute(job,a.output,out,capture=False)
        finally:session.close_process();session.archive_recording(out,a.output,archive_root=a.output.parent);session.archive_logs(a.output)
        write_json(a.output/'result.json',dict(status=result['status'],scope=__doc__,recorder_sha256=hashlib.sha256(RECORDER.encode()).hexdigest()))


if __name__=='__main__':main()
