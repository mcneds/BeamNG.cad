"""Bounded longitudinal PI diagnostic. It never controls steering or vehicle laws."""
import math

DURATION = 55.
SETTINGS = dict(start_s=4.,ramp_m_s2=.75,kp=.6,ki=.25,brake_scale=.5)

def settings(target,coast_after=None):
    if isinstance(target,bool) or not math.isfinite(target) or not 0<target<=15.:
        raise ValueError('Diagnostic target must be finite, greater than zero and at most 15 m/s')
    result=SETTINGS | dict(target_m_s=target)
    if coast_after is not None:
        if not math.isfinite(coast_after) or not 20<=coast_after<=45:
            raise ValueError('Coast must start between 20 and 45 seconds')
        result['coast_after_s']=coast_after
    return result

def step(speed,time,dt,integral,config):
    """Python oracle for the identical staged Lua controller."""
    if time>=config.get('coast_after_s',math.inf):return 0.,0.,integral
    target=min(config['target_m_s'],max(0.,time-config['start_s'])*config['ramp_m_s2'])
    error=target-speed
    proposal=max(-1.,min(1.,integral+config['ki']*error*dt))
    raw=config['kp']*error+proposal
    if -1<=raw<=1 or (raw>1 and error<0) or (raw< -1 and error>0):integral=proposal
    command=max(-1.,min(1.,config['kp']*error+integral))
    return max(0.,command),max(0.,-command)*config['brake_scale'],integral

LUA='''
local steadyIntegral=0
local function steadyControl(speed,dt)
  local c=job.steady_speed
  if c.coast_after_s and t>=c.coast_after_s then return 0,0 end
  local target=math.min(c.target_m_s,math.max(0,t-c.start_s)*c.ramp_m_s2)
  local error=target-speed
  local proposal=math.max(-1,math.min(1,steadyIntegral+c.ki*error*dt))
  local raw=c.kp*error+proposal
  if (raw>=-1 and raw<=1) or (raw>1 and error<0) or (raw< -1 and error>0) then steadyIntegral=proposal end
  local command=math.max(-1,math.min(1,c.kp*error+steadyIntegral))
  return math.max(0,command),math.max(0,-command)*c.brake_scale
end
'''

def instrument(source):
    anchor='local function updateGFX(dt)'
    branch="elseif job.scenario=='acceleration' then throttle=1"
    if 'local function steadyControl' in source or source.count(anchor)!=1 or source.count(branch)!=1:
        raise ValueError('Steady speed recorder anchors changed')
    # Each probe owns a fresh process/vehicle; the integral begins at zero.
    return source.replace(anchor,LUA+'\n'+anchor).replace(branch,
        "elseif job.scenario=='steady_speed' then throttle,brake=steadyControl(speed,dt)\n    "+branch)
