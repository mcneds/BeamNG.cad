from __future__ import annotations
import numpy as np
from PySide6.QtCore import Qt,Signal,QTimer,QRect
from PySide6.QtWidgets import QWidget,QVBoxLayout,QRubberBand
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtk.util.numpy_support import numpy_to_vtk,numpy_to_vtkIdTypeArray
from .project import transform


class Viewport(QWidget):
    selected=Signal(list);picked=Signal(object,object);manipulated=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.widget=QVTKRenderWindowInteractor(self);layout.addWidget(self.widget)
        self.renderer=vtk.vtkRenderer();self.renderer.SetBackground(.77,.77,.75)
        self.widget.GetRenderWindow().AddRenderer(self.renderer)
        self.widget.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera());self.widget.Initialize()
        self.actors={};self.ids={};self.objects={};self.selected_ids=set();self.project=None;self.box_mode=False
        self.point_mode=False;self.vertex_snap=False;self.explode=0.;self.overlays=[];self.press=None;self.preview_transforms={}
        self.widget.installEventFilter(self);self.rubber=QRubberBand(QRubberBand.Rectangle,self.widget)
        self.box=vtk.vtkBoxWidget2();self.box.SetInteractor(self.widget)
        self.boxrep=vtk.vtkBoxRepresentation();self.box.SetRepresentation(self.boxrep)
        self.box.AddObserver('EndInteractionEvent',self._manipulated)
        self.axes=vtk.vtkOrientationMarkerWidget();axes=vtk.vtkAxesActor();self.axes.SetOrientationMarker(axes)
        self.axes.SetInteractor(self.widget);self.axes.SetViewport(0,0,.15,.2);self.axes.SetEnabled(1);self.axes.InteractiveOff()

    def eventFilter(self,obj,event):
        from PySide6.QtCore import QEvent
        if event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
            self.press=event.position().toPoint()
            if self.box_mode:self.rubber.setGeometry(QRect(self.press,self.press));self.rubber.show();return True
        if event.type()==QEvent.MouseMove and self.box_mode and self.press:
            self.rubber.setGeometry(QRect(self.press,event.position().toPoint()).normalized());return True
        if event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and self.press:
            end=event.position().toPoint();start=self.press;self.press=None
            modifier=bool(event.modifiers()&(Qt.ControlModifier|Qt.ShiftModifier))
            if self.box_mode:
                self.rubber.hide();self._box_select(QRect(start,end).normalized(),modifier);return True
            if (end-start).manhattanLength()<5:self._pick(end,modifier)
        return super().eventFilter(obj,event)

    def load(self,project,meshes):
        if hasattr(self,'timer'):self.timer.stop()
        self.project=project;self.renderer.RemoveAllViewProps();self.actors.clear();self.ids.clear();self.objects.clear();self.overlays=[]
        self.box.Off();self.selected_ids=set();self.queue=list(meshes);self.total=len(self.queue)
        self.timer=QTimer(self);self.timer.timeout.connect(self._load_chunk);self.timer.start(1)

    def _load_chunk(self):
        for _ in range(min(40,len(self.queue))):
            obj,vertices,faces=self.queue.pop(0);points=vtk.vtkPoints();points.SetData(numpy_to_vtk(vertices,deep=True))
            cells=vtk.vtkCellArray();cells.SetCells(len(faces),numpy_to_vtkIdTypeArray(np.column_stack([np.full(len(faces),3),faces]).astype(np.int64).ravel(),deep=True))
            poly=vtk.vtkPolyData();poly.SetPoints(points);poly.SetPolys(cells)
            mapper=vtk.vtkPolyDataMapper();mapper.SetInputData(poly);mapper.ScalarVisibilityOff()
            actor=vtk.vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(*obj.get('color',[.62,.64,.67])[:3])
            self.renderer.AddActor(actor);self.actors[obj['id']]=actor;self.ids[actor.GetAddressAsString('')]=obj['id'];self.objects[obj['id']]=obj
        if not self.queue:
            self.timer.stop();self.refresh();self.fit();self.skeleton()

    def refresh(self):
        if not self.project:return
        view=self.project.data['view'];hidden=set(view.get('hidden',[]));locked=set(view.get('locked',[]))
        transparent=set(view.get('transparent',[]))
        owners=self.project.owners();orientation=np.asarray(self.project.data['orientation'])
        for key,actor in self.actors.items():
            owner=owners.get(key);mat=orientation@np.asarray(self.project.data['components'][owner]['transform']) if owner else orientation.copy()
            mat=mat@np.asarray(self.project.data.get('mesh_transforms',{}).get(key,np.eye(4)))
            if owner in self.preview_transforms:mat=self.preview_transforms[owner]@mat
            if self.explode:
                bounds=self.objects[key]['bounds'];center=(np.array(bounds[0])+bounds[1])/2;mat[:3,3]+=center*self.explode
            vm=vtk.vtkMatrix4x4()
            for i in range(4):
                for j in range(4):vm.SetElement(i,j,mat[i,j])
            actor.SetUserMatrix(vm);actor.SetVisibility(key not in hidden);actor.SetPickable(key not in locked)
            actor.GetProperty().SetOpacity(.2 if key in transparent else 1)
            actor.GetProperty().SetColor(*([.92,.57,.08] if key in self.selected_ids else self.objects[key].get('color',[.62,.64,.67])[:3]))
        self.render()

    def select(self,ids,notify=False):
        self.selected_ids=set(ids);self.refresh()
        if notify:self.selected.emit(sorted(self.selected_ids))

    def _pick(self,point,append):
        scale=self.widget.devicePixelRatioF();x=int(point.x()*scale);y=int((self.widget.height()-point.y())*scale)
        picker=vtk.vtkCellPicker();picker.SetTolerance(.0005);picker.Pick(x,y,0,self.renderer)
        actor=picker.GetActor();key=self.ids.get(actor.GetAddressAsString('')) if actor else None
        if self.point_mode and key:
            if self.explode or self.preview_transforms:return
            pos=np.array(picker.GetPickPosition())
            if self.vertex_snap:
                cell=actor.GetMapper().GetInput().GetCell(picker.GetCellId())
                pts=np.array([cell.GetPoints().GetPoint(i) for i in range(cell.GetNumberOfPoints())]);pts=transform(pts,self.project.object_transform(key))
                pos=pts[np.argmin(np.linalg.norm(pts-pos,axis=1))]
            self.picked.emit(pos.tolist(),key);return
        selected=self.selected_ids.copy() if append else set()
        if key:
            if append and key in selected:selected.remove(key)
            else:selected.add(key)
        self.select(selected,True)

    def _box_select(self,rect,append):
        selector=vtk.vtkHardwareSelector();selector.SetRenderer(self.renderer);selector.SetFieldAssociation(vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS)
        s=self.widget.devicePixelRatioF();h=self.widget.height()
        selector.SetArea(int(rect.left()*s),int((h-rect.bottom())*s),int(rect.right()*s),int((h-rect.top())*s))
        selection=selector.Select();ids=self.selected_ids.copy() if append else set()
        if selection:
            for i in range(selection.GetNumberOfNodes()):
                node=selection.GetNode(i);actor=node.GetProperties().Get(vtk.vtkSelectionNode.PROP());key=self.ids.get(actor.GetAddressAsString('')) if actor else None
                if key and actor.GetPickable():ids.add(key)
        self.select(ids,True)

    def gizmo(self,enabled):
        self.box.Off()
        actors=[self.actors[k] for k in self.selected_ids if k in self.actors]
        if enabled and actors:
            bounds=np.array([a.GetBounds() for a in actors]);minimum=bounds[:,::2].min(axis=0);maximum=bounds[:,1::2].max(axis=0)
            self.boxrep.PlaceWidget(np.column_stack([minimum,maximum]).ravel());self.box.On()
        self.render()

    def _manipulated(self,*args):
        t=vtk.vtkTransform();self.boxrep.GetTransform(t);m=t.GetMatrix()
        value=np.array([[m.GetElement(i,j) for j in range(4)] for i in range(4)])
        # Box handles can scale. Only rigid placement is accepted by the project.
        u,_,v=np.linalg.svd(value[:3,:3]);value[:3,:3]=u@v
        self.manipulated.emit(value.tolist());self.box.Off()

    def skeleton(self,poses=None):
        for actor in self.overlays:self.renderer.RemoveActor(actor)
        self.overlays=[]
        if not self.project:return
        from .build import expanded
        import json
        from pathlib import Path
        frame=Path(self.project.data['frame'])
        if frame.exists():
            part=next(iter(json.loads(frame.read_text()).values()));nodes={r[0]:r[1:4] for r,_ in expanded(part['nodes'])}
            points=vtk.vtkPoints();lines=vtk.vtkCellArray()
            for row,_ in expanded(part['beams']):
                start=points.InsertNextPoint(nodes[row[0]]);end=points.InsertNextPoint(nodes[row[1]])
                lines.InsertNextCell(2);lines.InsertCellPoint(start);lines.InsertCellPoint(end)
            poly=vtk.vtkPolyData();poly.SetPoints(points);poly.SetLines(lines);mapper=vtk.vtkPolyDataMapper();mapper.SetInputData(poly)
            actor=vtk.vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.08,.22,.5);actor.PickableOff();self.renderer.AddActor(actor);self.overlays.append(actor)
        points={name:self.project.point(name) for name in self.project.data['points']}
        if poses:
            for corner,pose in poses.items():
                for role,pos in pose.items():
                    name=self.project.data['corners'][corner]['points'].get(role)
                    if name:points[name]=pos
        for name,pos in points.items():
            sphere=vtk.vtkSphereSource();sphere.SetRadius(.009);sphere.SetCenter(*pos);sphere.SetThetaResolution(10);sphere.SetPhiResolution(8)
            mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(sphere.GetOutputPort());actor=vtk.vtkActor();actor.SetMapper(mapper)
            actor.GetProperty().SetColor(.7,.05,.08);actor.PickableOff();self.renderer.AddActor(actor);self.overlays.append(actor)
        self.render()

    def fit(self):
        camera=self.renderer.GetActiveCamera();camera.SetPosition(3,-4,2);camera.SetFocalPoint(0,1,.4);camera.SetViewUp(0,0,1)
        self.renderer.ResetCamera();self.render()
    def view(self,axis):
        camera=self.renderer.GetActiveCamera();f=np.array(camera.GetFocalPoint());distance=camera.GetDistance()
        direction={'front':(0,-1,0),'side':(1,0,0),'top':(0,0,1),'iso':(1,-1,.7)}[axis]
        camera.SetPosition(*(f+np.array(direction)*distance));camera.SetViewUp(0,1,0) if axis=='top' else camera.SetViewUp(0,0,1)
        camera.ParallelProjectionOn();self.renderer.ResetCamera();self.render()
    def render(self):self.widget.GetRenderWindow().Render()
