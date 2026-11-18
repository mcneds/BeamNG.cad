"""Check a frozen preview snapshot with the existing Blender/CGAL hull adapter.

This produces candidate meshes only, never a prepared generation or physical data.
The add-in owns this process and its descendants through a Windows process job.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def check(job_path, run=subprocess.run):
    job_path = Path(job_path)
    job = json.loads(job_path.read_text(encoding='utf-8-sig'))
    frame = Path(job['frame'])
    fingerprint = hashlib.sha256(frame.read_bytes()).hexdigest()
    output = job_path.parent / 'checks'
    output.mkdir(exist_ok=False)
    report = {'source_sha256': fingerprint, 'results': []}
    report_path = job_path.parent / 'check-results.json'

    def save():
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(report_path)

    save()
    for index, ratio in enumerate(job['ratios']):
        folder = output / str(index)
        folder.mkdir()
        hull = dict(job['hull'], ProxyOffsetRatio=ratio)
        candidate = {'frame': str(frame), 'off': str(folder / 'hull.off'),
                     'cgal': job['cgal'], 'hull': hull}
        candidate_path = folder / 'hull-job.json'
        candidate_path.write_text(json.dumps(candidate, allow_nan=False), encoding='utf-8')
        result = {'ratio': ratio, 'off': candidate['off'], 'success': False}
        print(f'Checking candidate ratio {index+1} / {len(job["ratios"])}: {ratio:g}', flush=True)
        try:
            run([job['blender'], '--background', '--factory-startup', '--disable-autoexec',
                 '--python-exit-code', '1', '--python', str(Path(__file__).parent / 'alpha_worker.py'),
                 '--', str(candidate_path)], check=True)
            if not Path(candidate['off']).is_file():
                raise ValueError('Blender produced no candidate mesh')
            if hashlib.sha256(frame.read_bytes()).hexdigest() != fingerprint:
                raise ValueError('Frozen preview snapshot changed during checking')
            result['success'] = True
        except (OSError, subprocess.CalledProcessError, ValueError) as error:
            result['error'] = str(error)
        report['results'].append(result)
        save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path)
    check(parser.parse_args().job)
