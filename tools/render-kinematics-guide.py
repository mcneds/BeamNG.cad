"""Standalone, labelled analytical animation using the production linkage solver."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from synthetic_vehicle import recipe
from vehicle_templates import TemplateModel
from vehicle_wizard.kinematics import Mechanism

data={}
for variant in ('primary','independent_rear'):
    model=TemplateModel(recipe(variant));corners={}
    for corner in ('FL','RL'):
        mechanism=Mechanism(model,corner);check=mechanism.inspect();frames=[]
        for height in np.linspace(-.08,.08,81):
            _,pose=mechanism.solve(float(height))
            frames.append({k:v.tolist() for k,v in pose.items()})
        corners[corner]=dict(template=mechanism.template,frames=frames,ratio=check['motion_ratio'])
    data[variant]=corners
document='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>CAD suspension kinematics</title><style>
*{box-sizing:border-box}body{margin:0;background:#111923;color:#e4edf2;font:16px system-ui,sans-serif}main{max-width:1080px;margin:auto;padding:32px}
h1{font-size:32px;margin:8px 0}p{max-width:850px;line-height:1.55}.label{color:#8ed6f2;text-transform:uppercase;letter-spacing:.12em;font-size:12px}
.controls{display:flex;flex-wrap:wrap;gap:18px;align-items:end;background:#1b2835;padding:20px;border-radius:10px}
label{display:grid;gap:6px;font-size:14px}select,button{font:inherit;background:#263c4d;color:#fff;border:1px solid #507187;border-radius:5px;padding:8px}button{cursor:pointer}input{width:230px}
svg{width:100%;height:auto;border:1px solid #304454;border-radius:10px;margin:18px 0;background:#142230}.legend{display:flex;gap:22px;flex-wrap:wrap;font-size:14px}.dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:7px}
.note{border-left:3px solid #ddad69;padding:10px 18px;color:#c6d1d9}a{color:#8ed6f2}output{font-variant-numeric:tabular-nums}
</style><main><div class="label">Analytical mechanism preview</div><h1>One suspension motion, different constraints</h1>
<p>Move the wheel through 160 mm of travel. Both mechanisms use the same production solver as the template checks. This is an analytical illustration; it is not a BeamNG recording or a material-strength result.</p>
<div class="controls"><label>Configuration<select id="variant"><option value="primary">Front wishbone / rear trailing arm</option><option value="independent_rear">Front and rear wishbones</option></select></label>
<label>Corner<select id="corner"><option value="RL">Rear left</option><option value="FL">Front left</option></select></label>
<label>Wheel travel <output id="travel"></output><input id="height" type="range" min="0" max="80" value="40"></label><button id="play">Animate</button></div>
<svg id="scene" viewBox="0 0 980 540" role="img" aria-label="Suspension hardpoints and articulated links"></svg>
<div class="legend"><span><i class="dot" style="background:#ffd18b"></i>Chassis hardpoint</span><span><i class="dot" style="background:#9bd59c"></i>Rigid arm or upright</span><span><i class="dot" style="background:#80ccef"></i>Spring / damper</span><span><i class="dot" style="background:#f59583"></i>Tie or toe link</span></div>
<p id="description"></p><p class="note">A hydro commands length, as used by the steering tie actuator. The suspension spring uses a bounded beam with damping and travel stops. Torsion bars brace thin structures; two separated hinge mounts define the trailing arm's rotation axis. These are separate functions.</p>
<p><a href="../README.md">Workflow and algorithms</a> · <a href="https://documentation.beamng.com/modding/vehicle/sections/">BeamNG section reference</a></p></main>
<script>const data=DATA;
const ns='http://www.w3.org/2000/svg',scene=document.querySelector('#scene'),height=document.querySelector('#height'),variant=document.querySelector('#variant'),corner=document.querySelector('#corner');
let playing=false,tick=0;
function element(tag,attrs){let e=document.createElementNS(ns,tag);for(let [k,v]of Object.entries(attrs))e.setAttribute(k,v);scene.append(e);return e}
function vec(a,b,f=1){return a.map((v,i)=>v+b[i]*f)}function unit(a){let n=Math.hypot(...a);return a.map(v=>v/n)}function cross(a,b){return[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]}
function draw(){let item=data[variant.value][corner.value],p=item.frames[+height.value],ref=item.frames[40].hub;
scene.replaceChildren();document.querySelector('#travel').textContent=((+height.value-40)*2).toFixed(0)+' mm';
function project(a){let q=vec(a,ref,-1);return[625+q[0]*560+q[1]*300,360+q[1]*120-q[2]*520]}
function line(a,b,color,width=5,dash=''){let [x1,y1]=project(a),[x2,y2]=project(b);element('line',{x1,y1,x2,y2,stroke:color,'stroke-width':width,'stroke-linecap':'round','stroke-dasharray':dash})}
function link(a,b,color,width=5,dash=''){line(p[a],p[b],color,width,dash)}
const wish=item.template==='double_wishbone',fixed=wish?['upper_inner_front','upper_inner_rear','lower_inner_front','lower_inner_rear','tie_inner','shock_top']:['hinge_inner','hinge_outer','shock_top'];
if(wish){for(let arm of ['lower','upper']){link(arm+'_inner_front',arm+'_inner_rear','#ffd18b',2,'7 6');for(let inner of ['inner_front','inner_rear'])link(arm+'_'+inner,arm+'_ball','#9bd59c');}link('upper_ball','lower_ball','#9bd59c',9);link('tie_inner','tie_outer','#f59583',4)}
else{link('hinge_inner','hinge_outer','#ffd18b',4,'8 7');for(let hinge of ['hinge_inner','hinge_outer'])link(hinge,'hub','#9bd59c',7)}
link('shock_top','shock_bottom','#80ccef',11);let a=p.shock_top,b=p.shock_bottom;line(a,vec(a,vec(b,a,-1),.45),'#c7eafc',5);
let normal=unit(vec(p.hub_axis,p.hub,-1)),u=unit(cross(normal,[0,0,1])),v=cross(normal,u);let ring=[];
for(let i=0;i<=48;i++){let t=i/48*2*Math.PI,q=vec(vec(p.hub,u,.28*Math.cos(t)),v,.28*Math.sin(t));ring.push(project(q).join(','))}element('polyline',{points:ring.join(' '),fill:'none',stroke:'#a6b8c6','stroke-width':12,opacity:.8});
for(let name of fixed){let [cx,cy]=project(p[name]);element('circle',{cx,cy,r:7,fill:'#ffd18b',stroke:'#142230','stroke-width':2})}
for(let name of (wish?['upper_ball','lower_ball','tie_outer','shock_bottom']:['hub','shock_bottom'])){let[cx,cy]=project(p[name]);element('circle',{cx,cy,r:5,fill:'#fff'})}
let text=element('text',{x:28,y:38,fill:'#e4edf2','font-size':21});text.textContent=wish?'Double wishbone':'Two-point trailing-arm hinge';
text=element('text',{x:28,y:66,fill:'#9db4c4','font-size':14});text.textContent='One free suspension motion · shock motion ratio '+item.ratio.toFixed(3);
document.querySelector('#description').textContent=wish?'The two arms rotate about their inner axes. Ball joints locate the upright, and the tie link constrains steering. The solver checks that the requested travel satisfies all linkage constraints.':'Two separated chassis mounts form one hinge axis. The rigid trailing arm rotates around that axis; it does not need a pair of wishbones or a rear toe link.';
}for(let control of [variant,corner,height])control.addEventListener('input',draw);
document.querySelector('#play').onclick=()=>{playing=!playing;document.querySelector('#play').textContent=playing?'Pause':'Animate'};
function animate(){if(playing){tick+=.018;height.value=Math.round(40+40*Math.sin(tick));draw()}requestAnimationFrame(animate)}draw();animate();
</script></html>'''.replace('DATA',json.dumps(data,separators=(',',':')))
(ROOT/'docs/kinematics.html').write_text(document,encoding='utf-8')
