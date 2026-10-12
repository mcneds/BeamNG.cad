"""Fresh calibration and timed Quick/Full runs of an unchanged reviewed generation."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import calibration_worker as worker
from frame_harness.build import write_json, sha256
from frame_harness.calibration import graph_identity,load_part
from frame_harness.retention import apply_retention


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--action',choices=['prepare','quick','full'],required=True)
    parser.add_argument('--profile',type=Path,default=Path(r'H:\BeamNGCadHarness\drive'))
    parser.add_argument('--game',type=Path,default=Path(r'D:\SteamLibrary\steamapps\common\BeamNG.drive'))
    args=parser.parse_args();baseline=args.baseline.resolve();job=args.output.resolve()
    os.environ['BEAMNG_CAD_CANCEL']=str(job/'benchmark-cancel.signal')
    worker.preflight()
    if args.action=='prepare':
        worker.check_snapshot(baseline)
        worker.prepare(baseline/'source',job,baseline)
        old=worker.read(baseline/'review.json');review=worker.read(job/'review.json')
        if not old['approved']:raise ValueError('Baseline fixtures were not approved')
        if graph_identity(load_part(job/'source/mochi_raw.jbeam'))!=graph_identity(load_part(baseline/'source/mochi_raw.jbeam')):
            raise ValueError('Benchmark graph differs; manual fixture review required')
        for name in ('cad_source.dae','material-snapshot.json'):
            if sha256(job/'source'/name)!=sha256(baseline/'source'/name):raise ValueError('Benchmark input differs: '+name)
        review.update(fixtures=old['fixtures'],cut_fixture=old['cut_fixture'],approved=True,
                      approval=dict(kind='unchanged reviewed benchmark',baseline=str(baseline),graph=old['graph_sha256']))
        write_json(job/'review.json',review)
        worker.calibrate(job,save_report=False)
        return
    started=time.monotonic()
    quick=worker.calibrate(job,resume=True,live=True,game=args.game,profile=args.profile,
                          verification=args.action,save_report=False)
    elapsed=time.monotonic()-started
    state=worker.read(job/'study/calibration-study.json')
    summary=apply_retention(job,state,False,quick=quick if args.action=='quick' else None)
    timing=dict(mode=args.action,wall_seconds=elapsed,result=summary,baseline=str(baseline))
    write_json(job/('benchmark-'+args.action+'.json'),timing)
    print('BENCHMARK '+json.dumps(timing),flush=True)


if __name__=='__main__':main()
