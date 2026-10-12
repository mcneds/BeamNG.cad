"""Owned native tangent test for torsion constraints, isolated from any vehicle.

Canonical, skew and actual CAD lower-arm layouts run as separate fixed coupons.
No generation coefficient or installed mod is changed.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import uuid
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'dependencies/cad-calibration/Test Harness'),str(ROOT/'beamng.cad/FramePipeline')]
from frame_harness.models import HarnessProject
from frame_harness.build import write_json
spec=importlib.util.spec_from_file_location('probe',ROOT/'tools/probe-drive-execution.py');probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

RECORDER=r'''
local M={};local job,file,t,byName,original,step,last
function M.start(value)
  job=value;t=0;step=0;last=-1;byName={};original={}
  for _,node in pairs(v.data.nodes) do byName[node.name]=node.cid;original[node.name]=obj:getNodePosition(node.cid) end
  local header={'t','case'}
  for _,coupon in ipairs(job.coupons) do for _,name in ipairs(coupon.names) do
    for _,key in ipairs({'x','y','z','fx','fy','fz'}) do header[#header+1]=name..'_'..key end
  end end
  file=assert(io.open(job.output..'/torsion_coupon.csv','w'));file:write(table.concat(header,',')..'\n')
  jsonWriteFile(job.output..'/compiled_coupon.json',{job_id=job.id,torsionbars=v.data.torsionbars,beams=v.data.beams},true)
  obj:setSleepingEnabled(false);enablePhysicsStepHook()
end
function M.onPhysicsStep(dt)
  if not file then return end
  t=t+dt;step=step+1
  local case=math.min(24,math.floor(t/.12))
  if step%10==0 then
    local values={t,last}
    for _,coupon in ipairs(job.coupons) do for _,name in ipairs(coupon.names) do
      local p=obj:getAbsNodePosition(byName[name]);local f=obj:getNodeForceVector(byName[name])
      for _,v in ipairs({p.x,p.y,p.z,f.x,f.y,f.z}) do values[#values+1]=v end
    end end
    local words={};for _,value in ipairs(values) do words[#words+1]=string.format('%.12g',value) end
    file:write(table.concat(words,',')..'\n')
  end
  for _,coupon in ipairs(job.coupons) do for i,name in ipairs(coupon.names) do
    local p=vec3(original[name]);local coordinate=math.floor((case-1)/2);local sign=case%2==1 and 1 or -1
    if case>0 and math.floor(coordinate/3)+1==i then
      local axis=coordinate%3;if axis==0 then p.x=p.x+sign*.0001 elseif axis==1 then p.y=p.y+sign*.0001 else p.z=p.z+sign*.0001 end
    end
    obj:setNodePosition(byName[name],p)
  end end
  last=case
  if t>=3.2 then
    file:flush();file:close();file=nil
    jsonWriteFile(job.output..'/completion.json',{job_id=job.id,session_id=job.session_id,status='completed',simulated_seconds=t},true)
    obj:queueGameEngineLua(string.format('vehicleharness_bridge.completed(%q,%q,%q)','completed','',job.id))
  end
end
return M
'''


def coupons(manifest):
    result=[dict(name='right_angle',points=[[0,1,0],[0,0,0],[1,0,0],[1,1,0]]),
            dict(name='skew',points=[[-.3,.5,.2],[0,0,0],[.8,0,0],[1.1,.3,-.4]])]
    owners=[o for o,r in manifest['component_roles'].items() if r=='fl_lower_wishbone']
    if len(owners)!=1:raise ValueError('One FL lower wishbone required')
    own=set(manifest['mass_allocations'][owners[0]])
    bars=[r for r in manifest['torsionbars'] if set(r[:4])<=own]
    if not bars:raise ValueError('No actual lower-arm angular constraint')
    row=max(bars,key=lambda r:r[4]['spring'])
    result.append(dict(name='cad_lower_arm',points=[manifest['nodes'][n]['position'] for n in row[:4]],source_nodes=row[:4]))
    for index,item in enumerate(result):
        xyz=np.array(item['points'],dtype=float);xyz-=xyz.mean(0);xyz+=np.array([index*2.,0.,0.])
        item.update(points=xyz.tolist(),names=[f'coupon_{index}_{n}' for n in range(4)],spring=10000.,normal_spring=10.)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--profile',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    definitions=coupons(json.loads(a.manifest.read_bytes()));a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    project=HarnessProject(userpath=a.profile,runs=a.output.parent)
    with probe.ProbeSession(project,'vehicle') as session:
        session.mode='null'
        (session.root/'mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/recorder.lua').write_text(RECORDER,encoding='utf-8')
        (a.output/'recorder.lua').write_text(RECORDER,encoding='utf-8')
        (session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/visuals.lua').write_text("return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}",encoding='utf-8')
        model='cad_torsion_coupon';folder=session.root/'mods/unpacked/vehicle_harness/vehicles'/model;folder.mkdir(parents=True,exist_ok=True)
        positions={f'ref{i}':p for i,p in enumerate([[0,0,0],[0,1,0],[1,0,0],[0,0,1]])}
        part=dict(information={'name':'CAD torsion tangent coupons','authors':'beamng.cad'},slotType='main',refNodes=[['ref:','back:','left:','up:'],['ref0','ref1','ref2','ref3']],
                  nodes=[['id','posX','posY','posZ']],beams=[['id1:','id2:']],torsionbars=[['id1:','id2:','id3:','id4:']])
        import itertools
        for item in definitions:
            positions.update(zip(item['names'],item['points']))
            for x,y in itertools.combinations(item['names'],2):part['beams'].append([x,y,dict(beamSpring=item['normal_spring'],beamDamp=0.,beamDeform=1e30,beamStrength=1e30)])
            part['torsionbars'].append(item['names']+[dict(spring=item['spring'],damp=0.,deform=1e30,strength=1e30)])
        part['nodes'] += [[n,*v,dict(nodeWeight=1000.,fixed=True,collision=False,selfCollision=False)] for n,v in positions.items()]
        assets={model+'.jbeam':{model:part},'base.pc':{'format':2,'parts':{model:model}},'info.json':{'Name':'CAD torsion coupons','Type':'Prop'}}
        for name,data in assets.items():write_json(folder/name,data);write_json(a.output/name,data)
        identity='torsion-'+uuid.uuid4().hex;out=session.control/'results'/identity;out.mkdir(parents=True)
        job=dict(id=identity,model=model,config='base.pc',duration=3.2,gravity=0.,spawn_z=2.,scenario='torsion_tangent',coupons=definitions,
                 output='/settings/vehicle_harness/results/'+identity,changed_files=['/vehicles/'+model+'/'+n for n in assets],manifest={'nodes':positions},source_manifest_sha256=hashlib.sha256(a.manifest.read_bytes()).hexdigest())
        write_json(a.output/'job.json',job)
        try:result=session.execute(job,a.output,out,capture=False)
        finally:
            session.close_process();session.archive_recording(out,a.output,archive_root=a.output.parent);session.archive_logs(a.output)
        write_json(a.output/'result.json',dict(status=result['status'],scope='Fixed prescribed-position coupons; no vehicle qualification',recorder_sha256=hashlib.sha256(RECORDER.encode()).hexdigest()))


if __name__=='__main__':main()
