"""Native scalar force/displacement check of the production crossover beam."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from coilover_springs import rates,crossover_beam
from frame_harness import build
from frame_harness.models import HarnessProject,ParameterSet,TestScenario
from frame_harness.runner import run_test
from frame_harness.session import DriveSession

output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
law=rates(dict(Mode='dual_rate',MainRateNPerM=6000,TenderRateNPerM=3000,CrossoverCompressionM=.15),1.,.5)
original=build.spring_fixture
def fixture(parameters):
    data=original(parameters);part=data['mochi'];part['nodes'][1]['nodeWeight']=2
    part['beams'][2].append(dict(beamType='|BOUNDED',beamLongBound=1,beamShortBound=1,beamLimitSpring=0,beamLimitDamp=0))
    # Symmetric long lateral stays resist buckling without materially changing
    # vertical stiffness (< 1% contribution across this test). Centimetres of
    # travel keep float-position quantization below the unchanged telemetry gate.
    part['nodes'][3][2]=10;part['nodes'][4][1]=10
    part['nodes'].extend([['d',0,-10,1],['e',-10,0,1]])
    part['beams'].extend([['d','p'],['e','p']])
    part['beams'].append(['a','p',crossover_beam(law)])
    return data

project=HarnessProject(source=Path('H:/beamng project programs/BeamNG.cad/Test Programs'),userpath=Path('H:/BeamNGCadHarness/drive'),runs=output)
results=[]
with patch.object(build,'spring_fixture',side_effect=fixture),DriveSession(project) as session:
    for force in (100.,200.,800.,1000.):
        scenario=TestScenario('spring',10.,0.,fixed_nodes=['a','b','c','d','e'],load_nodes=['p'],force_n=force,settle_s=1.,ramp_s=2.,hold_s=5.)
        result=run_test(project,scenario,ParameterSet(name='dual-'+str(force),spring_scale=2,damping_scale=10),session=session,save_report=False)
        directory=Path(result.path)
        telemetry=directory/json.loads((directory/'telemetry_location.json').read_text())['directory']
        metadata=json.loads((telemetry/'metadata.json').read_text())
        names={v['name']:v['cid'] for v in metadata['nodes']}
        if result.status!='completed':raise RuntimeError('Native recording failed: '+str(result.failure_reason))
        rows=np.genfromtxt(telemetry/'nodes.csv',delimiter=',',names=True)
        hold=rows[(rows['t']>6)&(rows['t']<7.5)]
        displacement=1-(np.mean(hold[hold['cid']==names['p']]['z'])-np.mean(hold[hold['cid']==names['a']]['z']))
        initial_rate=law['initial_rate_n_m'];cross=law['crossover_compression_m'];final_rate=law['final_rate_n_m']
        expected=force/initial_rate if force<=initial_rate*cross else cross+(force-initial_rate*cross)/final_rate
        if result.metrics.get('hold_settled') is not True or result.metrics.get('broken_beams')!=0:raise RuntimeError('Spring fixture did not settle intact')
        results.append(dict(force_n=force,compression_m=float(displacement),expected_compression_m=expected,
                            recording_status=result.status,directory=str(directory)))
initial=(results[1]['force_n']-results[0]['force_n'])/(results[1]['compression_m']-results[0]['compression_m'])
final=(results[3]['force_n']-results[2]['force_n'])/(results[3]['compression_m']-results[2]['compression_m'])
accepted=abs(initial/2000-1)<.05 and abs(final/6000-1)<.05 and all(abs(r['compression_m']/r['expected_compression_m']-1)<.01 for r in results)
evidence=dict(status='passed' if accepted else 'failed',law=law,initial_rate_n_m=initial,final_rate_n_m=final,expected_initial_rate_n_m=2000,expected_final_rate_n_m=6000,runs=results)
(output/'verification.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence,indent=2))
if not accepted:sys.exit(1)
