"""Reproducible CGAL/Blender parameter atlas using an exported assembly frame."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--frame',required=True);p.add_argument('--blender',required=True);p.add_argument('--cgal',required=True)
    p.add_argument('--work',required=True);p.add_argument('--source-label',required=True)
    args=p.parse_args();work=Path(args.work).resolve();work.mkdir(parents=True,exist_ok=True)
    sources=['beamng.cad/FramePipeline/generation/AlphaWrap.py','tools/docs-wrap-blender.py','tools/generate-docs-wrap.py']
    cgal_version=subprocess.check_output([args.cgal,'-c',"import sys,importlib.metadata as m;print(sys.version);print(m.version('cgal'))"],text=True).strip()
    blender_version=subprocess.check_output([args.blender,'--version'],text=True).strip()
    provenance=dict(frame=sha(args.frame),sources={name:sha(ROOT/name) for name in sources},cgal=cgal_version,blender=blender_version)
    stamp=work/'doc-inputs.json'
    if any(work.glob('*/stages.json')) and (not stamp.exists() or json.loads(stamp.read_text())!=provenance):
        raise ValueError('Cached stages belong to different or unrecorded inputs. Choose a new empty work directory.')
    stamp.write_text(json.dumps(provenance,indent=2))
    public=ROOT/'website/public/assets/wrapping';public.mkdir(parents=True,exist_ok=True)
    cases=[]
    for divisor in [4,7,12]:
        for ratio in [20,100,300]:
            key=f'a{divisor}-o{ratio}';folder=work/key
            job=dict(frame=str(Path(args.frame).resolve()),cgal=args.cgal,output=str(folder),divisor=divisor,ratio=ratio,includeSource=not cases)
            jobfile=work/(key+'.job.json');jobfile.write_text(json.dumps(job))
            if not (folder/'stages.json').exists():
                with (work/(key+'.log')).open('w') as log:
                    subprocess.run([args.blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(ROOT/'tools/docs-wrap-blender.py'),'--',str(jobfile)],stdout=log,stderr=subprocess.STDOUT,check=True)
            stages=json.loads((folder/'stages.json').read_text())
            if 'cad' in stages:
                cad=stages.pop('cad');(public/'cad.json').write_text(json.dumps(cad,separators=(',',':')))
                bounds=[[min(v[a] for v in cad['positions']),max(v[a] for v in cad['positions'])] for a in range(3)]
                diagonal=sum((hi-lo)**2 for lo,hi in bounds)**.5
            dest=public/(key+'.json');dest.write_text(json.dumps(stages,separators=(',',':')))
            cases.append(dict(id=key,divisor=divisor,offsetRatio=ratio,alphaM=diagonal/divisor,offsetM=diagonal/divisor/ratio,
                              proxyVertices=len(stages['proxy']['positions']),proxyTriangles=len(stages['proxy']['triangles']),
                              gridVertices=len(stages['grid']['positions']),hullVertices=len(stages['hull']['positions']),hullTriangles=len(stages['hull']['triangles']),sha256=sha(dest)))
            print(key, cases[-1]['proxyTriangles'],'proxy triangles;',cases[-1]['hullVertices'],'hull vertices',flush=True)
    result=dict(version=1,sourceLabel=args.source_label,sourceSha256=sha(args.frame),sourceUnits='metres',diagonalM=diagonal,bounds=bounds,
                grid=[3,5,7],shrinkOffsetM=.01,weldDistanceM=.15,symmetry=False,sourceTriangles=len(cad['triangles']),
                sources=provenance['sources'],software=dict(cgal=cgal_version,blender=blender_version),cases=cases)
    (public/'manifest.json').write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()
