from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSEMBLY = Path('H:/beamng project programs/mochi blender work/mochi sep v2.blend')
DEFAULT_BLENDER = Path('C:/Program Files/Blender Foundation/Blender 5.0/blender.exe')
DEFAULT_FRAME = ROOT.parent/'Test Harness/comparisons/4130-complete-20261004/4130-annealed/mochi.jbeam'
CORNERS = ('FL', 'FR', 'RL', 'RR')
FRONT_POINTS = ('upper_inner_front','upper_inner_rear','upper_ball','lower_inner_front','lower_inner_rear','lower_ball',
                'hub','hub_axis','tie_inner','tie_outer','shock_top','shock_bottom')
REAR_POINTS = ('trailing_pivot','hub','hub_axis','shock_top','shock_bottom')
HINGE_POINTS = ('hinge_inner','hinge_outer','hub','hub_axis','shock_top','shock_bottom')
ROLES = ('frame','upper_arm','lower_arm','upright','trailing_arm','locating_link','tie_rod','shock_body','shock_rod',
         'wheel','tire','engine','cvt','differential','shaft','fixed_accessory','ignore')


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temporary.replace(path)


def sha256(path):
    with Path(path).open('rb') as stream:
        digest=hashlib.sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def matrix(translation=(0,0,0),rotation=(0,0,0),pivot=(0,0,0)):
    result=np.eye(4);result[:3,:3]=Rotation.from_euler('xyz',rotation,degrees=True).as_matrix()
    result[:3,3]=np.array(translation)+pivot-result[:3,:3]@np.array(pivot)
    return result


def transform(points, value):
    p=np.asarray(points,dtype=float);m=np.asarray(value,dtype=float)
    return p@m[:3,:3].T+m[:3,3]


def circle_center(points):
    a,b,c=np.asarray(points,float);u=b-a;v=c-a;n=np.cross(u,v)
    if n@n<1e-16:raise ValueError('Pick three noncollinear points on the circle')
    return a+((u@u)*np.cross(v,n)+(v@v)*np.cross(n,u))/(2*(n@n))


def starter_parameters():
    return {'engine_power_kw':10.,'engine_peak_rpm':3600.,'idle_rpm':1200.,'max_rpm':4000.,
            'clutch_start_rpm':1600.,'clutch_full_rpm':2300.,'cvt_min':.8,'cvt_max':3.,'final_drive':8.,
            'engine_mass_kg':30.,'cvt_mass_kg':6.,'frequency_hz':1.5,'damping_ratio':.6,
            'tire_radius_m':.28,'tire_width_m':.19,'rim_radius_m':.16,'tire_pressure_psi':12.,
            'wheel_mass_kg':6.,'brake_torque_nm':650.,'steer_degrees':28.,'travel_m':.16,
            'front_diff':'open','rear_diff':'open','fuel_liters':5.,'ballast_kg':0.}


