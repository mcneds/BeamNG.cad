from __future__ import annotations
import argparse
import json
from pathlib import Path
from .project import VehicleProject


def main():
    parser=argparse.ArgumentParser(description='Guided CAD vehicle templates, desktop and repeatable build/test API')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('gui');p.add_argument('project',nargs='?')
    p=sub.add_parser('create');p.add_argument('project');p.add_argument('--assembly')
    for command in ('import','validate','build'):
        p=sub.add_parser(command);p.add_argument('project')
    p=sub.add_parser('test');p.add_argument('manifest');p.add_argument('--scenario',default='settle')
    p=sub.add_parser('install');p.add_argument('manifest');p.add_argument('--mods',required=True)
    args=parser.parse_args()
    if args.command=='gui':
        from .gui import run_gui
        return run_gui(args.project)
    if args.command=='create':
        project=VehicleProject.create(args.project,**({'assembly':args.assembly} if args.assembly else {}));print(project.path);return 0
    if args.command in ('import','validate','build'):
        project=VehicleProject.load(args.project)
        if args.command=='import':
            from .assembly import import_assembly
            result=import_assembly(project);print(f'{len(result["objects"])} meshes, {result["triangles"]} triangles')
        elif args.command=='validate':
            errors=project.validate(for_build=True);print('\n'.join(errors) if errors else 'Setup complete');return 1 if errors else 0
        else:
            from .build import build_vehicle
            print(build_vehicle(project))
    elif args.command=='install':
        from .build import install_build
        print(install_build(args.manifest,args.mods))
    elif args.command=='test':
        from frame_harness.vehicle import run_vehicle,run_acceptance
        result=run_acceptance(args.manifest) if args.scenario=='acceptance' else run_vehicle(args.manifest,args.scenario)
        print(json.dumps(result,indent=2));return 0 if result['status']=='passed' else 1
    return 0


if __name__=='__main__':raise SystemExit(main())
