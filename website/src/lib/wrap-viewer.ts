import * as THREE from 'three/webgpu';
import { color, positionLocal, uniform, smoothstep, mix } from 'three/tsl';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

type MeshData={positions:number[][];triangles:number[][];edges:number[][];names?:string[];addedEdges?:number[][];nodeCount?:number;beamCount?:number;rank?:number};
type Case={id:string;divisor:number;offsetRatio:number;alphaM:number;offsetM:number;proxyVertices:number;proxyTriangles:number;hullVertices:number;hullTriangles:number;graphNodes:number;graphBeams:number};
type Manifest={bounds:number[][];cases:Case[]};
const notes:Record<string,string>={
  cad:'The selected frame bodies keep their assembly positions. These triangles are the geometric input, not a beam network.',
  proxy:'CGAL constructs a closed outside envelope. Smaller alpha can follow narrower openings; a smaller offset hugs the CAD more closely and generally adds triangles.',
  grid:'Keep cells touching the proxy and empty cells enclosed behind it. Flood-fill removes empty cells reachable from outside. Only the retained boundary is shown.',
  projected:'Project boundary vertices to the ORIGINAL CAD surface, then apply the projection offset. The proxy is not the projection target.',
  hull:'Weld nearby projected vertices. This reduces slivers and duplicate points, but an excessive weld distance also merges intended detail.',
  graph:'Triangulated surface edges connect the shell nodes. An internal cage and local attachments remove unsupported internal motions. Orange edges are internal supports.',
  braced:'Local tetrahedra and nearest-node links add load paths before calibration. Blue edges are the base graph; orange edges are the added braces. These initial springs are not calibrated material properties.',
};
async function json<T>(url:string,signal:AbortSignal):Promise<T>{const response=await fetch(url,{signal});if(!response.ok)throw new Error('Could not load '+url);return response.json();}

