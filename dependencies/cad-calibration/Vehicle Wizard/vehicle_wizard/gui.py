from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import sys
import threading
import traceback
import numpy as np
from PySide6.QtCore import Qt,Signal,QThread,QTimer
from PySide6.QtGui import QAction,QKeySequence,QPainter,QPen
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QSplitter,
    QTreeWidget,QTreeWidgetItem,QLineEdit,QComboBox,QDoubleSpinBox,QPushButton,QLabel,QTabWidget,QPlainTextEdit,
    QFileDialog,QMessageBox,QInputDialog,QCheckBox,QGroupBox,QScrollArea,QTableWidget,QTableWidgetItem,QSlider)
from .project import VehicleProject,ROOT,ROLES,CORNERS,FRONT_POINTS,REAR_POINTS,matrix,transform,circle_center,write_json
from .assembly import import_assembly,mesh_arrays,Cancelled
from .kinematics import Mechanism
from .build import build_vehicle,install_build
from .viewport import Viewport


STYLE='''QWidget { font-family: "Segoe UI"; font-size: 12px; color: #202020; background: #d6d6d2; }
QMainWindow, QDialog, QTabWidget::pane { background: #d6d6d2; }
QPushButton { background: #dededa; border: 1px solid #777; padding: 4px 9px; border-radius: 0px; }
QPushButton:pressed { background: #b4b4b0; } QPushButton:disabled { color: #888; }
QLineEdit, QComboBox, QDoubleSpinBox, QTreeWidget, QTableWidget, QPlainTextEdit { background: #f3f3ef; border: 1px solid #888; }
QTabBar::tab { background: #c4c4c0; border: 1px solid #888; padding: 6px; }
QTabBar::tab:selected { background: #e6e6e1; } QGroupBox { border: 1px solid #999; margin-top: 10px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 7px; } QHeaderView::section { background: #cececa; padding: 4px; border: 1px solid #999; }
QToolBar { background: #c8c8c4; spacing: 4px; border-bottom: 1px solid #777; }'''


class Worker(QThread):
    progress=Signal(str);done=Signal(object);failed=Signal(str)
    def __init__(self,fn):super().__init__();self.fn=fn;self.cancel=threading.Event()
    def run(self):
        try:self.done.emit(self.fn(self.progress.emit,self.cancel))
        except Exception as exc:self.failed.emit(str(exc)+'\n'+traceback.format_exc())


class Guide(QWidget):
    """Animated, code-native instruction drawing; no decorative icon assets."""
    def __init__(self):
        super().__init__();self.setMinimumHeight(120);self.phase=0.;self.rear=False;self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(70)
    def tick(self):self.phase+=.09;self.update()
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),Qt.lightGray);painter.setPen(QPen(Qt.darkGray,2))
        y=62+int(math.sin(self.phase)*15);x=min(self.width()-60,190)
        painter.drawLine(25,20,25,85)
        if self.rear:
            painter.setPen(QPen(Qt.darkGray,5));painter.drawLine(25,65,x,y+10);painter.setPen(QPen(Qt.darkGray,2))
            painter.drawLine(65,25,x,y-15);painter.drawLine(65,80,x,y+3)
        else:painter.drawLine(25,35,x,y-20);painter.drawLine(25,75,x,y+10)
        painter.drawLine(x,y-20,x,y+10);painter.drawLine(25,20,int(x*.75),y+10)
        painter.drawEllipse(x-7,y-11,25,25);painter.setPen(Qt.black)
        painter.drawText(8,103,'Rear: trailing arm + locating links' if self.rear else 'Front: upper / lower wishbones')
        painter.drawText(8,117,'Direct shock to '+('trailing arm.' if self.rear else 'lower arm.'))


def button(text,fn,layout):
    b=QPushButton(text);b.clicked.connect(fn);layout.addWidget(b);return b


def number(value=0,minimum=-100000,maximum=100000,decimals=4):
    w=QDoubleSpinBox();w.setRange(minimum,maximum);w.setDecimals(decimals);w.setValue(value);w.setSingleStep(.01);return w


def vector_row(label,layout,value=(0,0,0)):
    row=QHBoxLayout();row.addWidget(QLabel(label));widgets=[number(v) for v in value]
    for axis,w in zip('XYZ',widgets):w.setMinimumWidth(55);w.setMaximumWidth(84);row.addWidget(QLabel(axis));row.addWidget(w)
    layout.addLayout(row);return widgets


