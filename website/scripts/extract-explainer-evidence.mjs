// Explicitly select a compact, public set of measurements; never publish raw local paths.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const project=new URL('../../',import.meta.url);
const source='docs/evidence/mvp-checkpoint-20261009.json';
const raw=readFileSync(new URL(source,project));
const checkpoint=JSON.parse(raw);
const names={primary:'Trailing arm / geared AWD',variant:'Rear wishbone / RWD'};
const cases=Object.entries(names).map(([key,label])=>{
  const build=checkpoint.builds[key];
  if(!build)throw new Error(`Missing historical fixture ${key}`);
  const d=build.driving;
  for(const value of [d.lateral_drift_m,d.broken_beams,d.applied_steering,d.completed_runs,d.required_runs])if(!Number.isFinite(value))throw new Error('Incomplete source measurements');
  return {key,label,lateralDriftM:d.lateral_drift_m,brokenBeams:d.broken_beams,appliedSteering:d.applied_steering,completedRuns:d.completed_runs,requiredRuns:d.required_runs,status:d.status,receiptSha256:d.receipt_sha256};
});
const limitSource='docs/mvp-checkpoint-20261009.md';
const limits=readFileSync(new URL(limitSource,project));
if(!limits.toString('utf8').includes('0.5 m'))throw new Error('Review the documented historical drift limit');
const result={date:'2026-10-09',scope:checkpoint.scope,status:checkpoint.status,source,sourceSha256:createHash('sha256').update(raw).digest('hex'),limitSource,limitSourceSha256:createHash('sha256').update(limits).digest('hex'),lateralLimitM:.5,cases};
const output=new URL('../src/data/checkpoint.json',import.meta.url);
mkdirSync(fileURLToPath(new URL('.',output)),{recursive:true});writeFileSync(output,JSON.stringify(result,null,2)+'\n');
console.log('Extracted two historical acceleration summaries with source hashes; no raw recordings or local paths published.');