export async function mountWrapExplorer(root:HTMLElement,signal:AbortSignal){
  const [manifest,cad]=await Promise.all([json<Manifest>('/assets/wrapping/manifest.json',signal),json<MeshData>('/assets/wrapping/cad.json',signal)]);
  const viewport=root.querySelector<HTMLElement>('[data-viewport]')!;
  const renderer=new THREE.WebGPURenderer({antialias:true,alpha:false});
  let disposed=false;
  try { await renderer.init(); } catch(error) { renderer.dispose(); throw error; }
  if(signal.aborted){renderer.dispose();throw new DOMException('Cancelled','AbortError');}
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  root.dataset.backend='isWebGPUBackend' in renderer.backend&&renderer.backend.isWebGPUBackend?'WebGPU':'WebGL2';
  renderer.domElement.setAttribute('aria-label','Orbitable frame geometry. Drag to rotate; scroll to zoom. Use the view buttons for fixed views.');
  renderer.domElement.setAttribute('role','img');
  viewport.append(renderer.domElement);root.querySelector<HTMLElement>('[data-fallback]')!.hidden=true;
  const scene=new THREE.Scene();scene.background=new THREE.Color('#111923');
  const center=new THREE.Vector3(...manifest.bounds.map(([lo,hi])=>(lo+hi)/2) as [number,number,number]);
  const extent=Math.max(...manifest.bounds.map(([lo,hi])=>hi-lo));
  const camera=new THREE.PerspectiveCamera(38,1,extent/100,extent*100);camera.up.set(0,0,1);
  const controls=new OrbitControls(camera,renderer.domElement);controls.target.copy(center);controls.enableDamping=false;controls.minDistance=extent*.3;controls.maxDistance=extent*6;
  scene.add(new THREE.HemisphereLight(0xd9eaff,0x38424f,2.3));
  const sun=new THREE.DirectionalLight(0xffffff,3);sun.position.set(-2,-3,5);scene.add(sun);
  const geometry=(data:MeshData)=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(data.positions.flat(),3));if(data.triangles.length)g.setIndex(data.triangles.flat());g.computeVertexNormals();return g;};
  const cadMaterial=new THREE.MeshStandardNodeMaterial({roughness:.7,metalness:.2,transparent:true,opacity:.2,depthWrite:false,side:THREE.DoubleSide});cadMaterial.colorNode=color('#d1dce7');
  const cadMesh=new THREE.Mesh(geometry(cad),cadMaterial);scene.add(cadMesh);
  const layer=new THREE.Group();scene.add(layer);
  const gpuResources:(THREE.BufferGeometry|THREE.Material)[]=[cadMesh.geometry,cadMaterial];
  const clear=()=>{for(const child of [...layer.children]){if(child instanceof THREE.Mesh||child instanceof THREE.LineSegments||child instanceof THREE.Points){child.geometry.dispose();(child.material as THREE.Material).dispose();}layer.remove(child);}};
  const render=()=>{if(!disposed&&!document.hidden)renderer.render(scene,camera);};
  const resize=()=>{const w=viewport.clientWidth,h=viewport.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false);render();};
  const observer=new ResizeObserver(resize);observer.observe(viewport);
  controls.addEventListener('change',render);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)render();},{signal});
  let stage='proxy',version=0;const cache=new Map<string,Record<string,MeshData>>();
  const divisor=root.querySelector<HTMLSelectElement>('[data-divisor]')!,ratio=root.querySelector<HTMLSelectElement>('[data-ratio]')!,overlay=root.querySelector<HTMLInputElement>('[data-overlay]')!;
  const status=root.querySelector<HTMLElement>('[data-status]')!;
  renderer.onDeviceLost=()=>{if(!disposed){status.textContent='Graphics device lost. Reload this page to restart the 3D view.';root.querySelector<HTMLElement>('[data-fallback]')!.hidden=false;renderer.domElement.hidden=true;}};
  const line=(data:MeshData,edges:number[][],hex:string)=>{
    const g=new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(edges.flatMap(e=>e.flatMap(i=>data.positions[i])),3));
    const mat=new THREE.LineBasicNodeMaterial();mat.colorNode=color(hex);layer.add(new THREE.LineSegments(g,mat));
  };
  const update=async()=>{
    const request=++version;status.textContent='Loading computed result…';
    const item=manifest.cases.find(c=>c.divisor===Number(divisor.value)&&c.offsetRatio===Number(ratio.value))!;
    try {
      let data=cache.get(item.id);if(!data){data=await json<Record<string,MeshData>>(`/assets/wrapping/${item.id}.json`,signal);cache.set(item.id,data);}
      if(disposed||request!==version)return;
      clear();cadMesh.visible=overlay.checked||stage==='cad';cadMaterial.opacity=stage==='cad'?1:.18;cadMaterial.depthWrite=stage==='cad';
      const selected=data[stage==='braced'?'graph':stage];
      if(stage==='graph'||stage==='braced'){
        const graph=data.graph;
        if(stage==='graph'){
          const isShell=(edge:number[])=>edge.every(i=>graph.names![i].startsWith('sh'));
          line(graph,graph.edges.filter(isShell),'#70b6fa');line(graph,graph.edges.filter(e=>!isShell(e)),'#ffb15d');
        }else line(graph,graph.edges,'#70b6fa');
        if(stage==='braced')line(graph,graph.addedEdges!,'#ffb15d');
        const points=new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(graph.positions.flat(),3));
        const dots=new THREE.PointsNodeMaterial({size:3,sizeAttenuation:false});dots.colorNode=color('#dcecff');layer.add(new THREE.Points(points,dots));
      }else if(stage!=='cad'){
        const mesh=geometry(selected);
        const mat=new THREE.MeshStandardNodeMaterial({side:THREE.DoubleSide,transparent:true,opacity:.58,depthWrite:false,roughness:.65});
        // TSL height shading makes ridges readable without displacing the recorded vertices.
        const lo=uniform(manifest.bounds[2][0]),hi=uniform(manifest.bounds[2][1]);
        mat.colorNode=mix(color('#216b94'),color('#8ddbcf'),smoothstep(lo,hi,positionLocal.z));
        layer.add(new THREE.Mesh(mesh,mat));line(selected,selected.edges,'#95dce8');
      }
      root.querySelector('[data-parameters]')!.textContent=`α = ${item.alphaM.toFixed(3)} m · CGAL offset = ${(item.offsetM*1000).toFixed(2)} mm`;
      root.querySelector('[data-explanation]')!.textContent=notes[stage];
      root.querySelector('[data-metrics]')!.textContent=stage==='graph'||stage==='braced'?`${item.graphNodes} nodes · ${stage==='braced'?item.graphBeams:data.graph.edges.length} beams · required rigidity rank ${data.graph.rank}`:stage==='cad'?`${cad.positions.length.toLocaleString()} vertices · ${cad.triangles.length.toLocaleString()} input triangles`:`${selected.positions.length} vertices · ${selected.triangles.length} triangles`;
      status.textContent='Drag to orbit · scroll or pinch to zoom. Recorded geometry; dimensions are in metres.';
      root.dataset.case=item.id;root.dataset.stage=stage;root.dataset.ready='true';render();
    }catch(error){if(!signal.aborted)status.textContent='Result unavailable. '+(error instanceof Error?error.message:'');}
  };
  const view=(name:string)=>{
    const offsets:Record<string,number[]>={perspective:[1.4,-1.7,1.1],side:[1,0,.001],top:[0,0,1]};
    const direction=new THREE.Vector3(...offsets[name] as [number,number,number]).normalize();
    camera.aspect=viewport.clientWidth/viewport.clientHeight;camera.updateProjectionMatrix();
    camera.position.copy(center).add(direction);camera.lookAt(center);
    const inverse=camera.quaternion.clone().invert(),tan=Math.tan(THREE.MathUtils.degToRad(camera.fov/2));
    let distance=0;
    for(const x of manifest.bounds[0])for(const y of manifest.bounds[1])for(const z of manifest.bounds[2]){
      const corner=new THREE.Vector3(x,y,z).sub(center).applyQuaternion(inverse);
      distance=Math.max(distance,Math.abs(corner.y)/tan+corner.z,Math.abs(corner.x)/(tan*camera.aspect)+corner.z);
    }
    camera.position.copy(center).add(direction.multiplyScalar(distance*1.2));controls.target.copy(center);controls.update();render();
  };
  root.querySelectorAll<HTMLButtonElement>('[data-stage]').forEach(button=>{button.disabled=false;button.addEventListener('click',()=>{stage=button.dataset.stage!;root.querySelectorAll('[data-stage]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));void update();},{signal});});
  root.querySelectorAll<HTMLButtonElement>('[data-view]').forEach(button=>{button.disabled=false;button.addEventListener('click',()=>view(button.dataset.view!),{signal});});
  [divisor,ratio,overlay].forEach(input=>{input.disabled=false;input.addEventListener('change',()=>void update(),{signal});});
  renderer.domElement.addEventListener('webglcontextlost',()=>{status.textContent='Graphics context lost. Reload the page to restart the 3D view.';},{signal});
  const cleanup=()=>{if(disposed)return;disposed=true;observer.disconnect();controls.dispose();clear();gpuResources.forEach(r=>r.dispose());renderer.dispose();renderer.domElement.remove();};
  signal.addEventListener('abort',cleanup,{once:true});
  try { view('perspective');resize();await update(); } catch(error) { cleanup(); root.querySelector<HTMLElement>('[data-fallback]')!.hidden=false; throw error; }
  if(signal.aborted)cleanup();
  return cleanup;
}
