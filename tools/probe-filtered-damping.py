"""Owned force-driven native coupons for normal/bounded damping filters."""
import argparse,hashlib,importlib.util,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject
from frame_harness.build import write_json
spec=importlib.util.spec_from_file_location('probe',ROOT/'tools/probe-drive-execution.py');probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

RECORDER=r'''
local M={};local job,file,t,nodes,beams,last,step
function M.start(value)
  job=value;t=0;last=0;step=0;nodes={};beams={}
  for _,node in pairs(v.data.nodes) do nodes[node.name]=node.cid end
  for _,beam in pairs(v.data.beams) do beams[beam.name]=beam end
  local header={'t','applied_force'}
  for _,c in ipairs(job.coupons) do for _,key in ipairs({'length','rate','elastic','damping','force'}) do header[#header+1]=c.name..'_'..key end end
  file=assert(io.open(job.output..'/damping.csv','w'));file:write(table.concat(header,',')..'\n')
  jsonWriteFile(job.output..'/compiled_coupon.json',{job_id=job.id,beams=beams,nodes=v.data.nodes},true)
  obj:setSleepingEnabled(false);enablePhysicsStepHook()
end
function M.onPhysicsStep(dt)
  if not file then return end
  t=t+dt;step=step+1;local row={t,last}
  local force=0
  for _,hz in ipairs({5,14,40,100,250}) do force=force+job.force_amplitude_n*math.sin(2*math.pi*hz*t) end
  for _,c in ipairs(job.coupons) do
    local a,b=nodes[c.name..'_a'],nodes[c.name..'_b'];local beam=beams[c.name]
    local delta=obj:getAbsNodePosition(b)-obj:getAbsNodePosition(a);local length=delta:length();local dir=delta/length
    local rate=(obj:getNodeVelocityVector(b)-obj:getNodeVelocityVector(a)):dot(dir)
    local elastic,damping=obj:getBeamStressDamp(beam.cid)
    for _,v in ipairs({length,rate,elastic,damping,obj:getNodeForceVector(b):dot(dir)}) do row[#row+1]=v end
    obj:applyForceVector(b,dir*force)
  end
  local words={};for _,v in ipairs(row) do words[#words+1]=string.format('%.12g',v) end
  file:write(table.concat(words,',')..'\n');last=force
  if t>=8 then
    file:flush();file:close();file=nil
    jsonWriteFile(job.output..'/completion.json',{job_id=job.id,session_id=job.session_id,status='completed',samples=step,simulated_seconds=t},true)
    obj:queueGameEngineLua(string.format('vehicleharness_bridge.completed(%q,%q,%q)','completed','',job.id))
  end
end
return M
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--stiff',action='store_true',help='Actual arm-scale stiffness and reduced endpoint masses');a=p.parse_args()
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    definitions=[dict(name=name,kind=kind,cutoff_hz=cutoff,spring=20000.,damping=400.,mass=2.) for name,kind,cutoff in
        [('normal_raw','|NORMAL',0),('normal_25','|NORMAL',25),('normal_100','|NORMAL',100),('bounded_25','|BOUNDED',25)]]
    if a.stiff:
        definitions=[dict(name=name,kind='|NORMAL',cutoff_hz=cutoff,spring=spring,damping=damping,mass=mass) for name,cutoff,spring,damping,mass in
            [('lower_1000_25',25,2500000.,1000.,1.),('lower_3000_25',25,2500000.,3000.,1.),
             ('lower_3000_100',100,2500000.,3000.,1.),('upper_5000_25',25,15000000.,5000.,3.)]]
        definitions.extend([dict(name='unequal_fixed_heavy',kind='|NORMAL',cutoff_hz=25,spring=2500000.,damping=10000.,mass=1.,anchor_mass=3.),
                            dict(name='unequal_free_heavy',kind='|NORMAL',cutoff_hz=25,spring=2500000.,damping=10000.,mass=3.,anchor_mass=1.)])
    project=HarnessProject(userpath=a.profile,runs=a.output.parent)
    with probe.ProbeSession(project,'vehicle') as session:
        session.mode='null'
        (session.root/'mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/recorder.lua').write_text(RECORDER,encoding='utf-8')
        (a.output/'recorder.lua').write_text(RECORDER,encoding='utf-8')
        (session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/visuals.lua').write_text("return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}",encoding='utf-8')
        model='cad_damping_coupon';folder=session.root/'mods/unpacked/vehicle_harness/vehicles'/model;folder.mkdir(parents=True,exist_ok=True)
        part=dict(information={'name':'CAD damping filter coupons','authors':'beamng.cad'},slotType='main',refNodes=[['ref:','back:','left:','up:'],['ref0','ref1','ref2','ref3']],nodes=[['id','posX','posY','posZ']],beams=[['id1:','id2:']])
        for i,point in enumerate([[0,0,0],[0,1,0],[1,0,0],[0,0,1]]):
            part['nodes'].append([f'ref{i}',*point,dict(nodeWeight=1000.,fixed=True,collision=False,selfCollision=False)])
        for i,c in enumerate(definitions):
            for suffix,x,fixed in [('a',0.,True),('b',.5,False)]:
                part['nodes'].append([c['name']+'_'+suffix,x,i*.5,0.,dict(nodeWeight=c.get('anchor_mass',c['mass']) if fixed else c['mass'],fixed=fixed,collision=False,selfCollision=False)])
            opts=dict(name=c['name'],beamType=c['kind'],beamSpring=c['spring'],beamDamp=c['damping'],beamDeform=1e30,beamStrength=1e30,dampCutoffHz=c['cutoff_hz'])
            if c['kind']=='|BOUNDED':opts.update(beamLongBound=1,beamShortBound=1,beamLimitSpring=0,beamLimitDamp=0)
            part['beams'].append([c['name']+'_a',c['name']+'_b',opts])
        assets={model+'.jbeam':{model:part},'base.pc':{'format':2,'parts':{model:model}},'info.json':{'Name':'CAD damping coupons','Type':'Prop'}}
        for name,data in assets.items():write_json(folder/name,data);write_json(a.output/name,data)
        identity='damping-'+uuid.uuid4().hex;out=session.control/'results'/identity;out.mkdir(parents=True)
        job=dict(id=identity,model=model,config='base.pc',duration=8.,gravity=0.,spawn_z=2.,scenario='damping_coupon',coupons=definitions,force_amplitude_n=1000. if a.stiff else 100.,
            output='/settings/vehicle_harness/results/'+identity,changed_files=['/vehicles/'+model+'/'+n for n in assets],manifest={'nodes':{r[0]:r[1:4] for r in part['nodes'][1:]}})
        write_json(a.output/'job.json',job)
        try:result=session.execute(job,a.output,out,capture=False)
        finally:
            session.close_process();session.archive_recording(out,a.output,archive_root=a.output.parent);session.archive_logs(a.output)
        write_json(a.output/'result.json',dict(status=result['status'],scope='Isolated numerical damping identification; no vehicle qualification',recorder_sha256=hashlib.sha256(RECORDER.encode()).hexdigest()))


if __name__=='__main__':main()