class MainWindow(QMainWindow):
    def __init__(self,path=None):
        super().__init__();self.project=None;self.worker=None;self.picked_points=[];self.loading_tree=False;self.pending_load=None
        self.setWindowTitle('BeamNG CAD - Guided Vehicle Setup');self.resize(1560,970)
        self.viewport=Viewport();self.viewport.selected.connect(self.from_viewport);self.viewport.picked.connect(self.point_picked);self.viewport.manipulated.connect(self.gizmo_moved)
        toolbar=self.addToolBar('Project');toolbar.setMovable(False)
        for title,slot,key in [('New',self.new_project,'Ctrl+N'),('Open',self.open_project,'Ctrl+O'),('Save',self.save,'Ctrl+S'),('Undo',self.undo,'Ctrl+Z'),('Redo',self.redo,'Ctrl+Y'),('Checkpoint',self.checkpoint,None)]:
            action=QAction(title,self);action.triggered.connect(self.safe(slot));toolbar.addAction(action)
            if key:action.setShortcut(QKeySequence(key))
        self.title=QLabel('Open a guided vehicle project');toolbar.addWidget(self.title)
        central=QWidget();outer=QVBoxLayout(central);outer.setContentsMargins(5,5,5,5);self.setCentralWidget(central)
        self.split=QSplitter();outer.addWidget(self.split,1)
        left=QWidget();self.left_panel=left;lv=QVBoxLayout(left);lv.setContentsMargins(0,0,0,0);self.search=QLineEdit();self.search.setPlaceholderText('Filter meshes / collections / components');self.search.textChanged.connect(self.filter_tree);lv.addWidget(self.search)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['Assembly / components','Role']);self.tree.setSelectionMode(QTreeWidget.ExtendedSelection);self.tree.itemSelectionChanged.connect(self.from_tree);lv.addWidget(self.tree)
        self.tree.setColumnWidth(0,240)
        row=QHBoxLayout();lv.addLayout(row)
        for title,fn in [('Hide',lambda:self.visibility('hide')),('Isolate',lambda:self.visibility('isolate')),('Show all',lambda:self.visibility('show'))]:button(title,self.safe(fn),row)
        row=QHBoxLayout();lv.addLayout(row)
        for title,fn in [('Transparent',lambda:self.visibility('transparent')),('Lock',lambda:self.visibility('lock')),('Unlock all',lambda:self.visibility('unlock'))]:button(title,self.safe(fn),row)
        row=QHBoxLayout();lv.addLayout(row);button('Save selection group',self.safe(self.save_group),row);button('Unassign',self.safe(self.unassign),row)
        self.split.addWidget(left)
        middle=QWidget();mv=QVBoxLayout(middle);mv.setContentsMargins(0,0,0,0);row=QHBoxLayout();mv.addLayout(row)
        for name in ('front','side','top','iso'):button(name.title(),lambda checked=False,n=name:self.viewport.view(n),row)
        button('Fit',self.viewport.fit,row);self.box_select=QCheckBox('Box select');self.box_select.toggled.connect(lambda x:setattr(self.viewport,'box_mode',x));row.addWidget(self.box_select)
        self.gizmo=QCheckBox('Move / rotate handles');self.gizmo.toggled.connect(self.viewport.gizmo);row.addWidget(self.gizmo)
        mv.addWidget(self.viewport,1);self.selection_label=QLabel('Click: select | Ctrl / Shift: multiple | Drag: orbit | Wheel: zoom');mv.addWidget(self.selection_label)
        row=QHBoxLayout();mv.addLayout(row);row.addWidget(QLabel('Exploded inspection (display only)'));self.exploded=QSlider(Qt.Horizontal);self.exploded.setRange(0,100);self.exploded.valueChanged.connect(self.explode);row.addWidget(self.exploded)
        self.split.addWidget(middle)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(430);self.split.addWidget(self.tabs);self.split.setSizes([310,790,460])
        self.setup_tab();self.components_tab();self.suspension_tab();self.powertrain_tab();self.test_tab()
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(115);outer.addWidget(self.log)
        row=QHBoxLayout();outer.addLayout(row);self.state=QLabel('Ready');row.addWidget(self.state,1);self.cancel_button=button('Cancel operation',self.cancel,row);self.cancel_button.setEnabled(False)
        if path:QTimer.singleShot(0,lambda:self.safe(lambda:self.load_project(path))())

    def safe(self,fn):
        def call(*args):
            try:return fn()
            except Exception as exc:self.log.appendPlainText(str(exc));QMessageBox.warning(self,'Cannot complete operation',str(exc))
        return call

    def tab(self,title,text):
        scroll=QScrollArea();scroll.setWidgetResizable(True);panel=QWidget();layout=QVBoxLayout(panel);label=QLabel(text);label.setWordWrap(True);layout.addWidget(label)
        scroll.setWidget(panel);self.tabs.addTab(scroll,title);return layout

    def setup_tab(self):
        layout=self.tab('1. Intake','AUTOMATED IMPORT / GUIDED ALIGNMENT\nOpen the cleaned Blender assembly. Source files remain unchanged. Blue lines show the generated chassis. BeamNG coordinates: +X left, -Y forward, +Z up; all distances are metres.')
        self.source=QLineEdit();self.blender=QLineEdit();self.frame=QLineEdit()
        for label,field,filter_ in [('Assembly',self.source,'Blender (*.blend)'),('Blender executable',self.blender,'Executable (*.exe)'),('Chassis JBeam',self.frame,'JBeam (*.jbeam)')]:
            layout.addWidget(QLabel(label));row=QHBoxLayout();row.addWidget(field);layout.addLayout(row)
            button('Browse',lambda checked=False,f=field,pat=filter_:self.browse(f,pat),row)
        button('Import / reimport assembly',self.safe(self.import_source),layout)
        self.orient_t=vector_row('Translate (m)',layout);self.orient_r=vector_row('Rotate (deg)',layout)
        button('Apply assembly alignment',self.safe(self.align),layout)
        self.alignment=QCheckBox('I checked units, forward direction and frame alignment');self.alignment.clicked.connect(self.safe(self.confirm_alignment));layout.addWidget(self.alignment)
        self.import_info=QLabel('');self.import_info.setWordWrap(True);layout.addWidget(self.import_info);layout.addWidget(Guide());layout.addStretch()

    def components_tab(self):
        layout=self.tab('2. Parts','GUIDED COMPONENTS\nSelect any meshes in the tree or viewer. Physical component ownership is exclusive. Selection groups may overlap. Assign unused CAD bodies to Ignore before building.')
        form=QFormLayout();layout.addLayout(form);self.comp_name=QLineEdit();self.role=QComboBox();self.role.addItems(ROLES);self.corner=QComboBox();self.corner.addItems(['',*CORNERS]);self.mass=number(1,0,10000)
        for label,field in [('Component name',self.comp_name),('Physical role',self.role),('Corner',self.corner),('Mass (kg, assumed)',self.mass)]:form.addRow(label,field)
        button('Assign selection to component',self.safe(self.assign),layout)
        self.component_picker=QComboBox();form.addRow('Edit component',self.component_picker);self.component_picker.currentIndexChanged.connect(self.component_changed)
        button('Update component name / mass / role',self.safe(self.update_component),layout)
        self.link_group=QLineEdit();self.link_group.setPlaceholderText('RL_link_0, RL_link_1, ...');form.addRow('Locating-link group',self.link_group)
        self.move_t=vector_row('Move (m)',layout);self.move_r=vector_row('Rotate (deg)',layout);self.pivot=vector_row('Pivot (m)',layout)
        self.local=QCheckBox('Use component local axes');layout.addWidget(self.local)
        button('Apply placement to selected components',self.safe(self.move),layout)
        row=QHBoxLayout();layout.addLayout(row);button('Pivot from last pick',self.safe(self.pivot_pick),row);button('Snap pivot to last pick',self.safe(self.snap),row)
        layout.addWidget(QLabel('Attached mounting points move with their component.\nUse Undo to revert placement or assignment.'));layout.addStretch()

    def suspension_tab(self):
        layout=self.tab('3. Suspension','GUIDED HARDPOINTS\nFront: double wishbone, direct coilover on LOWER arm.\nRear: trailing arm with separate locating links; direct coilover on trailing arm. Pick joint centers, not arbitrary mesh surfaces. Mirrored points require separate review.')
        form=QFormLayout();layout.addLayout(form);self.point_corner=QComboBox();self.point_corner.addItems(CORNERS);self.point_corner.currentIndexChanged.connect(self.point_roles)
        self.point_role=QComboBox();self.point_role.currentTextChanged.connect(self.role_selected);form.addRow('Corner',self.point_corner);form.addRow('Hardpoint',self.point_role)
        self.point_help=QLabel('');self.point_help.setWordWrap(True);layout.addWidget(self.point_help)
        self.point_name=QLineEdit();form.addRow('Point name',self.point_name)
        self.point_method=QComboBox();self.point_method.addItems(['Surface','Vertex','Midpoint (2 picks)','Circle center (3 picks)']);form.addRow('Pick method',self.point_method)
        self.point_method.currentTextChanged.connect(lambda value:setattr(self.viewport,'vertex_snap',value=='Vertex'))
        self.pick=QCheckBox('Pick hardpoints in viewport');self.pick.toggled.connect(self.pick_mode);layout.addWidget(self.pick)
        self.attach=QCheckBox('Attach point to picked component');self.attach.setChecked(True);layout.addWidget(self.attach)
        self.xyz=vector_row('Point (m)',layout);button('Save / bind numeric point',self.safe(self.save_point),layout)
        self.point_list=QComboBox();form.addRow('Saved points',self.point_list);button('Load selected point',self.safe(self.load_point),layout)
        layout.addWidget(QLabel('Rear locating links: save two points, then link them.'))
        self.link_inner=QComboBox();self.link_outer=QComboBox();form.addRow('Chassis end',self.link_inner);form.addRow('Arm end',self.link_outer)
        button('Add locating link',self.safe(self.add_link),layout);button('Remove last locating link',self.safe(self.remove_link),layout)
        row=QHBoxLayout();layout.addLayout(row);button('Mirror to opposite side',self.safe(self.mirror),row);button('Check travel / steering',self.safe(self.check_kinematics),row)
        self.travel=QSlider(Qt.Horizontal);self.travel.setRange(-100,100);self.travel.valueChanged.connect(self.preview_travel);layout.addWidget(QLabel('Analytical travel preview'));layout.addWidget(self.travel)
        self.geometry_confirm=QCheckBox('Geometry and coilover attachment reviewed');self.geometry_confirm.clicked.connect(self.safe(self.confirm_geometry));layout.addWidget(self.geometry_confirm)
        self.kinematics_info=QLabel('');self.kinematics_info.setWordWrap(True);layout.addWidget(self.kinematics_info);self.suspension_guide=Guide();layout.addWidget(self.suspension_guide);layout.addStretch();self.point_roles()

    def powertrain_tab(self):
        layout=self.tab('4. Powertrain','GUIDED HARDWARE\nRear engine with mounted CVT, rear differential and disconnectable front drive. Open axle differentials are starter assumptions. Enter hardware data here; assumptions remain recorded in the project.')
        self.engine_model=QLineEdit();self.cvt_model=QLineEdit();form=QFormLayout();form.addRow('Engine model',self.engine_model);form.addRow('CVT model',self.cvt_model);layout.addLayout(form)
        layout.addWidget(QLabel('Place these named points in Suspension / numeric entry:\nengine_center, cvt_center, engine_mount_1, engine_mount_2, engine_mount_3. Choose Custom / powertrain point.'))
        self.params=QTableWidget(0,3);self.params.setHorizontalHeaderLabels(['Parameter / units','Value','Source / assumption']);self.params.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.params)
        button('Save hardware and parameters',self.safe(self.save_parameters),layout)
        self.assumptions=QCheckBox('I reviewed the provisional hardware values');self.assumptions.clicked.connect(self.safe(self.confirm_assumptions));layout.addWidget(self.assumptions)
        label=QLabel('Default: 10 kW at 3600 rpm; CVT 0.8–3.0; final drive 8:1.\nSpring target: 1.5 Hz, damping ratio 0.6.\nMaterial condition and real rupture remain unvalidated.');label.setWordWrap(True);layout.addWidget(label)

    def test_tab(self):
        layout=self.tab('5. Build / test','AUTOMATED BUILD AND TEST\nValidation lists unresolved guided inputs. A build is reproducible from its project snapshot and source hashes. Native Lua automation uses the isolated harness profile; BeamNGpy is not required.')
        row=QHBoxLayout();layout.addLayout(row);button('Validate setup',self.safe(self.validate),row);button('Generate vehicle',self.safe(self.build),row)
        self.scenario=QComboBox();self.scenario.addItems(['settle','supported','articulation','acceleration','braking','reverse','left_turn','right_turn','acceptance']);layout.addWidget(self.scenario)
        button('Run test / acceptance series',self.safe(self.run_test),layout)
        self.results=QPlainTextEdit();self.results.setReadOnly(True);layout.addWidget(self.results)
        row=QHBoxLayout();layout.addLayout(row);button('Open build folder',self.safe(self.open_build),row);button('Open latest test',self.safe(self.open_test),row)
        self.mods=QLineEdit(str(Path(os.environ.get('LOCALAPPDATA',''))/'BeamNG/BeamNG.drive/current/mods'));layout.addWidget(QLabel('Normal game profile mods folder'));layout.addWidget(self.mods)
        button('Install named prototype mod',self.safe(self.install),layout)
        button('Launch normal game for driving',self.safe(self.launch_game),layout)
        layout.addWidget(QLabel('Vehicle selector: Mochi First Drive - Prototype\nTest results distinguish measured passes, failures and unavailable checks.'));layout.addStretch()

    def require(self):
        if not self.project:raise ValueError('Create or open a project first')
        return self.project
    def browse(self,field,filter_):
        path,_=QFileDialog.getOpenFileName(self,'Select file',field.text(),filter_)
        if path:field.setText(path)
    def new_project(self):
        path,_=QFileDialog.getSaveFileName(self,'New project',str(ROOT/'projects/new_vehicle/project.json'),'Project (*.json)')
        if path:self.project=VehicleProject.create(path);self.refresh()
    def open_project(self):
        path,_=QFileDialog.getOpenFileName(self,'Open project',str(ROOT/'projects'),'Project (*.json)')
        if path:self.load_project(path)
    def load_project(self,path):self.project=VehicleProject.load(path);self.refresh();self.load_meshes()
    def save(self):self.require().save();self.state.setText('Project saved')
    def undo(self):self.require().undo();self.refresh();self.viewport.refresh();self.viewport.skeleton()
    def redo(self):self.require().redo();self.refresh();self.viewport.refresh();self.viewport.skeleton()
    def checkpoint(self):
        p=self.require();name,ok=QInputDialog.getText(self,'Checkpoint','Checkpoint name')
        if ok and name:
            import re
            name=re.sub(r'[^a-zA-Z0-9_-]','_',name);snapshot=copy.deepcopy(p.data)
            if snapshot['asset_index']:snapshot['asset_index']=str((p.root/snapshot['asset_index']).resolve())
            snapshot['last_build']=None;snapshot['last_test']=None
            write_json(p.root/'checkpoints'/(name+'.json'),snapshot);self.state.setText('Checkpoint saved; use Open to resume it')

    def refresh(self):
        p=self.require();self.title.setText(str(p.path));self.source.setText(p.data['assembly']);self.blender.setText(p.data['blender']);self.frame.setText(p.data['frame'])
        self.alignment.setChecked(p.data['alignment_confirmed']);self.assumptions.setChecked(p.data['assumptions_accepted']);self.engine_model.setText(p.data.get('engine_model',''));self.cvt_model.setText(p.data.get('cvt_model',''))
        self.params.setRowCount(len(p.data['parameters']))
        for i,(key,value) in enumerate(p.data['parameters'].items()):
            for j,text in enumerate((key,str(value),p.data['parameter_sources'].get(key,'assumed'))):
                item=QTableWidgetItem(text)
                if j==0:item.setFlags(item.flags()&~Qt.ItemIsEditable)
                self.params.setItem(i,j,item)
        self.loading_tree=True;self.tree.clear();self.component_picker.blockSignals(True);self.component_picker.clear()
        self.tree_mesh_items={}
        objects={o['id']:o for o in p.index()['objects']};owners=p.owners()
        roots={name:QTreeWidgetItem(self.tree,[name]) for name in ('Components','Selection groups','Collections','Unassigned')}
        def child(parent,key):
            if key not in objects:return
            item=QTreeWidgetItem(parent,[objects[key]['name'],p.data['components'][owners[key]]['role'] if key in owners else '']);item.setData(0,Qt.UserRole,[key])
            item.setToolTip(0,objects[key]['name']+'\n'+', '.join(objects[key]['collections']))
            self.tree_mesh_items.setdefault(key,[]).append(item)
        for key,c in p.data['components'].items():
            self.component_picker.addItem(c['name'],key);item=QTreeWidgetItem(roots['Components'],[c['name'],c['role']+' '+c['corner']]);item.setData(0,Qt.UserRole,c['meshes'])
            for mesh in c['meshes']:child(item,mesh)
        for name,ids in p.data['groups'].items():
            item=QTreeWidgetItem(roots['Selection groups'],[name]);item.setData(0,Qt.UserRole,ids)
            for key in ids:child(item,key)
        collections={}
        for key,obj in objects.items():
            for collection in obj['collections']:
                if collection not in collections:collections[collection]=QTreeWidgetItem(roots['Collections'],[collection])
                child(collections[collection],key)
            if key not in owners:child(roots['Unassigned'],key)
        for item in roots.values():item.setExpanded(True)
        self.component_picker.blockSignals(False);self.loading_tree=False
        names=list(p.data['points'])
        for combo in (self.point_list,self.link_inner,self.link_outer):
            current=combo.currentText();combo.clear();combo.addItems(names);combo.setCurrentText(current)
        self.geometry_confirm.setChecked(p.data['corners'][self.point_corner.currentText()]['confirmed'])
        self.import_info.setText(f'{len(objects):,} mesh objects; {len(owners):,} assigned.\n'+str(p.path))
        self.viewport.project=p;self.viewport.refresh();self.filter_tree(self.search.text())

    def task(self,title,fn,done=None):
        if self.worker and self.worker.isRunning():raise ValueError('An operation is already running')
        self.state.setText(title);self.tabs.setEnabled(False);self.left_panel.setEnabled(False);self.viewport.setEnabled(False)
        for bar in self.findChildren(__import__('PySide6.QtWidgets',fromlist=['QToolBar']).QToolBar):bar.setEnabled(False)
        self.cancel_button.setEnabled(True);self.worker=Worker(fn);self.worker.progress.connect(self.log.appendPlainText)
        self.worker.failed.connect(lambda error:self.log.appendPlainText(error));self.worker.done.connect(done or (lambda result:self.log.appendPlainText(str(result))))
        self.worker.finished.connect(self.task_finished);self.worker.start()
    def task_finished(self):
        self.tabs.setEnabled(True);self.left_panel.setEnabled(True);self.viewport.setEnabled(True);self.cancel_button.setEnabled(False);self.state.setText('Ready - see operation log')
        for bar in self.findChildren(__import__('PySide6.QtWidgets',fromlist=['QToolBar']).QToolBar):bar.setEnabled(True)
        if self.pending_load:
            fn=self.pending_load;self.pending_load=None;QTimer.singleShot(0,fn)
    def cancel(self):
        if self.worker:self.worker.cancel.set();self.state.setText('Cancelling operation...')
    def load_meshes(self):
        p=self.require()
        if not p.data['asset_index']:return
        def load(progress,cancel):
            result=[]
            for i,obj in enumerate(p.index()['objects']):
                if cancel.is_set():raise Cancelled('Viewport loading cancelled')
                result.append((obj,*mesh_arrays(p,obj)))
                if i%200==0:progress(f'Loading viewer mesh {i+1}')
            return result
        self.task('Loading viewport...',load,lambda meshes:self.viewport.load(p,meshes))
    def import_source(self):
        p=self.require();p.checkpoint('Import settings');p.data.update(assembly=self.source.text(),blender=self.blender.text(),frame=self.frame.text());p.save()
        def complete(index):self.refresh();self.pending_load=self.load_meshes
        self.task('Importing assembly...',lambda progress,cancel:import_assembly(p,progress,cancel),complete)

    def selected(self):return sorted(self.viewport.selected_ids)
    def selected_components(self):
        p=self.require();owners=p.owners();keys=sorted({owners[k] for k in self.selected() if k in owners})
        if any(set(p.data['components'][k]['meshes'])&set(p.data['view']['locked']) for k in keys):raise ValueError('Unlock the component before changing placement')
        return keys
    def from_tree(self):
        if self.loading_tree:return
        ids=set()
        def collect(item):
            value=item.data(0,Qt.UserRole)
            if value:ids.update(value)
            else:
                for i in range(item.childCount()):collect(item.child(i))
        for item in self.tree.selectedItems():collect(item)
        self.viewport.select(ids);self.selection_label.setText(f'{len(ids)} meshes selected');self.viewport.gizmo(self.gizmo.isChecked())
    def from_viewport(self,ids):
        self.selection_label.setText(f'{len(ids)} meshes selected');self.viewport.gizmo(self.gizmo.isChecked());self.loading_tree=True;self.tree.clearSelection()
        for key in ids:
            items=getattr(self,'tree_mesh_items',{}).get(key,[])
            if items:items[0].setSelected(True)
        self.loading_tree=False
    def filter_tree(self,text):
        def filter_(item):
            children=[filter_(item.child(i)) for i in range(item.childCount())];match=text.lower() in item.text(0).lower() or any(children)
            item.setHidden(not match);return match
        for i in range(self.tree.topLevelItemCount()):filter_(self.tree.topLevelItem(i))
    def visibility(self,action):
        p=self.require();view=p.data['view'];ids=set(self.selected());all_ids={o['id'] for o in p.index()['objects']}
        if action=='show':view['hidden']=[]
        elif action=='isolate':view['hidden']=sorted(all_ids-ids)
        elif action=='hide':view['hidden']=sorted(set(view.get('hidden',[]))|ids)
        elif action=='unlock':view['locked']=[]
        else:
            key='locked' if action=='lock' else 'transparent';view[key]=sorted(set(view.get(key,[]))^ids)
        p.save();self.viewport.refresh()
    def explode(self,value):self.viewport.explode=value/100;self.viewport.refresh()
    def save_group(self):
        p=self.require();name,ok=QInputDialog.getText(self,'Selection group','Group name')
        if ok and name:p.checkpoint('Save group',physical=False);p.data['groups'][name]=self.selected();p.save();self.refresh()
    def unassign(self):
        p=self.require();p.unassign(self.selected());self.refresh()
    def assign(self):
        p=self.require();p.assign(self.comp_name.text() or self.role.currentText(),self.role.currentText(),self.selected(),self.corner.currentText(),self.mass.value());self.refresh()
    def component_changed(self):
        if not self.project:return
        key=self.component_picker.currentData();c=self.project.data['components'].get(key)
        if not c:return
        self.comp_name.setText(c['name']);self.role.setCurrentText(c['role']);self.corner.setCurrentText(c['corner']);self.mass.setValue(c['mass_kg']);self.link_group.setText(c.get('link_group',''))
        self.viewport.select(c['meshes'])
    def update_component(self):
        p=self.require();key=self.component_picker.currentData()
        if not key:raise ValueError('Select a component')
        p.checkpoint('Edit component');p.data['components'][key].update(name=self.comp_name.text(),role=self.role.currentText(),corner=self.corner.currentText(),mass_kg=self.mass.value(),link_group=self.link_group.text());p.save();self.refresh()
    def move(self):
        self.require().move(self.selected_components(),[w.value() for w in self.move_t],[w.value() for w in self.move_r],[w.value() for w in self.pivot],self.local.isChecked());self.viewport.refresh();self.viewport.skeleton()
        self.alignment.setChecked(self.project.data['alignment_confirmed']);self.geometry_confirm.setChecked(False)
    def gizmo_moved(self,value):
        def apply():
            p=self.require();keys=self.selected_components()
            if not keys:raise ValueError('Assign a component before moving it')
            p.checkpoint('Manipulate components');orientation=np.asarray(p.data['orientation']);delta=np.linalg.inv(orientation)@value@orientation
            for key in keys:p.data['components'][key]['transform']=(delta@p.data['components'][key]['transform']).tolist()
            for c in p.data['corners'].values():c['confirmed']=False
            p.save();self.viewport.refresh();self.viewport.skeleton()
        self.safe(apply)()
    def pivot_pick(self):
        if not self.picked_points:raise ValueError('Pick a point first')
        for w,value in zip(self.pivot,self.picked_points[-1][0]):w.setValue(value)
    def snap(self):
        if not self.picked_points:raise ValueError('Pick the destination first')
        delta=np.array(self.picked_points[-1][0])-np.array([w.value() for w in self.pivot]);self.require().move(self.selected_components(),delta,[0,0,0]);self.viewport.refresh();self.viewport.skeleton()
    def align(self):
        p=self.require();p.checkpoint('Align assembly');p.data['orientation']=(matrix([w.value() for w in self.orient_t],[w.value() for w in self.orient_r])@p.data['orientation']).tolist();p.data['alignment_confirmed']=False
        for c in p.data['corners'].values():c['confirmed']=False
        p.save();self.refresh();self.viewport.skeleton()
    def confirm_alignment(self):p=self.require();p.checkpoint('Confirm alignment');p.data['alignment_confirmed']=self.alignment.isChecked();p.save()

    def point_roles(self):
        if not hasattr(self,'point_role'):return
        self.point_role.clear();self.point_role.addItems([*(FRONT_POINTS if self.point_corner.currentText().startswith('F') else REAR_POINTS),'Custom / powertrain point'])
        if hasattr(self,'suspension_guide'):self.suspension_guide.rear=self.point_corner.currentText().startswith('R')
        if self.project:self.geometry_confirm.setChecked(self.project.data['corners'][self.point_corner.currentText()]['confirmed'])
    def role_selected(self,role):
        if hasattr(self,'point_name') and role and not role.startswith('Custom'):self.point_name.setText(self.point_corner.currentText()+'_'+role)
        if hasattr(self,'point_help'):
            hints={'hub':'Center of the wheel bearing. Use circle-center picking on a machined circular feature.',
                   'hub_axis':'Second point on the bearing axis, at least 10 mm from hub center. This defines wheel orientation.',
                   'shock_top':'Center of the coilover chassis bolt. Attach to the frame component.',
                   'shock_bottom':'Center of the coilover lower bolt: front LOWER wishbone, rear trailing arm.',
                   'trailing_pivot':'Center of the trailing arm chassis joint. The first rear template treats this as a spherical joint.',
                   'tie_inner':'Center of the inner steering joint. The prototype uses a variable-length tie-rod hydro.',
                   'tie_outer':'Center of the outer steering joint on the upright.'}
            text=hints.get(role,'Pick the center of this joint. Use Midpoint or Circle center for a hole axis; avoid picking the outside of the bolt.')
            if role.startswith('Custom'):text='Enter a custom name for engine/CVT points or the ends of rear locating links. These points are not automatically bound to the current corner.'
            self.point_help.setText(text)
    def pick_mode(self,on):self.viewport.point_mode=on;self.picked_points=[]
    def point_picked(self,position,mesh):
        self.safe(lambda:self._point_picked(position,mesh))()
    def _point_picked(self,position,mesh):
        self.picked_points.append((position,mesh));method=self.point_method.currentText();count=3 if method.startswith('Circle') else 2 if method.startswith('Midpoint') else 1
        self.viewport.vertex_snap=method=='Vertex'
        if len(self.picked_points)<count:self.state.setText(f'Pick {len(self.picked_points)+1} of {count}');return
        picked=self.picked_points[-count:];points=np.array([p[0] for p in picked]);point=circle_center(points) if count==3 else points.mean(axis=0)
        for w,value in zip(self.xyz,point):w.setValue(value)
        self.state.setText('Point ready; use Save / bind numeric point to accept')
    def save_point(self):
        p=self.require();name=self.point_name.text().strip()
        if not name:raise ValueError('Enter a point name')
        owner=None
        if self.attach.isChecked():owner=p.owners().get(self.picked_points[-1][1]) if self.picked_points else p.data['points'].get(name,{}).get('component')
        p.set_point(name,[w.value() for w in self.xyz],owner,'CAD pick' if self.picked_points else 'numeric entry',self.picked_points[-1][1] if self.picked_points else None)
        if not self.point_role.currentText().startswith('Custom'):p.bind_point(self.point_corner.currentText(),self.point_role.currentText(),name)
        self.picked_points=[];self.refresh();self.viewport.skeleton()
    def load_point(self):
        p=self.require();name=self.point_list.currentText();self.point_name.setText(name)
        for w,value in zip(self.xyz,p.point(name)):w.setValue(value)
    def add_link(self):
        p=self.require();corner=self.point_corner.currentText()
        if not corner.startswith('R'):raise ValueError('Locating links belong to the rear template')
        a,b=self.link_inner.currentText(),self.link_outer.currentText()
        if not a or not b or a==b:raise ValueError('Choose two different saved points')
        p.checkpoint('Add locating link');p.data['corners'][corner]['links'].append({'inner':a,'outer':b});p.data['corners'][corner]['confirmed']=False;p.save();self.refresh()
    def remove_link(self):
        p=self.require();c=p.data['corners'][self.point_corner.currentText()]
        if c['links']:p.checkpoint('Remove locating link');c['links'].pop();c['confirmed']=False;p.save();self.refresh()
    def mirror(self):
        p=self.require();source=self.point_corner.currentText();p.mirror_corner(source,source[0]+('R' if source[1]=='L' else 'L'));self.refresh();self.viewport.skeleton()
    def check_kinematics(self):
        c=self.point_corner.currentText();check=Mechanism(self.require(),c).inspect();self.kinematics_info.setText(json.dumps({k:v for k,v in check.items() if k!='samples'},indent=2));self.log.appendPlainText(c+': analytical linkage check passed')
    def preview_travel(self,value):
        if not self.project:return
        try:
            c=self.point_corner.currentText();mechanism=Mechanism(self.project,c);x,pose=mechanism.solve(value/100*self.project.data['parameters']['travel_m']/2);self.viewport.skeleton({c:pose})
            transforms=mechanism.component_transforms(x);self.viewport.preview_transforms={}
            if value:
                for key,component in self.project.data['components'].items():
                    if component['corner']!=c:continue
                    role=(component.get('link_group') or c+'_link_0') if component['role']=='locating_link' else component['role']
                    if role in transforms:self.viewport.preview_transforms[key]=transforms[role]
            self.viewport.refresh()
            self.state.setText(f'Analytical {c} travel: {value/100*self.project.data["parameters"]["travel_m"]*500:.0f} mm')
        except (ValueError,KeyError) as exc:self.state.setText(str(exc))
    def confirm_geometry(self):
        p=self.require();corner=self.point_corner.currentText()
        if self.geometry_confirm.isChecked():Mechanism(p,corner).inspect()
        p.checkpoint('Confirm geometry');p.data['corners'][corner]['confirmed']=self.geometry_confirm.isChecked();p.save()
    def save_parameters(self):
        p=self.require();values={};sources={}
        for row in range(self.params.rowCount()):
            key=self.params.item(row,0).text();text=self.params.item(row,1).text();values[key]=float(text) if isinstance(p.data['parameters'][key],(int,float)) else text;sources[key]=self.params.item(row,2).text()
        if not all(np.isfinite(v) and v>=0 for v in values.values() if isinstance(v,float)):raise ValueError('Parameters must be finite and nonnegative')
        p.checkpoint('Edit hardware parameters');p.data.update(parameters=values,parameter_sources=sources,engine_model=self.engine_model.text(),cvt_model=self.cvt_model.text(),assumptions_accepted=False);p.save();self.refresh()
    def confirm_assumptions(self):p=self.require();p.checkpoint('Review assumptions');p.data['assumptions_accepted']=self.assumptions.isChecked();p.save()
    def validate(self):
        errors=self.require().validate(for_build=True);self.results.setPlainText('\n'.join(errors) if errors else 'Setup complete. Generate to check linkage travel, mass and export.');self.state.setText(f'{len(errors)} unresolved inputs')
    def build(self):
        p=self.require();self.task('Generating vehicle...',lambda progress,cancel:build_vehicle(p,progress,cancel),lambda path:self.results.setPlainText('Build saved:\n'+str(path)))
    def run_test(self):
        from frame_harness.vehicle import run_vehicle,run_acceptance
        p=self.require();manifest=self.current_build()
        scenario=self.scenario.currentText()
        def run(progress,cancel):return run_acceptance(manifest,progress=progress,cancel=cancel) if scenario=='acceptance' else run_vehicle(manifest,scenario,progress=progress,cancel=cancel)
        def complete(result):p.data['last_test']=str(result['directory']);p.save();self.results.setPlainText(json.dumps(result,indent=2))
        self.task('Running BeamNG test...',run,complete)
    def open_build(self):
        path=self.require().data['last_build']
        if not path:raise ValueError('Generate a build first')
        os.startfile(str(Path(path).parent))
    def open_test(self):
        path=self.require().data['last_test']
        if not path:raise ValueError('Run a test first')
        report=Path(path)/'report.html';os.startfile(str(report if report.exists() else path))
    def install(self):
        p=self.require()
        path=install_build(self.current_build(),self.mods.text());self.log.appendPlainText('Installed '+str(path));self.results.appendPlainText('Vehicle selector: '+p.data['name'])
    def current_build(self):
        p=self.require();path=p.data['last_build']
        if not path:raise ValueError('Generate the current setup first')
        manifest=json.loads(Path(path).read_text(encoding='utf-8'))
        if manifest['project_fingerprint']!=p.fingerprint():raise ValueError('Project, chassis or generator changed. Generate a fresh build before testing or installing.')
        from .project import sha256
        if sha256(p.data['assembly'])!=p.data['assembly_sha256']:raise ValueError('The Blender assembly changed. Reimport before testing or installing.')
        return path
    def launch_game(self):
        import subprocess
        from frame_harness.models import HarnessProject
        h=HarnessProject.load();subprocess.Popen([str(h.executable)],cwd=h.game)
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.cancel();self.state.setText('Cancelling; close again when the operation has stopped');event.ignore();return
        if self.project:self.project.save()
        self.viewport.widget.Finalize();event.accept()


def run_gui(path=None):
    app=QApplication.instance() or QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    window=MainWindow(path);window.show();return app.exec()
