"""Portable native/ideal overlay and exportable plots, with no external assets."""
import json
from pathlib import Path


def write_motion_report(directory, result):
    root=Path(directory)
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    samples=result['samples'];t=[s['t'] for s in samples]
    fig,axes=plt.subplots(3,2,figsize=(12,10),sharex=True,layout='constrained')
    for corner in samples[0]['corners']:
        for axis,key,label in [(axes[0,0],'camber_error_deg','Camber error (degrees)'),(axes[0,1],'toe_error_deg','Toe error (degrees)'),
                               (axes[1,0],'hub_path_error_m','Hub path error (m)'),(axes[1,1],'mount_error_m','Mount displacement (m)')]:
            axis.plot(t,[s['corners'][corner].get(key,float('nan')) for s in samples],label=corner,linewidth=1)
            axis.set_ylabel(label)
    for owner in samples[0]['bodies']:
        axes[2,0].plot(t,[s['bodies'][owner]['shape_error_m'] for s in samples],label=owner,linewidth=.8)
    axes[2,0].set_ylabel('Rigid body shape error (m)')
    axes[2,1].plot(t,[s['lateral_m'] for s in samples],label='Lateral drift (m)')
    axes[2,1].plot(t,[s['yaw_deg'] for s in samples],label='Heading change (degrees)')
    for axis in axes.flat:
        axis.grid(alpha=.25);axis.legend(fontsize=7,loc='upper left')
    for axis in axes[2]:axis.set_xlabel('Simulation time (s)')
    fig.savefig(root/'motion-comparison.png',dpi=140);plt.close(fig)
    data=json.dumps(result,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    document='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Ideal versus simulated suspension motion</title><style>
body{margin:24px auto;padding:0 20px;max-width:1200px;background:#121d28;color:#e6eef3;font:15px system-ui;line-height:1.5}
h1{font-size:28px}.controls{display:flex;gap:20px;flex-wrap:wrap;align-items:center;background:#21313f;padding:16px}button,select{font:inherit;padding:8px;background:#31495b;color:white;border:1px solid #789}input{width:320px}svg{width:100%;background:#172634;border:1px solid #456;margin-top:16px}img{width:100%}a{color:#95daf8}pre{white-space:pre-wrap}#metrics{font-variant-numeric:tabular-nums}.ideal{color:#70d6b6}.actual{color:#ff977d}</style>
<h1>Ideal versus simulated suspension motion</h1><p>The ideal linkage uses the measured hub height and actuator target length. Both overlays are in the fitted chassis coordinate system. Differences show compliance or a constraint failure; the ideal model does not predict road forces, acceleration or vibration frequency.</p>
<div class="controls"><label>Corner <select id="corner"></select></label><label>View <select id="view"><option value="xz">Front (X/Z)</option><option value="xy">Top (X/Y)</option><option value="yz">Side (Y/Z)</option></select></label><input id="time" type="range" min="0" value="0"><button id="play">Play</button><output id="stamp"></output></div>
<p><span class="ideal">Green dashed: ideal</span> · <span class="actual">Orange: simulator</span> · White connectors: positional error</p>
<svg id="scene" viewBox="0 0 1000 520" role="img" aria-label="Ideal and native suspension overlays"></svg><p id="metrics"></p>
<h2>Measured deviations</h2><img src="motion-comparison.png" alt="Camber, toe, hub and mount errors, body distortion and vehicle drift plotted against time">
<p>Screening limits are provisional engineering tolerances, not validated material properties. Snapshot sampling does not resolve high-frequency vibration spectra. Missing or unreachable ideal poses fail the comparison.</p>
<p><a href="motion_comparison.json">Comparison data</a> · <a href="report.html">Scenario report</a></p>
<script>const data=DATA,frames=data.samples,ns='http://www.w3.org/2000/svg';const scene=document.querySelector('#scene'),slider=document.querySelector('#time'),corner=document.querySelector('#corner'),view=document.querySelector('#view');
for(const name of Object.keys(frames[0].corners)){let o=document.createElement('option');o.textContent=name;corner.append(o)}slider.max=frames.length-1;let playing=false,last=0;
const params=new URLSearchParams(location.hash.slice(1));if(frames[0].corners[params.get('corner')])corner.value=params.get('corner');if(params.has('t'))slider.value=frames.reduce((best,f,i)=>Math.abs(f.t-Number(params.get('t')))<Math.abs(frames[best].t-Number(params.get('t')))?i:best,0);
function element(tag,attrs,text){let e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text)e.textContent=text;scene.append(e);return e}
function draw(){scene.replaceChildren();let row=frames[+slider.value],p=row.corners[corner.value],a=p.actual,b=p.ideal||{};let index=view.value==='xz'?[0,2]:view.value==='xy'?[0,1]:[1,2];let all=frames.flatMap(f=>Object.values(f.corners[corner.value].ideal||{}));if(!all.length)all=Object.values(a);let lo=index.map(i=>Math.min(...all.map(v=>v[i]))),hi=index.map(i=>Math.max(...all.map(v=>v[i])));let scale=Math.min(850/Math.max(.2,hi[0]-lo[0]),400/Math.max(.2,hi[1]-lo[1]));
function project(v){return[500+(v[index[0]]-(lo[0]+hi[0])/2)*scale,260-(v[index[1]]-(lo[1]+hi[1])/2)*scale]}
function line(v,w,color,width=3,dash=''){if(!v||!w)return;let[x1,y1]=project(v),[x2,y2]=project(w);element('line',{x1,y1,x2,y2,stroke:color,'stroke-width':width,'stroke-dasharray':dash})}
function pose(q,color,dash){let links=[['shock_top','shock_bottom'],['tie_inner','tie_outer'],['upper_ball','lower_ball'],['hinge_inner','hinge_outer'],['hinge_inner','hub'],['hinge_outer','hub'],['hub','hub_axis']];for(let arm of ['upper','lower'])for(let end of ['inner_front','inner_rear'])links.push([arm+'_'+end,arm+'_ball']);for(let[x,y]of links)line(q[x],q[y],color,3,dash);let labels=[];for(let[name,v]of Object.entries(q)){let[cx,cy]=project(v);element('circle',{cx,cy,r:4,fill:color});if(!dash){let y=cy-7;while(labels.some(p=>Math.abs(p[0]-cx)<120&&Math.abs(p[1]-y)<13))y-=14;labels.push([cx,y]);element('text',{x:cx+6,y,fill:'#becbd6','font-size':11},name)}}}
pose(b,'#70d6b6','7 5');pose(a,'#ff977d','');for(let name of Object.keys(b))if(a[name])line(a[name],b[name],'#fff',1);document.querySelector('#stamp').textContent=row.t.toFixed(2)+' s';
let fmt=(v,n=2)=>v==null?'unavailable':v.toFixed(n);document.querySelector('#metrics').textContent='Camber error '+fmt(p.camber_error_deg)+'° · Toe error '+fmt(p.toe_error_deg)+'° · Hub error '+fmt(p.hub_path_error_m*1000)+' mm · Mount error '+fmt(p.mount_error_m*1000)+' mm · Lateral drift '+fmt(row.lateral_m)+' m'+(p.reachable?'':' · UNREACHABLE: '+p.reason);
}for(let e of [slider,corner,view])e.oninput=draw;document.querySelector('#play').onclick=()=>{playing=!playing;document.querySelector('#play').textContent=playing?'Pause':'Play'};function tick(now){if(playing&&now-last>100){slider.value=(+slider.value+1)%frames.length;draw();last=now}requestAnimationFrame(tick)}draw();requestAnimationFrame(tick);</script></html>'''.replace('DATA',data)
    (root/'motion-comparison.html').write_text(document,encoding='utf-8')
