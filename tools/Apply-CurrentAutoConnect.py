"""Prepare/review an assisted Auto-connect snapshot; apply only with --apply.

Source must still equal the before snapshot. Native CAD is never written.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad'/'FramePipeline'))
import auto_connect
import joint_authoring
import attachment_contract


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--proposals',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=args.snapshot.parent
    original=(root/'before.beamng-project.json').read_bytes()
    if args.source.read_bytes()!=original:raise ValueError('Source project changed; inspect and merge before applying')
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    project=read(args.snapshot);report=read(args.proposals)
    if report['Project']!=project:raise ValueError('Proposals do not match the final CAD snapshot')
    ready=[r for r in report['Rows'] if r['Status']=='ready']
    result=auto_connect.apply(project,[r for r in ready if 'Connections' in r])
    workspace=result['JointWorkspace']
    workspace['Joints']=joint_authoring.proposals(workspace)
    for row in ready:
        if 'Joint' not in row:continue
        joint=copy.deepcopy(row['Joint']);joint['Status']='approved'
        workspace['Joints']=[j for j in workspace['Joints'] if j['Id']!=joint['Id']]+[joint]
        for binding in row['Bindings']:
            if not any(b['Request']==binding['Request'] for b in workspace['Bindings']):workspace['Bindings'].append(binding)
        ids={a['Id'] for a in row['Anchors']}
        result['Anchors']=[a for a in result['Anchors'] if a['Id'] not in ids]+row['Anchors']
    workspace['Mode']='authored'
    # Ensure no assignment, physical property or appearance setting was changed.
    before=read(root/'before.beamng-project.json')
    for old,new in zip(before['Components'],result['Components'],strict=True):
        a,b=copy.deepcopy(old),copy.deepcopy(new)
        for value in (a,b):value.pop('GeometryDirectory',None)
        if a!=b:raise ValueError('Component settings unexpectedly changed: '+old['Name'])
    resolved=joint_authoring.resolve_bindings(result)
    attachments=attachment_contract.resolve(result)
    try:
        joint_authoring.definition(result);definition_error=None
    except ValueError as error:definition_error=str(error)
    summary=dict(status='applied' if args.apply else 'prepared',connections=len(attachments),
                 breakable_fasteners=sum(bool(m['group']) for m in attachments),
                 approved_joints=sum(j['Status']=='approved' for j in workspace['Joints']),
                 hardpoint_bindings=len(resolved),definition_error=definition_error,
                 remaining=[{k:r.get(k) for k in ('Id','Name','Issue')} for r in report['Rows'] if r['Status']=='needs_input'])
    encoded=json.dumps(result,indent=2,allow_nan=False).encode('utf-8')
    (root/'applied-project.json').write_bytes(encoded)
    if args.apply:
        if args.source.read_bytes()!=original:raise ValueError('Source changed before write')
        backup=Path(str(args.source)+'.before-assisted-mounts.bak')
        with backup.open('xb') as stream:stream.write(original)
        temp=Path(str(args.source)+'.autoconnect.tmp')
        with temp.open('xb') as stream:stream.write(encoded)
        os.replace(temp,args.source)
        summary['backup']=str(backup)
    (root/'application-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='remaining'},indent=2))


if __name__=='__main__':main()
