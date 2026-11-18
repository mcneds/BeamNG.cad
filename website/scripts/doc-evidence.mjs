import { readFileSync,writeFileSync,readdirSync,existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve,relative } from 'node:path';
import { fileURLToPath } from 'node:url';
export const site=resolve(fileURLToPath(new URL('../',import.meta.url)));
const root=resolve(site,'..'),file=resolve(site,'src/data/doc-evidence.json');
export const definitions={
  'frame-generation':{label:'Frame wrapping and graph generation',sources:['beamng.cad/FramePipeline/generation','beamng.cad/FramePipeline/alpha_worker.py','beamng.cad/FramePipeline/prepare_frame.py','dependencies/cad-calibration/Test Harness/frame_harness/bracing.py'],refresh:'Regenerate the CGAL atlas, graph layers and fallback preview; review parameter names and graph construction.'},
  'frame-calibration':{label:'Frame calibration and numerical limits',sources:['beamng.cad/FramePipeline/calibration_worker.py','dependencies/cad-calibration/Test Harness/frame_harness/calibration.py','dependencies/cad-calibration/Test Harness/frame_harness/elastic_fit.py','dependencies/cad-calibration/Test Harness/frame_harness/projection.py'],refresh:'Review fit settings, acceptance limits and mass/stiffness policies. Recorded data stays dated; regenerate only from a reviewed calibration snapshot.'},
  'mate-compilation':{label:'Native mate compilation and ownership',sources:['beamng.cad/FramePipeline/joint_authoring.py','beamng.cad/FramePipeline/joint_contract.py','beamng.cad/FramePipeline/translating_rack.py','beamng.cad/Preparation/NativeMateScanner.cs'],refresh:'Re-run the mate evidence exporter on captured native records; compare matrix ranks, joint kinds and supported realizations.'},
  'vehicle-generation':{label:'Vehicle generation and component representations',sources:['beamng.cad/FramePipeline'],refresh:'Review component defaults, physical settings, spring equations and drivetrain contracts. Refresh affected plots and example output.'},
  'verification':{label:'Verification criteria and recorded results',sources:['dependencies/cad-calibration/Test Harness/frame_harness'],refresh:'Review scenario counts, tolerances, status meanings and telemetry fields. Preserve the dates and source hashes of historical recordings.'},
  'application':{label:'CAD workflow, settings and UI',sources:['beamng.cad/Preparation','beamng.cad/UI','beamng.cad/MainSwAddIn.cs'],refresh:'Review instruction steps, UI labels and screenshots. Replace screenshots only after the UI stabilizes.'},
  'website':{label:'Documentation tooling and deployment',sources:['website/package.json','website/astro.config.mjs','website/scripts/deploy.mjs'],refresh:'Review runtime versions, build commands and Cloudflare deployment instructions.'},
};
export function groupFor(slug){
  if(/wrapping/.test(slug))return 'frame-generation';
  if(/calibration/.test(slug))return 'frame-calibration';
  if(/joints/.test(slug))return 'mate-compilation';
  if(/verification|milestones|testing/.test(slug))return 'verification';
  if(/contributors\/(documentation|deployment)/.test(slug))return 'website';
  if(/concepts|reference\/(templates|files|cli)/.test(slug))return 'vehicle-generation';
  return 'application';
}
// Track published datasets and the programs that produce/render each plot too.
definitions['frame-generation'].sources.push('website/public/assets/wrapping', 'tools/generate-docs-wrap.py', 'tools/docs-wrap-blender.py', 'tools/generate-docs-graph.py', 'website/src/lib/wrap-viewer.ts', 'website/src/components/explainers/WrapExplorer.astro');
definitions['frame-calibration'].sources.push('website/src/data/frame-tuning.json', 'tools/generate-docs-evidence.py', 'website/src/components/explainers/TuningExplorer.astro');
definitions['mate-compilation'].sources.push('website/src/data/mate-compilation.json', 'tools/generate-docs-evidence.py', 'website/src/components/explainers/MateExplorer.astro');
definitions['vehicle-generation'].sources.push('website/src/lib/explainers.ts', 'website/src/components/explainers/SpringExplorer.astro');
definitions.verification.sources.push('website/src/data', 'website/src/components/explainers/EvidenceChart.astro');
definitions.verification.sources.push('tools/probe-drive-execution.py', 'tools/steady_speed_control.py', 'tools/analyze-low-speed.py', 'tools/analyze-suspension-frequency.py');
definitions.verification.sources.push('tools/probe-driveline.py', 'tests/test_driveline.py');
for(const group of ['frame-generation','frame-calibration','mate-compilation'])definitions[group].sources.push('website/src/components/explainers/explorers.css');
definitions.website.sources.push('website/scripts/doc-evidence.mjs','website/scripts/remark-doc-evidence.mjs','website/scripts/check-links.mjs','website/src/components/ReviewedPageTitle.astro');
definitions.website.sources.push('website/src/components/ReviewedMarkdownContent.astro');
definitions.application.sources.push('beamng.cad/FramePipeline/preview_search_worker.py');
definitions.application.sources.push('beamng.cad/FramePipeline/driveline.py', 'beamng.cad/FramePipeline/driveline_physics.py', 'beamng.cad/FramePipeline/driveline_presets.py');
function filesAt(path){
  if(!existsSync(path))throw new Error('Missing documentation source '+relative(root,path));
  try { return readdirSync(path,{withFileTypes:true}).filter(e=>!['__pycache__','bin','obj'].includes(e.name)).flatMap(e=>filesAt(resolve(path,e.name))); }
  catch(e){if(e.code!=='ENOTDIR')throw e;return !path.endsWith('doc-evidence.json')&&/\.(py|cs|json|mjs|lua|ts|astro|svg|comp|vert|frag)$/.test(path)?[path]:[];}
}
export function sourceHashes(group){return Object.fromEntries([...new Set(definitions[group].sources.flatMap(s=>filesAt(resolve(root,s))))].sort().map(p=>[relative(root,p).replaceAll('\\','/'),createHash('sha256').update(readFileSync(p)).digest('hex')]));}
export function registry(){return existsSync(file)?JSON.parse(readFileSync(file,'utf8')):{version:1,groups:{}};}
export function changes(group,record=registry()){const now=sourceHashes(group),old=record.groups[group]?.hashes??{};return [...new Set([...Object.keys(now),...Object.keys(old)])].filter(p=>now[p]!==old[p]);}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  if(!existsSync(resolve(root,'beamng.cad/FramePipeline'))){
    if(process.argv.includes('--strict')||process.argv.includes('--review'))throw new Error('Reviewing source changes requires the full repository checkout.');
    console.log('Website-only build: using saved documentation evidence snapshots. Run docs:check in the full repository to review implementation changes.');
    process.exit(0);
  }
  const record=registry();const reviewing=process.argv.includes('--review'),which=process.argv.find(a=>a.startsWith('--group='))?.slice(8);
  const selected=which?[which]:Object.keys(definitions);if(selected.some(g=>!definitions[g]))throw new Error('Unknown documentation evidence group');
  if(reviewing){for(const group of selected)record.groups[group]={...definitions[group],reviewed:new Date().toISOString().slice(0,10),hashes:sourceHashes(group)};writeFileSync(file,JSON.stringify(record,null,2)+'\n');console.log('Recorded reviewed source hashes: '+selected.join(', '));}
  else {
    const stale=selected.map(group=>({group,files:changes(group,record)})).filter(r=>r.files.length);
    for(const {group,files} of stale)console.warn(`Documentation review needed: ${group}\n${files.map(p=>'  '+p).join('\n')}\n  ${definitions[group].refresh}`);
    console.log(`${selected.length-stale.length}/${selected.length} documentation source groups match their reviewed snapshots.`);
    if(stale.length&&process.argv.includes('--strict'))process.exitCode=1;
  }
}
