"""Check sampled native device laws without assuming front/rear torque paths."""
import math


def sampled_checks(contract,samples):
    active=[s for s in samples if s.get('t',0)>14]
    checks={};metrics={}
    if not active:return dict(graph_device_rate_samples=False),metrics
    def finite(value):return isinstance(value,(int,float)) and math.isfinite(value)
    for name,decl in contract['devices'].items():
        ports=[];laws=[];locks=[]
        for sample in active:
            row=sample.get('devices',{}).get(name,{})
            parent=sample.get('devices',{}).get(decl.get('inputName'),{})
            incoming=row.get('input_av');out=row.get('output_av');ratio=row.get('ratio',decl.get('gearRatio',1.))
            if decl.get('inputName'):
                upstream=parent.get('output_av2' if decl['inputIndex']==2 else 'output_av')
                if finite(incoming) and finite(upstream):ports.append(abs(incoming-upstream)/(1+max(abs(incoming),abs(upstream))))
            kind=decl['type']
            if kind in ('shaft','cvtGearbox') and all(finite(v) for v in (incoming,out,ratio)):
                target=out*ratio;laws.append(abs(incoming-target)/(1+max(abs(incoming),abs(target))))
            elif kind in ('differential','splitShaft'):
                other=row.get('output_av2')
                if all(finite(v) for v in (incoming,out,other,ratio)):
                    target=((out+other)*.5 if kind=='differential' else out if decl.get('primaryOutputID',1)==1 else other)*ratio
                    laws.append(abs(incoming-target)/(1+max(abs(incoming),abs(target))))
                    if kind=='splitShaft':locks.append(abs(out-other)/(1+max(abs(out),abs(other))))
        if decl.get('inputName'):
            checks[name+'_input_rate_matches_port']=len(ports)==len(active) and max(ports,default=math.inf)<.01
        if decl['type'] in ('shaft','cvtGearbox','differential','splitShaft'):
            checks[name+'_native_ratio_law']=len(laws)==len(active) and max(laws,default=math.inf)<.01
        if decl['type']=='splitShaft':
            error=sum(locks)/len(locks) if locks else None;metrics[name+'_mean_locked_output_rate_error']=error
            checks[name+'_locked_output_rates']=len(locks)==len(active) and error is not None and error<.05
    return checks,metrics
