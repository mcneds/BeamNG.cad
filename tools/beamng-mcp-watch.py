"""Read-only, bounded MCP monitoring during a user's manual BeamNG reproduction."""
import argparse,datetime,json,time,urllib.request
from pathlib import Path


def call(name,args=None):
    payload=json.dumps(dict(jsonrpc='2.0',id=time.time_ns(),method='tools/call',params=dict(name=name,arguments=args or {}))).encode()
    request=urllib.request.Request('http://127.0.0.1:29292/mcp',data=payload,headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
    with urllib.request.urlopen(request,timeout=5) as response:raw=response.read().decode()
    if raw.startswith('event:') or raw.startswith('data:'):
        raw=next(line[5:].strip() for line in raw.splitlines() if line.startswith('data:'))
    result=json.loads(raw)
    if 'error' in result:raise ValueError(result['error'])
    blocks=result.get('result',{}).get('content',[])
    texts=[b['text'] for b in blocks if b.get('type')=='text']
    if result.get('result',{}).get('isError'):return dict(tool_error=texts)
    if len(texts)==1:
        try:return json.loads(texts[0])
        except ValueError:return texts[0]
    return texts


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--seconds',type=float,default=1800);a=p.parse_args()
    if not 1<=a.seconds<=3600:raise ValueError('Monitoring is limited to one hour')
    a.output.mkdir(parents=True,exist_ok=False);start=time.monotonic();connected=False;last_events=None;count=0
    with (a.output/'observations.jsonl').open('w',encoding='utf-8',buffering=1) as file:
        while time.monotonic()-start<a.seconds:
            row=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsed_s=time.monotonic()-start)
            try:
                row['status']=call('get_status');row['instability']=call('get_instability',{'clear':False})
                vehicle=(row['status'].get('vehicle') or {}) if isinstance(row['status'],dict) else {}
                if vehicle.get('id'):
                    row['electrics']=call('get_electrics',dict(id=vehicle['id'],keys=['rpm','wheelspeed','gear','throttle','brake','steering']))
                    row['damage']=call('get_vehicle_damage',dict(id=vehicle['id']))
                events=json.dumps(row['instability'],sort_keys=True)
                if events!=last_events:
                    row['logs']=call('get_logs',{'lines':100});last_events=events
                    print(json.dumps(dict(event='instability_snapshot',data=row['instability'])),flush=True)
                if not connected:print('MCP_MONITOR_CONNECTED',flush=True)
                connected=True;count+=1
            except Exception as error:
                row['connection_error']=str(error)
                if connected:print('MCP connection interrupted: '+str(error),flush=True)
                connected=False
            file.write(json.dumps(row,allow_nan=False)+'\n')
            (a.output/'status.json').write_text(json.dumps(dict(connected=connected,samples=count,last=row['utc'],elapsed_s=row['elapsed_s'],duration_s=a.seconds)))
            time.sleep(1 if connected else 3)
    (a.output/'complete.json').write_text(json.dumps(dict(samples=count,duration_s=time.monotonic()-start)))


if __name__=='__main__':main()