@dataclass
class VehicleProject:
    path: Path
    data: dict
    undo_stack: list = field(default_factory=list,repr=False)
    redo_stack: list = field(default_factory=list,repr=False)

    @classmethod
    def create(cls,path,assembly=DEFAULT_ASSEMBLY):
        path=Path(path).resolve()
        if path.exists():raise FileExistsError(path)
        data={'version':1,'id':uuid.uuid4().hex,'name':'Mochi First Drive - Prototype','model':'mochi_first_drive',
              'assembly':str(Path(assembly).resolve()),'blender':str(DEFAULT_BLENDER),'frame':str(DEFAULT_FRAME),
              'assembly_sha256':None,'asset_index':None,'revision':0,'components':{},'groups':{},'points':{},
              'corners':{c:{'template':'double_wishbone' if c[0]=='F' else 'trailing_links','points':{},'links':[],
                            'confirmed':False} for c in CORNERS},
              'parameters':starter_parameters(),'parameter_sources':{},'orientation':np.eye(4).tolist(),'mesh_transforms':{},
              'alignment_confirmed':False,'assumptions_accepted':False,'last_build':None,'last_test':None,
              'limitations':['Frame mesh separation and real rupture remain unvalidated.'],
              'view':{'hidden':[],'locked':[]}}
        result=cls(path,data);result.save();return result

    @classmethod
    def load(cls,path):
        path=Path(path).resolve();data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('version')!=1:raise ValueError('Unsupported project version')
        return cls(path,data)

    @property
    def root(self):return self.path.parent

    def save(self):write_json(self.path,self.data)

    def checkpoint(self,label,physical=True):
        self.undo_stack.append((label,copy.deepcopy(self.data)))
        self.undo_stack=self.undo_stack[-60:];self.redo_stack.clear()
        self.data['revision']+=1
        if physical:self.data['last_build']=None;self.data['last_test']=None

    def undo(self):
        if self.undo_stack:
            label,value=self.undo_stack.pop();self.redo_stack.append((label,copy.deepcopy(self.data)))
            self.data=value;self.save()

    def redo(self):
        if self.redo_stack:
            label,value=self.redo_stack.pop();self.undo_stack.append((label,copy.deepcopy(self.data)))
            self.data=value;self.save()

    def index(self):
        if not self.data['asset_index']:return {'objects':[]}
        return json.loads((self.root/self.data['asset_index']).read_text(encoding='utf-8'))

    def owners(self):
        return {m:k for k,c in self.data['components'].items() for m in c['meshes']}

    def assign(self,name,role,meshes,corner='',mass=1.):
        if role not in ROLES:raise ValueError('Unknown component role')
        if not meshes:raise ValueError('Select meshes first')
        if corner and corner not in CORNERS:raise ValueError('Unknown corner')
        if not np.isfinite(mass) or mass<0:raise ValueError('Mass must be finite and nonnegative')
        known={o['id'] for o in self.index()['objects']}
        if not set(meshes)<=known:raise ValueError('Selection contains missing meshes')
        owners=self.owners();old_transforms=[np.linalg.inv(np.asarray(self.data['orientation']))@self.object_transform(m) for m in meshes]
        affected_owners={owners[m] for m in meshes if m in owners}
        new_transform=old_transforms[0] if all(np.allclose(old_transforms[0],m) for m in old_transforms[1:]) else np.eye(4)
        self.checkpoint('Assign component')
        key='c_'+uuid.uuid4().hex[:12]
        # Physical ownership is exclusive; selection groups remain unrestricted.
        for component in self.data['components'].values():component['meshes']=[m for m in component['meshes'] if m not in meshes]
        self.data['components'][key]={'name':name,'role':role,'corner':corner,'meshes':sorted(set(meshes)),
                                     'mass_kg':mass,'mass_source':'assumed','transform':new_transform.tolist()}
        for mesh,old in zip(meshes,old_transforms):self.data.setdefault('mesh_transforms',{})[mesh]=(np.linalg.inv(new_transform)@old).tolist()
        for point in self.data['points'].values():
            old_owner=point.get('component')
            if old_owner and (point.get('mesh') in meshes or old_owner in affected_owners and not self.data['components'][old_owner]['meshes']):
                old_m=np.asarray(self.data['components'][old_owner]['transform'])
                point['position']=transform(point['position'],np.linalg.inv(new_transform)@old_m).tolist();point['component']=key
        for corner_data in self.data['corners'].values():corner_data['confirmed']=False
        self.save();return key

    def object_transform(self,mesh):
        owner=self.owners().get(mesh);m=np.eye(4) if owner is None else np.array(self.data['components'][owner]['transform'])
        return np.asarray(self.data['orientation'])@m@np.asarray(self.data.get('mesh_transforms',{}).get(mesh,np.eye(4)))

    def unassign(self,meshes):
        self.checkpoint('Unassign meshes');orientation=np.asarray(self.data['orientation'])
        for mesh in meshes:self.data.setdefault('mesh_transforms',{})[mesh]=(np.linalg.inv(orientation)@self.object_transform(mesh)).tolist()
        for component in self.data['components'].values():component['meshes']=[m for m in component['meshes'] if m not in meshes]
        for c in self.data['corners'].values():c['confirmed']=False
        self.save()

    def move(self,keys,translation,rotation,pivot=(0,0,0),local=False):
        if not keys:raise ValueError('Select a component first')
        if not np.isfinite([*translation,*rotation,*pivot]).all():raise ValueError('Transform must be finite')
        self.checkpoint('Move components');delta=matrix(translation,rotation,pivot)
        if not local:
            orientation=np.asarray(self.data['orientation']);delta=np.linalg.inv(orientation)@delta@orientation
        for key in keys:
            old=np.array(self.data['components'][key]['transform'])
            self.data['components'][key]['transform']=(old@delta if local else delta@old).tolist()
            if self.data['components'][key]['role']=='frame':self.data['alignment_confirmed']=False
        for c in self.data['corners'].values():c['confirmed']=False
        self.save()

    def set_point(self,name,world,component=None,source='picked',mesh=None):
        if not np.isfinite(world).all():raise ValueError('Point must be finite')
        self.checkpoint('Set point')
        m=np.asarray(self.data['orientation'])
        if component:m=m@np.array(self.data['components'][component]['transform'])
        self.data['points'][name]={'position':transform(np.asarray(world),np.linalg.inv(m)).tolist(),
                                   'component':component,'source':source,'mesh':mesh}
        for c in self.data['corners'].values():c['confirmed']=False
        self.save()

    def point(self,name):
        p=self.data['points'][name];m=np.asarray(self.data['orientation'])
        if p['component']:m=m@np.array(self.data['components'][p['component']]['transform'])
        return transform(p['position'],m)

    def corner_points(self,corner):
        return {role:self.point(name) for role,name in self.data['corners'][corner]['points'].items()}

    def bind_point(self,corner,role,name):
        self.checkpoint('Bind suspension point');self.data['corners'][corner]['points'][role]=name
        self.data['corners'][corner]['confirmed']=False;self.save()

    def mirror_corner(self,source,target):
        if source[0]!=target[0] or source==target:raise ValueError('Mirror within the same axle')
        self.checkpoint('Mirror suspension');data=copy.deepcopy(self.data['corners'][source])
        mapping={}
        names=list(data['points'].values())+[n for link in data['links'] for n in (link['inner'],link['outer'])]
        for name in names:
            if name in mapping:continue
            point=self.point(name);point[0]*=-1;new=target+'_'+name
            local=transform(point,np.linalg.inv(np.array(self.data['orientation'])))
            self.data['points'][new]={'position':local.tolist(),'component':None,'source':'mirrored - review required'};mapping[name]=new
        data['points']={r:mapping[n] for r,n in data['points'].items()}
        for link in data['links']:link.update(inner=mapping[link['inner']],outer=mapping[link['outer']])
        data['confirmed']=False;self.data['corners'][target]=data;self.save()

    def fingerprint(self):
        data={k:v for k,v in self.data.items() if k not in ('view','groups','revision','last_build','last_test')}
        data['generator_version']=2
        data['generator_sha256']={name:sha256(Path(__file__).with_name(name)) for name in ('build.py','collada.py','kinematics.py')}
        if Path(self.data['frame']).exists():data['frame_content_sha256']=sha256(self.data['frame'])
        return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

    def validate(self,for_build=False):
        problems=[]
        if not re.fullmatch('[a-z][a-z0-9_]{1,45}',self.data['model']):problems.append('Model ID must use lowercase letters, digits and underscores')
        if not self.data['asset_index']:problems.append('Import the assembly first')
        if not Path(self.data['frame']).is_file():problems.append('Select a generated chassis JBeam')
        if not self.data['alignment_confirmed']:problems.append('Assembly: confirm scale, axes and chassis alignment')
        known={o['id'] for o in self.index()['objects']};seen=set()
        def rigid(value):
            m=np.asarray(value)
            return m.shape==(4,4) and np.isfinite(m).all() and np.allclose(m[3],[0,0,0,1]) and np.allclose(m[:3,:3].T@m[:3,:3],np.eye(3),atol=1e-6) and np.linalg.det(m[:3,:3])>0
        if not rigid(self.data['orientation']):problems.append('Assembly orientation must be a finite rigid transform')
        for name,value in self.data.get('mesh_transforms',{}).items():
            if not rigid(value):problems.append(name+': invalid mesh placement')
        for key,c in self.data['components'].items():
            for m in c['meshes']:
                if m not in known:problems.append(c['name']+': source mesh missing')
                if m in seen:problems.append(c['name']+': duplicate mass/mesh ownership')
                seen.add(m)
            if not np.isfinite(c['mass_kg']) or c['mass_kg']<0:problems.append(c['name']+': invalid mass')
            if c['meshes'] and c['role'] not in ('ignore','frame') and c['mass_kg']<=0:problems.append(c['name']+': enter a positive component mass')
            if c['role'] not in ROLES:problems.append(c['name']+': unknown role')
            if not rigid(c['transform']):problems.append(c['name']+': invalid placement transform')
        for name,point in self.data['points'].items():
            if point.get('component') and point['component'] not in self.data['components']:problems.append(name+': missing owner component')
            if len(point['position'])!=3 or not np.isfinite(point['position']).all():problems.append(name+': invalid coordinate')
        if for_build and known-seen:problems.append(f'Assign or explicitly ignore {len(known-seen)} remaining mesh objects')
        if for_build and not any(c['role']=='frame' and c['meshes'] for c in self.data['components'].values()):problems.append('Assign the frame meshes')
        for corner,c in self.data['corners'].items():
            if c['template'] not in ('double_wishbone','trailing_arm','trailing_links'):problems.append(corner+': unsupported suspension template')
            required=FRONT_POINTS if c['template']=='double_wishbone' else HINGE_POINTS if c['template']=='trailing_arm' else REAR_POINTS
            for role in required:
                if c['points'].get(role) not in self.data['points']:problems.append(corner+': place '+role)
            if c['template']=='trailing_links' and len(c['links'])<2:problems.append(corner+': identify at least two locating links')
            for link in c['links']:
                if any(link.get(k) not in self.data['points'] for k in ('inner','outer')):problems.append(corner+': incomplete locating link')
            if for_build and not c['confirmed']:problems.append(corner+': confirm geometry')
        for name in ('engine_center','engine_mount_1','engine_mount_2','engine_mount_3','cvt_center'):
            if name not in self.data['points']:problems.append('Powertrain: place '+name)
        p=self.data['parameters']
        for key,value in p.items():
            if isinstance(value,(int,float)) and (not np.isfinite(value) or value<0):problems.append('Invalid parameter '+key)
        if not 0<p['cvt_min']<p['cvt_max']:problems.append('CVT minimum ratio must be below maximum')
        if not 0<p['rim_radius_m']<p['tire_radius_m']:problems.append('Rim must fit inside tire')
        if not p['idle_rpm']<p['clutch_start_rpm']<p['clutch_full_rpm']<p['max_rpm']:problems.append('Check idle, clutch engagement and maximum RPM')
        for key in ('front_diff','rear_diff'):
            if p[key] not in ('open','locked','lsd'):problems.append(key+': choose open, locked or lsd')
        for key in ('engine_mass_kg','cvt_mass_kg','engine_power_kw','engine_peak_rpm','final_drive','frequency_hz','travel_m','tire_width_m','wheel_mass_kg'):
            if p[key]<=0:problems.append(key+': must be positive')
        if for_build and not self.data['assumptions_accepted']:problems.append('Review and accept the provisional hardware values')
        return list(dict.fromkeys(problems))
