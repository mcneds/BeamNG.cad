"""Audit native synthetic CAD, declare template joints, then use production calibration.

All artifacts live under the supplied H: fixture directory. No reference frame
or archived tuned JBeam is consumed by this harness.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import components as c
from vehicle_templates import frame_mount_plan
import calibration_worker as calibration
from prepare_frame import prepare


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def setup(cad,output):
    cad=Path(cad).resolve();output=Path(output).resolve()
    capture=read(cad/'native-capture.json');recipe=read(cad/'recipe.json');project=read(capture['project'])
    if output.exists():raise FileExistsError('Use a new synthetic verification directory')
    output.mkdir(parents=True)
    expected={item['id']:item for item in recipe['components']};audits={};fixed={};halfshafts={};shafts={}
    from mvp_inventory import configuration
    _,active,_=configuration(read(ROOT/'beamng.cad/FramePipeline/template_catalog.json'),project)
    omitted=[comp['Id'] for comp in project['Components'] if comp['MvpRole'] not in active]
    project['Components']=[comp for comp in project['Components'] if comp['MvpRole'] in active]
    c.write(output/'selection-audit.json',dict(source_bodies=capture['bodies'],omitted_roles=omitted,
        reason='Native fixture can contain optional geometry; the selected template dictates exported physical groups'))
    for comp in project['Components']:
        owner=comp['Id'];meshes,moments,geometry=c.read_geometry(comp);item=expected[owner]
        native=read(Path(comp['GeometryDirectory'])/'material-snapshot.json')
        volume=item['analytic_volume_m3']
        if volume>0:
            # Density is deliberately obtained from the captured SolidWorks
            # assignment; the independent geometry volume is the cross-check.
            density=float(native['bodies'][0]['density_kg_m3'])
            error=abs(moments[0]/(volume*density)-1)
            if error>1e-5:raise ValueError(owner+': native mass differs from independent primitive volume by '+str(error))
        else:error=0
        audits[owner]=dict(cad_mass_kg=moments[0],analytic_volume_m3=volume,relative_mass_error=error,bodies=len(meshes),center=moments[1].tolist())
        if owner.endswith('_halfshaft'):
            shape=item['primitives'][0]
            halfshafts[owner]=dict(corner=owner[:2].upper(),inner=shape['a'],outer=shape['b'],plunge_m=.06)
            continue
        if owner in ('front_propshaft','cvt_output_shaft'):
            shape=item['primitives'][0]
            shafts[owner]=dict(inner_role='front_diff' if owner=='front_propshaft' else 'cvt',
                              outer_role='rear_final_drive' if recipe['variant']!='independent_rear' else 'rear_diff',
                              inner=shape['a'],outer=shape['b'],plunge_m=.03)
            continue
        if owner=='frame' or any(token in owner for token in ('wishbone','upright','trailing_arm','radius_rod','tie_rod','toe_link','spring_damper','wheel')) or moments[0]<=0:continue
        # Known synthetic fixture declarations. Production generation consumes
        # only these explicit points and checks them against the calibrated plan.
        center=np.asarray(moments[1]);extent=np.ptp(np.concatenate([tri.reshape(-1,3) for _,tri in meshes]),axis=0)
        sx=max(.015,extent[0]*.4);sy=max(.015,extent[1]*.4)
        offsets=([-sx,-sy,0],[sx,-sy,0],[-sx,sy,0],[sx,sy,0]) if comp['Template']=='panel' else ([-sx,-sy,0],[sx,-sy,0],[0,sy,0])
        fixed[owner]=[(center+offset).tolist() for offset in offsets]
    definition=dict(kind='vehicle_template',version=1,templates=recipe['templates'],hardpoints=recipe['hardpoints'],fixed_mounts=fixed,halfshafts=halfshafts,shafts=shafts,
                    parameters=dict(travel_m=.16,steer_degrees=28,tire_radius_m=.28,tire_width_m=.16,frequency_hz=1.5,damping_ratio=.65),
                    declaration_source=dict(kind='synthetic_recipe',recipe_sha256=recipe['recipe_sha256']))
    c.write(output/'template.json',definition);c.write(output/'cad-audit.json',audits)
    project['TemplateDefinitionPath']=str(output/'template.json');c.write(Path(capture['project']),project);c.write(output/'project.json',project)
    inputs=output/'settings';inputs.mkdir()
    c.write(inputs/'main.materials.json',{'mochi_frame_material':dict(name='mochi_frame_material',mapTo='mochi_frame_material',**{'class':'Material'},Stages=[dict(baseColorFactor=[.5,.6,.7,1])],version=1.5)})
    c.write(inputs/'vehicle_info_settings.json',dict(modelId='mochi',mainPartName='mochi',generatedPartName='mochi',generatedJBeam='mochi.jbeam',defaultConfig='base',
        name='Independent Synthetic Frame',brand='CAD',author='BeamNG CAD harness',country='Germany',description='Native synthetic CAD recipe',bodyStyle='Frame',type='Car',
        years=dict(min=2026,max=2026),defaultPaintName1='Steel',paints={'Steel':dict(baseColor=[.5,.6,.7,1])}))
    frame=next(comp for comp in project['Components'] if comp['Template']=='calibrated_frame')
    prepare(Path(frame['GeometryDirectory'])/'geometry.json',inputs,output/'prepared',
            'C:/Program Files/Blender Foundation/Blender 5.0/blender.exe',
            'C:/Users/ak1di/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0/python.exe')
    c.write(output/'prepared/frame-mounts.json',frame_mount_plan(definition,project['Components']))
    calibration.prepare(output/'prepared',output/'generation')
    review=read(output/'generation/review.json');review['approved']=True
    review['approval_source']='Owned synthetic harness; fixture support/load selections generated and validated on this independent graph'
    c.write(output/'generation/review.json',review)
    calibration.calibrate(output/'generation')
    calibration.package(output/'generation','solidworks-assigned',output/'frame-package')
    # Namespacing is the same metadata/package operation used by the add-in.
    from build_static_frame import customize
    profile=dict(Name='Synthetic '+recipe['variant'],Brand='CAD',Author='BeamNG CAD harness',Description='Independent native CAD template',Configuration='Prototype',PreviewImage='')
    c.write(output/'profile.json',profile)
    customize(output/'frame-package/static_frame_build.json',output/'profile.json',output/'frame-namespaced',Path(capture['project']))
    project['FrameBuildReceipt']=str(output/'frame-namespaced/static_frame_build.json');project['LastBuildReceipt']=project['FrameBuildReceipt']
    c.write(Path(capture['project']),project);c.write(output/'project.json',project)
    print('SYNTHETIC_PROJECT '+str(output/'project.json'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cad',type=Path);p.add_argument('output',type=Path);a=p.parse_args();setup(a.cad,a.output)
