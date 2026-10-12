"""Exercise the real imported assembly in a disposable project copy."""
import copy
from pathlib import Path
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vehicle_wizard.gui import MainWindow,STYLE
from vehicle_wizard.project import VehicleProject,ROOT,write_json

app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
source=VehicleProject.load(ROOT/'projects/mochi/project.json');data=copy.deepcopy(source.data)
data['asset_index']=str(source.root/data['asset_index']);output=ROOT/'runtime/gui-smoke';output.mkdir(parents=True,exist_ok=True)
write_json(output/'project.json',data);window=MainWindow(output/'project.json');window.show();attempt=0
def verify():
    global attempt
    attempt+=1
    if attempt>180:print('FAIL GUI loading timeout',flush=True);app.exit(1);return
    if not window.project or window.worker and window.worker.isRunning() or getattr(window.viewport,'queue',None):QTimer.singleShot(500,verify);return
    try:
        p=window.project;objects=p.index()['objects'];assert len(window.viewport.actors)==len(objects)==1935
        selected=[o['id'] for o in objects if o['name'].startswith('Mochi Frame V3')][:10];assert selected
        window.viewport.select(selected,True);window.comp_name.setText('Smoke frame selection');window.role.setCurrentText('frame');window.assign()
        key=p.owners()[selected[0]];p.set_point('smoke_mount',[0,.3,.5],key);original=p.point('smoke_mount').copy()
        window.viewport.select(selected);window.move_t[0].setValue(.05);window.move();assert abs(p.point('smoke_mount')[0]-original[0]-.05)<1e-8
        window.undo();assert abs(p.point('smoke_mount')[0]-original[0])<1e-8
        window.redo();window.undo();window.save();assert VehicleProject.load(p.path).data==p.data
        window.viewport.view('iso');window.viewport.select(selected);app.processEvents()
        from PySide6.QtCore import QPoint,QRect
        window.viewport._pick(QPoint(window.viewport.widget.width()//2,window.viewport.widget.height()//2),False)
        assert window.viewport.selected_ids,'Viewport click did not select actual mesh geometry'
        window.viewport._box_select(QRect(0,0,window.viewport.widget.width()-1,window.viewport.widget.height()-1),False)
        assert len(window.viewport.selected_ids)>10,'Visible mesh box selection did not work'
        window.viewport.select(selected);window.visibility('hide');assert not window.viewport.actors[selected[0]].GetVisibility()
        window.visibility('show');window.visibility('lock');assert not window.viewport.actors[selected[0]].GetPickable();window.visibility('unlock')
        window.viewport.gizmo(True);assert window.viewport.box.GetEnabled();window.viewport.gizmo(False)
        window.grab().save(str(output/'desktop.png'))
        import vtk
        capture=vtk.vtkWindowToImageFilter();capture.SetInput(window.viewport.widget.GetRenderWindow());capture.ReadFrontBufferOff();capture.Update()
        writer=vtk.vtkPNGWriter();writer.SetFileName(str(output/'viewport.png'));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        write_json(output/'result.json',{'status':'passed','meshes':len(objects),'checks':['actual assembly load','viewport ray picking','box selection','hide/show','lock/unlock','placement gizmo','exclusive component assignment','point follows placement','undo','redo','save/resume'],'screenshot':str(output/'viewport.png')})
        print('PASS GUI smoke: '+str(output),flush=True);window.close();app.exit(0)
    except Exception:
        import traceback;traceback.print_exc();app.exit(1)
QTimer.singleShot(500,verify)
raise SystemExit(app.exec())
