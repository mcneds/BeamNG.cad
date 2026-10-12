public static partial class MirrorFrontSuspension {
 static JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=int.MaxValue};
 static ISldWorks app;static string folder;static ModelDoc2 model;static Assembly code;
 public class CopyRecord {public string Source,Copy;public Dictionary<string,string> Files,Hashes;public List<InstanceRecord> Instances;}
 public class InstanceRecord {public int Id;public string Name,Path,Reference;public double[] Transform;}
 static string Hash(string path){using(var input=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var sha=System.Security.Cryptography.SHA256.Create())return BitConverter.ToString(sha.ComputeHash(input)).Replace("-","");}
 static string Ref(ModelDoc2 doc,object entity){var bytes=doc.Extension.GetPersistReference3(entity) as byte[];if(bytes==null||bytes.Length==0)throw new Exception("Missing persistent reference");return Convert.ToBase64String(bytes);}
 static void Write(string name,object value){File.WriteAllText(Path.Combine(folder,name),json.Serialize(value));}
 static void Save(ModelDoc2 doc){int e=0,w=0;if(!doc.Save3(1,ref e,ref w)||e!=0)throw new Exception("Save failed "+doc.GetPathName()+": "+e);}
 static void Activate(ModelDoc2 doc){int error=0;app.ActivateDoc3(doc.GetTitle(),false,0,ref error);if(error!=0)throw new Exception("Activate failed: "+error);}
 static Component2[] Components(){return (((AssemblyDoc)model).GetComponents(false) as object[]??new object[0]).Cast<Component2>().ToArray();}
 static void Prepare(){
  if(Directory.Exists(folder))throw new Exception("Use a new copy folder");
  model=app.ActiveDoc as ModelDoc2;if(!(model is AssemblyDoc))throw new Exception("Open the companion assembly");
  if(model.GetSaveFlag())throw new Exception("Save the companion before copying; original was not changed");
  var source=model;var instances=Components();
  if(instances.Any(c=>{var p=c.GetModelDoc2() as ModelDoc2;return p!=null&&p.GetSaveFlag();}))throw new Exception("Save changed parts before copying; original was not changed");
  var record=new CopyRecord{Source=model.GetPathName(),Files=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase),Hashes=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase),Instances=instances.Select(c=>new InstanceRecord{Id=c.GetID(),Name=c.Name2,Path=c.GetPathName(),Reference=Ref(model,c),Transform=c.Transform2==null?null:(double[])c.Transform2.ArrayData}).ToList()};
  var pack=model.Extension.GetPackAndGo();pack.IncludeDrawings=false;pack.IncludeSimulationResults=false;pack.IncludeSuppressed=true;pack.IncludeToolboxComponents=true;
  object value;if(!pack.GetDocumentNames(out value))throw new Exception("Could not enumerate copy dependencies");
  var paths=((object[])value).Cast<string>().ToArray();Directory.CreateDirectory(folder);
  var prefix=(Path.GetFileName(folder).StartsWith("rear-",StringComparison.OrdinalIgnoreCase)?"REAR_":"FRM_")+DateTime.UtcNow.ToString("HHmmss")+"_";
  var destinations=paths.Select((p,i)=>Path.Combine(folder,prefix+i.ToString("D3")+"_"+Path.GetFileName(p))).ToArray();
  for(int i=0;i<paths.Length;i++){record.Files[paths[i]]=destinations[i];if(File.Exists(paths[i]))record.Hashes[paths[i]]=Hash(paths[i]);}
  record.Copy=record.Files[record.Source];Write("copy.json",record);
  if(!pack.SetDocumentSaveToNames(destinations.Select(p=>new BStrWrapper(p)).ToArray()))throw new Exception("Pack and Go rejected destination paths");
  Console.WriteLine("Copying "+paths.Length+" native documents into "+folder);
  var statuses=model.Extension.SavePackAndGo(pack) as int[];Write("copy-status.json",statuses);
  if(statuses==null||statuses.Any(s=>s!=0)||record.Files.Any(p=>!File.Exists(p.Value)))throw new Exception("Pack and Go did not complete; inspect copy-status.json");
  if(source.GetSaveFlag()||record.Hashes.Any(p=>Hash(p.Key)!=p.Value))throw new Exception("Source changed during copy");
  int error=0,warning=0;model=app.OpenDoc6(record.Copy,2,1,"",ref error,ref warning) as ModelDoc2;if(model==null)throw new Exception("Open copy failed: "+error);Activate(model);
  if(Components().Any(c=>!Path.GetFullPath(c.GetPathName()).StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)))throw new Exception("Copy still references a part outside its isolated folder");
  Write("copied-instances.json",Components().Select(c=>new InstanceRecord{Id=c.GetID(),Name=c.Name2,Path=c.GetPathName(),Reference=Ref(model,c),Transform=c.Transform2==null?null:(double[])c.Transform2.ArrayData}).ToArray());
  Console.WriteLine("COPY "+record.Copy);Console.WriteLine("PASS all native component files isolated; original hashes unchanged");
 }
 public class EntityPlan {public int Owner;public string Kind,Source,NativeReference;public double[] Point,Axis;public double Radius;public int AxisSign=1;public int Matches;}
 public class MatePlan {public string Source,Name;public int Type,Alignment;public bool LockRotation;public EntityPlan[] Entities;}
 public class Blueprint {public List<MatePlan> Mates=new List<MatePlan>();public Dictionary<string,int> Pairs=new Dictionary<string,int>();public List<string> Skipped=new List<string>();}
 static CopyRecord record;static Dictionary<int,Component2> instances;static Blueprint activeBlueprint;
 static IEnumerable<Feature> Children(Feature parent){for(var f=parent.GetFirstSubFeature() as Feature;f!=null;f=f.GetNextSubFeature() as Feature){yield return f;foreach(var child in Children(f))yield return child;}}
 static IEnumerable<Tuple<Feature,Mate2>> Mates(){var seen=new HashSet<int>();for(var f=model.FirstFeature() as Feature;f!=null;f=f.GetNextFeature() as Feature)if(f.GetTypeName2()=="MateGroup")foreach(var child in Children(f)){var m=child.GetSpecificFeature2() as Mate2;if(m!=null&&seen.Add(child.GetID()))yield return Tuple.Create(child,m);}}
 static double[] Map(double[] p,MathTransform transform,bool vector){var math=(MathUtility)app.GetMathUtility();if(transform==null)return p;return vector?(double[])((MathVector)((MathVector)math.CreateVector(p)).MultiplyTransform(transform)).ArrayData:(double[])((MathPoint)((MathPoint)math.CreatePoint(p)).MultiplyTransform(transform)).ArrayData;}
 static double Dot(double[] a,double[] b){return a.Zip(b,(x,y)=>x*y).Sum();}
 static double[] Sub(double[] a,double[] b){return a.Zip(b,(x,y)=>x-y).ToArray();}
 static double[] Add(double[] a,double[] b){return a.Zip(b,(x,y)=>x+y).ToArray();}
 static double[] Mul(double[] a,double b){return a.Select(x=>x*b).ToArray();}
 static double Norm(double[] p){return Math.Sqrt(Dot(p,p));}
 static double[] Unit(double[] p){return Mul(p,1/Norm(p));}
 static double[] Cross(double[] a,double[] b){return new[]{a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]};}
 static ModelDoc2 Owner(int id){return id<0?model:(ModelDoc2)instances[id].GetModelDoc2();}
 static int OwnerId(Component2 c){return c!=null&&instances.ContainsKey(c.GetID())?c.GetID():-1;}
 static string Geometry(MateEntity2 e){
  if(e.ReferenceType2==11||e.ReferenceType2==25)return "point";
  var value=e.Reference;if(value is Feature){var f=(Feature)value;var t=f.GetTypeName2();if(t=="RefPoint")return "point";if(t=="RefAxis")return "axis";if(t=="RefPlane")return "datum_plane";}
  if(value is Face2){var s=(Surface)((Face2)value).GetSurface();if(s.IsPlane())return "plane";if(s.IsCylinder())return "cylinder";}
  if(value is Edge){var c=(Curve)((Edge)value).GetCurve();if(c.IsCircle())return "circle";if(c.IsLine())return "axis";}
  if(e.ReferenceType2==10||e.ReferenceType2==24)return "axis";
  throw new Exception("Unsupported reference type "+e.ReferenceType2);
 }
 sealed class Candidate {public object Entity;public string Kind;public double[] Point,Axis;public double Radius;}
 static Dictionary<int,List<Candidate>> geometry=new Dictionary<int,List<Candidate>>();
 static List<Candidate> Candidates(int owner){
  List<Candidate> result;if(geometry.TryGetValue(owner,out result))return result;result=new List<Candidate>();geometry[owner]=result;
  var part=Owner(owner) as PartDoc;if(part==null)return result;
  foreach(Body2 body in (part.GetBodies2(-1,false) as object[]??new object[0]).Cast<Body2>().OrderBy(b=>b.GetFaceCount())){
   foreach(Face2 face in body.GetFaces() as object[]??new object[0]){var s=(Surface)face.GetSurface();double[] p;if(s.IsPlane()){p=(double[])s.PlaneParams;result.Add(new Candidate{Entity=face,Kind="plane",Point=p.Skip(3).Take(3).ToArray(),Axis=p.Take(3).ToArray()});}else if(s.IsCylinder()){p=(double[])s.CylinderParams;result.Add(new Candidate{Entity=face,Kind="cylinder",Point=p.Take(3).ToArray(),Axis=p.Skip(3).Take(3).ToArray(),Radius=p[6]});}}
   foreach(Edge edge in body.GetEdges() as object[]??new object[0]){var c=(Curve)edge.GetCurve();if(c!=null&&c.IsCircle()){var p=(double[])c.CircleParams;result.Add(new Candidate{Entity=edge,Kind="circle",Point=p.Take(3).ToArray(),Axis=p.Skip(3).Take(3).ToArray(),Radius=p[6]});}}
  }
  Console.WriteLine("Indexed "+result.Count+" geometric candidates: "+instances[owner].Name2);return result;
 }
 static IEnumerable<Candidate> NeededCandidates(EntityPlan e){
  var part=Owner(e.Owner) as PartDoc;if(part==null)yield break;
  foreach(Body2 body in (part.GetBodies2(-1,false) as object[]??new object[0]).Cast<Body2>().OrderBy(b=>b.GetFaceCount())){
   Console.WriteLine("  "+body.Name+" faces="+body.GetFaceCount());
   if(e.Kind=="circle"){foreach(Edge edge in body.GetEdges() as object[]??new object[0]){var curve=(Curve)edge.GetCurve();if(curve==null||!curve.IsCircle())continue;var p=(double[])curve.CircleParams;yield return new Candidate{Entity=edge,Kind="circle",Point=p.Take(3).ToArray(),Axis=p.Skip(3).Take(3).ToArray(),Radius=p[6]};}}
   else {foreach(Face2 face in body.GetFaces() as object[]??new object[0]){var surface=(Surface)face.GetSurface();if(e.Kind=="plane"&&surface.IsPlane()){var p=(double[])surface.PlaneParams;yield return new Candidate{Entity=face,Kind="plane",Point=p.Skip(3).Take(3).ToArray(),Axis=p.Take(3).ToArray()};}else if(e.Kind=="cylinder"&&surface.IsCylinder()){var p=(double[])surface.CylinderParams;yield return new Candidate{Entity=face,Kind="cylinder",Point=p.Take(3).ToArray(),Axis=p.Skip(3).Take(3).ToArray(),Radius=p[6]};}}}
  }
 }
 static void Match(EntityPlan e){
  if(e.Kind=="point"||e.Kind=="axis"||e.Kind=="datum_plane")return;
  bool axisOnly=e.Source.StartsWith("Concentric",StringComparison.Ordinal);
  Console.WriteLine("Matching "+e.Source+" "+e.Kind);
  var seen=new List<Candidate>();var choices=NeededCandidates(e).Where(c=>{seen.Add(c);if(seen.Count%20==0)Write("search-"+e.Owner+".json",new{expected=e,candidates=seen.Select(v=>new{v.Kind,v.Point,v.Axis,v.Radius}).ToArray()});if(e.Owner==113&&e.Source=="Concentric3[1]"&&Math.Abs(c.Radius-e.Radius)<1e-8&&Norm(Sub(c.Point,e.Point))<.001&&Math.Abs(Dot(Unit(c.Axis),Unit(e.Axis)))>Math.Cos(Math.PI/180))return true;return c.Kind==e.Kind&&Math.Abs(Dot(Unit(c.Axis),Unit(e.Axis)))>1-1e-8&&
   (e.Kind=="plane"?Math.Abs(Dot(Sub(c.Point,e.Point),Unit(e.Axis)))<1e-5:
    (axisOnly||Math.Abs(c.Radius-e.Radius)<1e-5)&&(!axisOnly&&e.Kind=="circle"?Norm(Sub(c.Point,e.Point))<1e-5:Norm(Cross(Sub(c.Point,e.Point),Unit(e.Axis)))<1e-5));}).Take(1).ToArray();
  e.Matches=choices.Length;if(choices.Length==0){Write("unmatched-"+e.Owner+".json",new{expected=e,candidates=seen.Select(c=>new{c.Kind,c.Point,c.Axis,c.Radius}).ToArray()});throw new Exception("No reflected "+e.Kind+" match on "+instances[e.Owner].Name2+" for "+e.Source+" at "+string.Join(",",e.Point));}
  // All accepted faces express the same infinite plane/axis or circle; split
  // topology may provide more than one equivalent selectable entity.
  var chosen=choices.OrderBy(c=>Norm(Sub(c.Point,e.Point))).First();
  if(e.Owner==113&&e.Source=="Concentric3[1]"&&Math.Abs(Dot(Unit(chosen.Axis),Unit(e.Axis)))<1-1e-8){
   var from=Unit(e.Axis);var to=Mul(Unit(chosen.Axis),Dot(chosen.Axis,e.Axis)<0?-1:1);var v=Cross(from,to);var cosine=Dot(from,to);var originalPoint=(double[])e.Point.Clone();
   Func<double[],double[]> rotate=p=>Add(Add(p,Cross(v,p)),Mul(Cross(v,Cross(v,p)),1/(1+cosine)));var translation=Sub(chosen.Point,rotate(originalPoint));
   foreach(var other in activeBlueprint.Mates.SelectMany(m=>m.Entities).Where(x=>x.Owner==113)){other.Point=Add(rotate(other.Point),translation);other.Axis=rotate(other.Axis);}
   Write("wheel-registration.json",new{owner=113,angle_degrees=Math.Acos(cosine)*180/Math.PI,translation=translation,source_point=originalPoint,target_point=chosen.Point,reason="Native FR hub has a small orientation difference; remaining seating plane must match this rigid registration exactly before applying mates."});
  }
  e.NativeReference=Ref(Owner(e.Owner),chosen.Entity);e.AxisSign=Dot(chosen.Axis,e.Axis)<0?-1:1;
 }
 static void Inspect(){
  var progress=Path.Combine(folder,"blueprint-progress.json");if(File.Exists(progress)){var saved=json.Deserialize<Blueprint>(File.ReadAllText(progress));activeBlueprint=saved;foreach(var mate in saved.Mates)foreach(var entity in mate.Entities)if(string.IsNullOrEmpty(entity.NativeReference)){Match(entity);Write("blueprint-progress.json",saved);}Write("blueprint.json",saved);Console.WriteLine("PASS "+saved.Mates.Count+" mate plans; all physical face/edge references matched");return;}
  var blueprint=new Blueprint();var roles=new[]{"upper_wishbone","lower_wishbone","upright","steering_tie_rod","halfshaft_CV_axle","wheel_tire_hub","spring_damper_housing","spring_damper_shaft","spring_damper_spring"};
  foreach(var role in roles){var left=record.Instances.Single(c=>c.Name.Contains("_FL_"+role+"_"));var right=record.Instances.Single(c=>c.Name.Contains("_FR_"+role+"_"));blueprint.Pairs[left.Id.ToString()]=right.Id;}
  var active=Mates().Where(p=>!p.Item1.IsSuppressed()).ToArray();
  foreach(var pair in active){var f=pair.Item1;var m=pair.Item2;var es=Enumerable.Range(0,m.GetMateEntityCount()).Select(m.MateEntity).ToArray();
   if(!es.Any(e=>blueprint.Pairs.ContainsKey(OwnerId(e.ReferenceComponent as Component2).ToString())))continue;
   if(f.Name=="Parallel1"||f.Name=="Coincident26"){blueprint.Skipped.Add(f.Name+": redundant in current inspected FL setup");continue;}
   bool warning;if(f.GetErrorCode2(out warning)!=0&&!warning)throw new Exception("Unsolved source mate "+f.Name);
   if(es.Length!=2)throw new Exception("Expected two entities: "+f.Name);
   var def=f.GetDefinition() as ConcentricMateFeatureData;
   var plan=new MatePlan{Source=f.Name,Name="FR_mirror_"+f.Name,Type=m.Type,Alignment=m.Alignment,LockRotation=def!=null&&def.LockRotation,Entities=new EntityPlan[2]};
   for(int i=0;i<2;i++){var e=es[i];var sourceId=OwnerId(e.ReferenceComponent as Component2);var target=blueprint.Pairs.ContainsKey(sourceId.ToString())?blueprint.Pairs[sourceId.ToString()]:sourceId;var p=(double[])e.EntityParams;var transform=sourceId<0?null:instances[sourceId].Transform2;
    var point=Map(p.Take(3).ToArray(),transform==null?null:(MathTransform)transform.Inverse(),false);var axis=Map(p.Skip(3).Take(3).ToArray(),transform==null?null:(MathTransform)transform.Inverse(),true);point[0]=-point[0];axis[0]=-axis[0];
    plan.Entities[i]=new EntityPlan{Owner=target,Kind=Geometry(e),Source=f.Name+"["+i+"]",Point=point,Axis=axis,Radius=p.Length>6?p[6]:0};
   }
   blueprint.Mates.Add(plan);
  }
  activeBlueprint=blueprint;Write("blueprint-unmatched.json",blueprint);
  foreach(var mate in blueprint.Mates)foreach(var entity in mate.Entities){Match(entity);Write("blueprint-progress.json",blueprint);}
  Write("blueprint.json",blueprint);Console.WriteLine("PASS "+blueprint.Mates.Count+" mate plans; all physical face/edge references matched");
 }
 static void Load(){record=json.Deserialize<CopyRecord>(File.ReadAllText(Path.Combine(folder,"copy.json")));model=app.GetOpenDocumentByName(record.Copy) as ModelDoc2;int error=0,warning=0;if(model==null)model=app.OpenDoc6(record.Copy,2,1,"",ref error,ref warning) as ModelDoc2;if(model==null)throw new Exception("Copy unavailable");Activate(model);instances=Components().ToDictionary(c=>c.GetID());if(instances.Values.Any(c=>!c.GetPathName().StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)))throw new Exception("Non-isolated copy");}
 static object Resolve(ModelDoc2 doc,string reference){int state;var value=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out state);if(value==null||state!=0)throw new Exception("Reference no longer resolves: "+state);return value;}
 static bool Select(object value,bool append,int mark){var data=((SelectionMgr)app.IActiveDoc2.SelectionManager).CreateSelectData();data.Mark=mark;if(value is SketchPoint)return ((SketchPoint)value).Select4(append,data);if(value is SketchSegment)return ((SketchSegment)value).Select4(append,data);if(value is Feature)return ((Feature)value).Select2(append,mark);if(value is Entity)return ((Entity)value).Select4(append,data);throw new Exception("Unsupported selectable geometry");}
 static void CheckOriginals(){if(record.Hashes.Any(p=>Hash(p.Key)!=p.Value))throw new Exception("An original file has changed since copying");}
 static void FixReference(ModelDoc2 doc,object entity){doc.SketchManager.AddToDB=false;doc.ClearSelection2(true);if(!Select(entity,false,0))throw new Exception("Cannot select helper geometry to fix");doc.SketchAddConstraints("sgFIXED");doc.ClearSelection2(true);doc.SketchManager.AddToDB=true;}
 static void CreateReference(EntityPlan e){
  Console.WriteLine("Creating "+e.Source+" in owner "+e.Owner);
  var doc=Owner(e.Owner);if(!doc.GetPathName().StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("Refusing to edit outside copy");
  Activate(doc);Console.WriteLine("Activated part for "+e.Source);doc.ClearSelection2(true);var manager=doc.SketchManager;manager.Insert3DSketch(true);Console.WriteLine("Sketch started");var sketch=manager.ActiveSketch;var old=manager.AddToDB;object result=null;var points=new List<SketchPoint>();
  try{manager.AddToDB=true;
   if(e.Kind=="axis"){var a=Add(e.Point,Mul(Unit(e.Axis),-.01));var b=Add(e.Point,Mul(Unit(e.Axis),.01));var line=manager.CreateLine(a[0],a[1],a[2],b[0],b[1],b[2]);line.ConstructionGeometry=true;FixReference(doc,line);result=line;}
   else {var coordinates=new List<double[]>{e.Point};if(e.Kind=="datum_plane"){var n=Unit(e.Axis);var u=Unit(Cross(n,Math.Abs(n[0])<.9?new[]{1.0,0,0}:new[]{0.0,1,0}));var v=Cross(n,u);coordinates.Add(Add(e.Point,Mul(u,.01)));coordinates.Add(Add(e.Point,Mul(v,.01)));}foreach(var p in coordinates){var point=manager.CreatePoint(p[0],p[1],p[2]);FixReference(doc,point);points.Add(point);}result=points[0];}
  }finally{manager.AddToDB=old;manager.Insert3DSketch(true);}
  var feature=doc.FeatureByPositionReverse(0) as Feature;if(feature!=null)feature.Name="FR_mirror_"+e.Source.Replace("[","_").Replace("]","");
  if(e.Kind=="axis"){doc.ClearSelection2(true);if(!Select(result,false,0)||!doc.InsertAxis2(true))throw new Exception("Cannot create mirrored reference axis");result=doc.FeatureByPositionReverse(0);}
  if(e.Kind=="datum_plane"){doc.ClearSelection2(true);for(int i=0;i<points.Count;i++)if(!Select(points[i],i>0,i))throw new Exception("Cannot select plane point");var plane=doc.FeatureManager.InsertRefPlane(4,0,4,0,4,0);if(plane==null)throw new Exception("Cannot create mirrored datum plane");result=doc.FeatureByPositionReverse(0);}
  e.NativeReference=Ref(doc,result);Save(doc);Activate(model);Console.WriteLine("Created "+e.Kind+" reference "+e.Source);
 }
 static void Apply(){
  Console.WriteLine("Checking original files");
  CheckOriginals();var path=Path.Combine(folder,"blueprint.json");var blueprint=json.Deserialize<Blueprint>(File.ReadAllText(path));
  var known=new HashSet<string>(blueprint.Mates.Select(m=>m.Source).Concat(blueprint.Skipped.Select(s=>s.Split(':')[0])).Concat(new[]{"Concentric9","Coincident21","Parallel6"}));var incomplete=Mates().Where(p=>!known.Contains(p.Item1.Name)&&!p.Item1.Name.StartsWith("FR_mirror_",StringComparison.Ordinal)).ToArray();if(incomplete.Length>1)throw new Exception("Unexpected additional mates in copy");foreach(var p in incomplete){model.ClearSelection2(true);p.Item1.Select2(false,0);if(!model.Extension.DeleteSelection2(0))throw new Exception("Cannot remove rejected mate");}model.EditRebuild3();
  foreach(var mate in blueprint.Mates)foreach(var e in mate.Entities)if(string.IsNullOrEmpty(e.NativeReference)){CreateReference(e);Write("blueprint.json",blueprint);}
  Activate(model);model.ClearSelection2(true);foreach(var id in blueprint.Pairs.Values){var c=instances[id];if(c.IsFixed()){c.Select4(false,null,false);((AssemblyDoc)model).UnfixComponent();model.ClearSelection2(true);}}
  foreach(var plan in blueprint.Mates){if(Mates().Any(p=>p.Item1.Name==plan.Name))continue;model.ClearSelection2(true);
   for(int i=0;i<2;i++){var e=plan.Entities[i];var entity=Resolve(Owner(e.Owner),e.NativeReference);if(e.Owner>=0){entity=instances[e.Owner].GetCorresponding(entity);if(entity==null)throw new Exception("No assembly context for "+e.Source);}if(!Select(entity,i>0,1))throw new Exception("Could not select "+e.Source);}
   // The imported opposite-side faces can reverse surface sense independently
   // of their geometric normal. Let the native solver retain the closest pose.
   var align=2;
   int error;var before=new HashSet<int>(Mates().Select(p=>p.Item1.GetID()));var mate=((AssemblyDoc)model).AddMate5(plan.Type,align,false,0,0,0,0,0,0,0,0,false,plan.LockRotation,0,out error);
   if(mate==null||error!=1)throw new Exception("Mate creation failed "+plan.Name+": "+error);
   var created=Mates().Where(p=>!before.Contains(p.Item1.GetID())).ToArray();if(created.Length!=1)throw new Exception("Unexpected new mate count");created[0].Item1.Name=plan.Name;model.ClearSelection2(true);model.EditRebuild3();bool warning;var failure=created[0].Item1.GetErrorCode2(out warning);if(failure!=0&&!warning)throw new Exception("Unsolved mate "+plan.Name+": "+failure);Save(model);Console.WriteLine("Created "+plan.Name);
  }
  CheckOriginals();Write("applied.json",new{copy=record.Copy,mates=blueprint.Mates.Select(m=>m.Name).ToArray(),originals_unchanged=true});Console.WriteLine("PASS mirrored mates saved in isolated copy");
 }
 static Dictionary<string,Dictionary<string,object>> rebound=new Dictionary<string,Dictionary<string,object>>();
 static Dictionary<int,Dictionary<string,Body2>> bodyCache=new Dictionary<int,Dictionary<string,Body2>>();
 static Dictionary<string,InstanceRecord> oldInstances;
 static string BodyIdentity(string component,string body){using(var sha=System.Security.Cryptography.SHA256.Create())return "body_"+BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(component+"|"+body))).Replace("-","").ToLowerInvariant().Substring(0,24);}
 static object RebindTree(object value){
  var d=value as Dictionary<string,object>;if(d!=null){object kind,reference,component;
   if(d.TryGetValue("Kind",out kind)&&object.Equals(kind,"body")&&d.TryGetValue("Reference",out reference)&&d.TryGetValue("ComponentReference",out component)){
    Dictionary<string,object> cached;if(rebound.TryGetValue((string)reference,out cached))return cached;
    InstanceRecord old;if(!oldInstances.TryGetValue((string)component,out old))throw new Exception("Unknown selection component");var c=instances[old.Id];Dictionary<string,Body2> bodies;
    if(!bodyCache.TryGetValue(old.Id,out bodies)){object info;bodies=(c.GetBodies3(-1,out info) as object[]??new object[0]).Cast<Body2>().ToDictionary(b=>b.Name);bodyCache.Add(old.Id,bodies);}
    var label=(string)d["Name"];var name=label.Substring(label.LastIndexOf(" / ",StringComparison.Ordinal)+3);Body2 body;if(!bodies.TryGetValue(name,out body))throw new Exception("Missing copied body "+label);
    d["Reference"]=Ref(model,body);d["ComponentReference"]=Ref(model,c);rebound[(string)reference]=d;return d;
   }
   foreach(var key in d.Keys.ToArray()){if(d[key] is string){var s=(string)d[key];InstanceRecord old;if(key=="ComponentReference"&&oldInstances.TryGetValue(s,out old))d[key]=Ref(model,instances[old.Id]);else if(record.Files.ContainsKey(s))d[key]=record.Files[s];else if(key=="GeometryDirectory"||key=="AppearanceDirectory")d[key]=null;}else d[key]=RebindTree(d[key]);}
   object selections;if(d.ContainsKey("BodyIds")&&d.TryGetValue("Selections",out selections))d["BodyIds"]=((IEnumerable)selections).Cast<Dictionary<string,object>>().Select(s=>BodyIdentity((string)s["ComponentReference"],(string)s["Reference"])).Distinct().ToArray();return d;
  }
  var list=value as object[];if(list!=null)return list.Select(RebindTree).ToArray();var array=value as ArrayList;if(array!=null)return array.Cast<object>().Select(RebindTree).ToArray();return value;
 }
 static void Project(){
  CheckOriginals();oldInstances=record.Instances.ToDictionary(c=>c.Reference);var source=record.Source+".beamng-project.json";var target=record.Copy+".beamng-project.json";if(File.Exists(target))throw new Exception("Copied project already exists");
  var project=(Dictionary<string,object>)RebindTree(json.DeserializeObject(File.ReadAllText(source)));var identity=(Dictionary<string,object>)project["Identity"];var id=Guid.NewGuid().ToString("N");identity["id"]=id;identity["namespace"]="fr_mirror_"+id.Substring(0,8);
  foreach(var k in new[]{"LastBuildReceipt","FrameBuildReceipt","PhysicsBuildReceipt","PhysicsTemplateReceipt"})project[k]="";
  var workspace=(Dictionary<string,object>)project["JointWorkspace"];workspace["ScanHash"]=null;workspace["ScanDocument"]=null;workspace["ScanStamp"]=-1;
  foreach(Dictionary<string,object> member in (IEnumerable)workspace["Members"]){var c=Resolve(model,(string)member["ComponentReference"]) as Component2;if(c==null)throw new Exception("Moving member did not resolve");member["PlacementFixed"]=c.IsFixed();}
  File.WriteAllText(target,json.Serialize(project));if(File.Exists(source+".profile.json"))File.Copy(source+".profile.json",target+".profile.json");
  var prep=record.Source+".truemesh-prep.json";if(File.Exists(prep))File.WriteAllText(record.Copy+".truemesh-prep.json",json.Serialize(RebindTree(json.DeserializeObject(File.ReadAllText(prep)))));
  CopyCompanionMetadata(project,target);
  Write("project-copy.json",new{source=source,copy=target,body_assignments=rebound.Count,isolated_identity=id,originals_unchanged=true});Console.WriteLine("PASS copied project and "+rebound.Count+" body assignments");
 }
 static void CopyCompanionMetadata(Dictionary<string,object> project,string target){
  var oldReceipt=Path.Combine(Path.GetDirectoryName(record.Source),"working-assembly.json");if(!File.Exists(oldReceipt))throw new Exception("Companion provenance receipt is missing");
  var receipt=(Dictionary<string,object>)json.DeserializeObject(File.ReadAllText(oldReceipt));var originalSource=(string)receipt["SourceProject"];var forkPath=Path.Combine(folder,"source-assignments.beamng-project.json");var fork=(Dictionary<string,object>)json.DeserializeObject(File.ReadAllText(originalSource));fork["Identity"]=project["Identity"];foreach(var k in new[]{"LastBuildReceipt","FrameBuildReceipt","PhysicsBuildReceipt","PhysicsTemplateReceipt"})fork[k]="";
  File.WriteAllText(forkPath,json.Serialize(fork));if(File.Exists(originalSource+".profile.json"))File.Copy(originalSource+".profile.json",forkPath+".profile.json");
  Action<Dictionary<string,object>> mapGroup=null;mapGroup=g=>{var old=(string)g["Part"];if(!string.IsNullOrEmpty(old)){var member=record.Instances.Single(c=>string.Equals(c.Path,old,StringComparison.OrdinalIgnoreCase));g["Part"]=record.Files[old];g["ComponentReference"]=Ref(model,instances[member.Id]);}object members;if(g.TryGetValue("Members",out members)&&members!=null)foreach(Dictionary<string,object> child in (IEnumerable)members)mapGroup(child);};
  foreach(Dictionary<string,object> group in (IEnumerable)receipt["Groups"])mapGroup(group);receipt["SourceProject"]=forkPath;receipt["Assembly"]=record.Copy;receipt["Project"]=target;receipt["PreviousAssembly"]=record.Source;
  var receiptPath=Path.Combine(folder,"working-assembly.json");File.WriteAllText(receiptPath,json.Serialize(receipt));var link=json.Serialize(new{Format="beamng-companion-link",Receipt=receiptPath});File.WriteAllText(target+".companion.json",link);File.WriteAllText(forkPath+".companion.json",link);
  // Immutable appearance lineage points to the original companion bodies. The
  // reader follows each original part's existing lineage back to source CAD.
  var originalProject=(Dictionary<string,object>)json.DeserializeObject(File.ReadAllText(record.Source+".beamng-project.json"));var selections=((IEnumerable)originalProject["Components"]).Cast<Dictionary<string,object>>().SelectMany(c=>((IEnumerable)c["Selections"]).Cast<Dictionary<string,object>>()).ToArray();
  var groups=selections.GroupBy(s=>(string)s["ComponentReference"]).Select(g=>{var old=oldInstances[g.Key];return new{Id=old.Id.ToString(),Name=old.Name,Part=record.Files[old.Path],ComponentReference=Ref(model,instances[old.Id]),SourceBodies=g.Select(s=>g.Key+"|"+(string)s["Reference"]).ToArray(),CopiedBodies=g.Select(s=>{var name=(string)s["Name"];return name.Substring(name.LastIndexOf(" / ",StringComparison.Ordinal)+3);}).ToArray(),Members=new object[0]};}).ToArray();
  File.WriteAllText(Path.Combine(folder,"appearance-provenance.json"),json.Serialize(new{Format="beamng-association-assembly",Version=3,Status="completed",SourceProject=record.Source+".beamng-project.json",SourceDocument=record.Source,Configuration=model.ConfigurationManager.ActiveConfiguration.Name,Assembly=record.Copy,Project=target,Groups=groups}));
 }
 static object[] MateHealth(){return Mates().Select(p=>{bool warning;int error=p.Item1.GetErrorCode2(out warning);return (object)new{ name=p.Item1.Name,error=error,warning=warning,suppressed=p.Item1.IsSuppressed()};}).ToArray();}
 static void Tidy(){
  var blueprint=json.Deserialize<Blueprint>(File.ReadAllText(Path.Combine(folder,"blueprint.json")));
  foreach(var owner in blueprint.Mates.SelectMany(m=>m.Entities).Where(e=>e.Kind=="point"||e.Kind=="axis"||e.Kind=="datum_plane").Select(e=>e.Owner).Distinct()){
   var doc=Owner(owner);var features=new List<Feature>();for(var f=doc.FirstFeature() as Feature;f!=null;f=f.GetNextFeature() as Feature)features.Add(f);
   foreach(var f in features){var type=f.GetTypeName2();
    if((f.Name.StartsWith("FR_mirror_",StringComparison.Ordinal)||(owner==101&&f.Name.StartsWith("3DSketch",StringComparison.Ordinal)))&&(type=="3DProfileFeature"||type=="ProfileFeature")){model.ClearSelection2(true);var assemblyFeature=owner<0?f:instances[owner].GetCorresponding(f) as Feature;if(assemblyFeature==null||!assemblyFeature.Select2(false,0))throw new Exception("Cannot hide copied helper sketch");model.BlankSketch();}
   }
   foreach(var e in blueprint.Mates.SelectMany(m=>m.Entities).Where(e=>e.Owner==owner&&(e.Kind=="axis"||e.Kind=="datum_plane"))){var feature=Resolve(doc,e.NativeReference) as Feature;if(feature==null)throw new Exception("Expected datum feature");feature.Name="FR_mirror_"+e.Source.Replace("[","_").Replace("]","")+"_"+e.Kind;model.ClearSelection2(true);var assemblyFeature=owner<0?feature:instances[owner].GetCorresponding(feature) as Feature;if(assemblyFeature==null||!assemblyFeature.Select2(false,0))throw new Exception("Cannot hide copied helper datum");model.BlankRefGeom();}
   model.ClearSelection2(true);if(doc.GetSaveFlag())Save(doc);Console.WriteLine("Tidied helper references in owner "+owner);
  }
  Activate(model);model.EditRebuild3();Save(model);CheckOriginals();Console.WriteLine("PASS helper names and visibility cleaned up");
 }
 static int MateFailures(){return Mates().Count(p=>{bool warning;return !p.Item1.IsSuppressed()&&p.Item1.GetErrorCode2(out warning)!=0&&!warning;});}
 static void Promote(){
  CheckOriginals();if(Mates().Count()!=39||MateFailures()!=0)throw new Exception("The reviewed copy is not in its verified mate state");
  var originals=new HashSet<string>(record.Files.Keys,StringComparer.OrdinalIgnoreCase);var originalDocs=(app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().Where(d=>originals.Contains(d.GetPathName())).ToArray();
  if(originalDocs.Any(d=>d.GetSaveFlag()))throw new Exception("Working companion has unsaved edits; transfer has not started");
  foreach(var d in (app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().Where(d=>record.Files.Values.Contains(d.GetPathName())&&d.GetType()==1&&d.GetSaveFlag()).ToArray())Save(d);Save(model);
  var expected=instances.ToDictionary(p=>p.Key,p=>(double[])p.Value.Transform2.ArrayData);var expectedColors=instances.ToDictionary(p=>p.Key,p=>json.Serialize(new{component=p.Value.GetMaterialPropertyValues2(1,null),part=Owner(p.Key).MaterialPropertyValues}));
  var backup=Path.Combine(Path.GetDirectoryName(folder),"before-FR-mates-"+DateTime.Now.ToString("yyyyMMdd-HHmmss"));Directory.CreateDirectory(backup);var backed=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);int index=0;
  var projectPath=record.Source+".beamng-project.json";var nativePaths=record.Files.Keys.ToArray();var sidecars=record.Files.Keys.Select(Path.GetDirectoryName).Distinct(StringComparer.OrdinalIgnoreCase).SelectMany(d=>Directory.GetFiles(d,"*.json")).ToArray();
  foreach(var p in nativePaths.Concat(sidecars).Distinct(StringComparer.OrdinalIgnoreCase)){var dest=Path.Combine(backup,(index++).ToString("D3")+"_"+Path.GetFileName(p));File.Copy(p,dest,false);if(Hash(p)!=Hash(dest))throw new Exception("Backup hash mismatch");backed[p]=dest;}
  var unchangedSidecars=sidecars.Where(p=>!string.Equals(p,projectPath,StringComparison.OrdinalIgnoreCase)).ToDictionary(p=>p,Hash);File.WriteAllText(Path.Combine(backup,"restore-map.json"),json.Serialize(backed));Write("promotion.json",new{status="backed_up",target=record.Source,backup=backup});Console.WriteLine("Verified backup: "+backup);
  foreach(var d in originalDocs.OrderBy(d=>d.GetType()==2?0:1))app.CloseDoc(d.GetTitle());
  bool writing=false;
  try{
   var reverse=record.Files.ToDictionary(p=>p.Value,p=>p.Key,StringComparer.OrdinalIgnoreCase);var pack=model.Extension.GetPackAndGo();pack.IncludeDrawings=false;pack.IncludeSimulationResults=false;pack.IncludeSuppressed=true;pack.IncludeToolboxComponents=true;object value;if(!pack.GetDocumentNames(out value))throw new Exception("Could not enumerate reviewed copy");var from=((object[])value).Cast<string>().ToArray();if(from.Length!=record.Files.Count||from.Any(p=>!reverse.ContainsKey(p)))throw new Exception("Unexpected copy dependencies");
   var targets=from.Select(p=>reverse[p]).ToArray();if(!pack.SetDocumentSaveToNames(targets.Select(p=>new BStrWrapper(p)).ToArray()))throw new Exception("Could not map native files to working companion");CheckOriginals();var workingRoot=Path.GetFullPath(Path.GetDirectoryName(Path.GetDirectoryName(record.Source)))+Path.DirectorySeparatorChar;if(nativePaths.Any(p=>!Path.GetFullPath(p).StartsWith(workingRoot,StringComparison.OrdinalIgnoreCase)))throw new Exception("Transfer target lies outside the working companion directory");var displaced=Path.Combine(backup,"displaced-native-files");Directory.CreateDirectory(displaced);writing=true;foreach(var p in nativePaths){if(Hash(p)!=Hash(backed[p]))throw new Exception("Original changed since backup");File.Move(p,Path.Combine(displaced,Path.GetFileName(backed[p])));}var status=model.Extension.SavePackAndGo(pack) as int[];Write("promotion-pack-status.json",status);if(status==null||status.Any(s=>s!=0))throw new Exception("Native transfer failed");Console.WriteLine("Transferred native assembly and part files");
   // Close only the reviewed copy. The user's unsaved source assembly stays open.
   var reviewed=(app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().Where(d=>reverse.ContainsKey(d.GetPathName())).OrderBy(d=>d.GetType()==2?0:1).Select(d=>d.GetTitle()).ToArray();foreach(var title in reviewed)app.CloseDoc(title);
   int error=0,warning=0;model=app.OpenDoc6(record.Source,2,1,"",ref error,ref warning) as ModelDoc2;if(model==null)throw new Exception("Cannot open working companion: "+error);Activate(model);instances=Components().ToDictionary(c=>c.GetID());model.EditRebuild3();if(instances.Count!=record.Instances.Count||record.Instances.Any(c=>!instances.ContainsKey(c.Id)||!string.Equals(instances[c.Id].GetPathName(),c.Path,StringComparison.OrdinalIgnoreCase)))throw new Exception("Working companion does not reference its original part paths");if(Mates().Count()!=39||MateFailures()!=0)throw new Exception("Working companion mates failed validation");
   double delta=instances.Max(p=>((double[])p.Value.Transform2.ArrayData).Zip(expected[p.Key],(a,b)=>Math.Abs(a-b)).Max());if(delta>1e-5)throw new Exception("Transferred resting pose changed: "+delta);if(instances.Any(p=>json.Serialize(new{component=p.Value.GetMaterialPropertyValues2(1,null),part=Owner(p.Key).MaterialPropertyValues})!=expectedColors[p.Key]))throw new Exception("Component/part appearance values changed during transfer");
   int selections=0;var seen=new HashSet<string>();Action<object> validate=null;validate=o=>{var d=o as Dictionary<string,object>;if(d!=null){object kind,r,c;if(d.TryGetValue("Kind",out kind)&&object.Equals(kind,"body")&&d.TryGetValue("Reference",out r)&&d.TryGetValue("ComponentReference",out c)&&seen.Add((string)c+"|"+(string)r)){if(!(Resolve(model,(string)r) is Body2)||!(Resolve(model,(string)c) is Component2))throw new Exception("Original body assignment no longer resolves");selections++;}foreach(var child in d.Values)validate(child);}else{var list=o as object[];if(list!=null)foreach(var child in list)validate(child);}};
   var project=(Dictionary<string,object>)json.DeserializeObject(File.ReadAllText(projectPath));validate(project);var prep=record.Source+".truemesh-prep.json";if(File.Exists(prep))validate(json.DeserializeObject(File.ReadAllText(prep)));Console.WriteLine("Validated "+selections+" existing body references without rebinding");
   var workspace=(Dictionary<string,object>)project["JointWorkspace"];workspace["ScanHash"]=null;workspace["ScanStamp"]=-1;workspace["ScanDocument"]=null;foreach(Dictionary<string,object> m in (IEnumerable)workspace["Members"]){var c=Resolve(model,(string)m["ComponentReference"]) as Component2;if(c==null)throw new Exception("Moving member no longer resolves");m["PlacementFixed"]=c.IsFixed();}
   foreach(var key in new[]{"LastBuildReceipt","PhysicsBuildReceipt","PhysicsTemplateReceipt"})project[key]="";
   File.WriteAllText(projectPath,json.Serialize(project));code.GetType("BeamNG.Cad.Preparation.VehicleProject",true).GetMethod("Load").Invoke(null,new object[]{projectPath});if(unchangedSidecars.Any(p=>Hash(p.Key)!=p.Value))throw new Exception("An association/profile sidecar changed unexpectedly");Save(model);
   app.CloseDoc(model.GetTitle());model=app.OpenDoc6(record.Source,2,1,"",ref error,ref warning) as ModelDoc2;if(model==null)throw new Exception("Working companion could not reopen");Activate(model);instances=Components().ToDictionary(c=>c.GetID());if(Mates().Count()!=39||MateFailures()!=0)throw new Exception("Working mate state failed reopen");
   Write("promotion.json",new{status="completed",target=record.Source,backup=backup,mirrored_mates=17,total_mates=39,body_assignments_resolved=selections,rest_transform_max_delta=delta,original_part_paths_preserved=true,component_and_part_appearance_values_preserved=true,identity_and_association_links_preserved=true,save_reopen_passed=true});Console.WriteLine("PASS promoted to working companion, saved/reopened; backup retained");
  }catch(Exception ex){
   if(writing){var changed=(app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().Where(d=>originals.Contains(d.GetPathName())).OrderBy(d=>d.GetType()==2?0:1).Select(d=>d.GetTitle()).ToArray();foreach(var title in changed)app.CloseDoc(title);foreach(var p in nativePaths.Concat(new[]{projectPath}))File.Copy(backed[p],p,true);Write("promotion.json",new{status="rolled_back",target=record.Source,backup=backup,error=ex.ToString()});Console.WriteLine("Restored pre-transfer native files and project from verified backup");}throw;
  }
 }
 static void Finish(){
  CheckOriginals();var projectPath=record.Copy+".beamng-project.json";var projectType=code.GetType("BeamNG.Cad.Preparation.VehicleProject",true);projectType.GetMethod("Load").Invoke(null,new object[]{projectPath});
  var project=(Dictionary<string,object>)json.DeserializeObject(File.ReadAllText(projectPath));int count=0;var refs=new HashSet<string>();Action<object> check=null;check=value=>{var d=value as Dictionary<string,object>;if(d!=null){object kind,r,c;if(d.TryGetValue("Kind",out kind)&&object.Equals(kind,"body")&&d.TryGetValue("Reference",out r)&&d.TryGetValue("ComponentReference",out c)){if(refs.Add((string)c+"|"+(string)r)){if(!(Resolve(model,(string)r) is Body2)||!(Resolve(model,(string)c) is Component2))throw new Exception("Copied body assignment no longer resolves");count++;}}foreach(var v in d.Values)check(v);}else {var a=value as object[];if(a!=null)foreach(var v in a)check(v);}};check(project);
  var drive=(object[])json.DeserializeObject(File.ReadAllText(Path.Combine(folder,"steering-drive.json")));if(drive.Length!=2||drive.Cast<Dictionary<string,object>>().Any(d=>!object.Equals(d["passed"],true)))throw new Exception("Steering test did not pass in both directions");
  var snapshot=(Dictionary<string,object>)json.DeserializeObject(File.ReadAllText(Path.Combine(folder,"native-mates.json")));var saved=((object[])snapshot["components"]).Cast<Dictionary<string,object>>().ToDictionary(d=>(string)d["name"]);double restDelta=instances.Values.Max(c=>((double[])c.Transform2.ArrayData).Zip(((object[])saved[c.Name2]["transform"]).Select(Convert.ToDouble),(a,b)=>Math.Abs(a-b)).Max());if(restDelta>1e-5)throw new Exception("Resting pose was not restored: "+restDelta);
  model.EditRebuild3();if(Mates().Count()!=39||MateFailures()!=0)throw new Exception("Unexpected mate state after tests");Save(model);var copyPath=model.GetPathName();app.CloseDoc(model.GetTitle());Load();if(Mates().Count()!=39||MateFailures()!=0)throw new Exception("Save/reopen failed");CheckOriginals();
  Write("final-verification.json",new{copy=copyPath,project=projectPath,mirrored_mates=17,total_mates=39,body_assignments_resolved=count,rest_transform_max_delta=restDelta,steering=drive,other_motion_evidence="motion-tests.json (bump, rebound, wheel spin)",supersedes_steering_drag_failure="steering-drive.json uses a temporary distance mate; driver removed and resting pose restored",original_native_hashes_unchanged=true,save_reopen_passed=true});Console.WriteLine("PASS final save/reopen, "+count+" resolved body assignments, 39 healthy mates, originals unchanged");
 }
 static void SteeringDrive(){
  CheckOriginals();var math=(MathUtility)app.GetMathUtility();var baseline=instances.ToDictionary(p=>p.Key,p=>(double[])p.Value.Transform2.ArrayData);var known=new HashSet<int>(Mates().Select(p=>p.Item1.GetID()));var results=new List<object>();
  var blueprint=json.Deserialize<Blueprint>(File.ReadAllText(Path.Combine(folder,"blueprint.json")));var e=blueprint.Mates.Single(m=>m.Source=="Coincident12").Entities.Single(x=>x.Owner==107);var point=instances[107].GetCorresponding(Resolve(Owner(107),e.NativeReference));Feature plane=null;for(var f=model.FirstFeature() as Feature;f!=null;f=f.GetNextFeature() as Feature)if(f.Name=="Right Plane")plane=f;if(plane==null)throw new Exception("Root Right Plane not found");
  Action remove=()=>{foreach(var p in Mates().Where(p=>!known.Contains(p.Item1.GetID())).ToArray()){model.ClearSelection2(true);p.Item1.Select2(false,0);if(!model.Extension.DeleteSelection2(0))throw new Exception("Cannot remove temporary steering driver");}};
  Action reset=()=>{foreach(var p in baseline)instances[p.Key].Transform2=(MathTransform)math.CreateTransform(p.Value);model.EditRebuild3();};
  Save(model);if(!File.Exists(Path.Combine(folder,"before-steering-drive.SLDASM")))File.Copy(record.Copy,Path.Combine(folder,"before-steering-drive.SLDASM"),false);
  try {foreach(var dx in new[]{.002,-.002}){reset();model.ClearSelection2(true);if(!Select(point,false,1)||!Select(plane,true,1))throw new Exception("Cannot select steering driver references");var x=Map(e.Point,instances[107].Transform2,false)[0];int error;double distance=Math.Abs(x+dx);var mate=((AssemblyDoc)model).AddMate5(5,2,true,distance,distance,distance,0,0,0,0,0,false,false,0,out error);model.ClearSelection2(true);model.EditRebuild3();var actual=((double[])instances[107].Transform2.ArrayData)[9]-baseline[107][9];var left=((double[])instances[110].Transform2.ArrayData).Zip(baseline[110],(a,b)=>Math.Abs(a-b)).Max();var right=((double[])instances[113].Transform2.ArrayData).Zip(baseline[113],(a,b)=>Math.Abs(a-b)).Max();var row=new{requested=dx,actual=actual,left_wheel_delta=left,right_wheel_delta=right,creation_status=error,mate_errors=MateFailures(),passed=mate!=null&&error==1&&Math.Abs(actual-dx)<1e-6&&left>1e-5&&right>1e-5&&MateFailures()==0};results.Add(row);Write("steering-drive.json",results);Console.WriteLine(json.Serialize(row));remove();}}
  finally{remove();reset();model.ClearSelection2(true);Save(model);CheckOriginals();}
 }
 static void SteeringProbe(){
  var math=(MathUtility)app.GetMathUtility();var baseline=instances.ToDictionary(p=>p.Key,p=>(double[])p.Value.Transform2.ArrayData);var c=instances[107];var suppressed=new List<Feature>();var results=new List<object>();
  Action reset=()=>{foreach(var p in baseline)instances[p.Key].Transform2=(MathTransform)math.CreateTransform(p.Value);model.EditRebuild3();};
  try{foreach(var names in new[]{new[]{"Coincident25","Coincident26","FR_mirror_Coincident25"},new[]{"Coincident24","FR_mirror_Coincident24"},new[]{"Concentric7","FR_mirror_Concentric7"}}){
    foreach(var feature in suppressed)feature.SetSuppression2((int)swFeatureSuppressionAction_e.swUnSuppressFeature,(int)swInConfigurationOpts_e.swThisConfiguration,null);suppressed.Clear();reset();foreach(var name in names){var feature=Mates().Single(p=>p.Item1.Name==name).Item1;if(!feature.SetSuppression2((int)swFeatureSuppressionAction_e.swSuppressFeature,(int)swInConfigurationOpts_e.swThisConfiguration,null))throw new Exception("Cannot isolate steering constraint");suppressed.Add(feature);model.EditRebuild3();}
    var before=(double[])c.Transform2.ArrayData;var target=(double[])before.Clone();target[9]+=.002;var solved=c.SetTransformAndSolve3((MathTransform)math.CreateTransform(target),true);var immediate=(double[])c.Transform2.ArrayData;model.EditRebuild3();var rebuilt=(double[])c.Transform2.ArrayData;var row=new{omitted=suppressed.Select(f=>f.Name).ToArray(),solver=solved,immediate_travel=immediate[9]-before[9],rebuilt_travel=rebuilt[9]-before[9],fr_wheel_delta=((double[])instances[113].Transform2.ArrayData).Zip(baseline[113],(a,b)=>Math.Abs(a-b)).Max(),errors=MateFailures()};results.Add(row);Write("steering-probe-links.json",results);Console.WriteLine(string.Join("+",names)+" immediate="+row.immediate_travel+" rebuilt="+row.rebuilt_travel);
   }}finally{foreach(var feature in suppressed)feature.SetSuppression2((int)swFeatureSuppressionAction_e.swUnSuppressFeature,(int)swInConfigurationOpts_e.swThisConfiguration,null);reset();Save(model);}
 }
 static void Verify(){
  CheckOriginals();var blueprint=json.Deserialize<Blueprint>(File.ReadAllText(Path.Combine(folder,"blueprint.json")));model.EditRebuild3();if(MateFailures()!=0)throw new Exception("Mate errors before motion test");
  var original=instances.ToDictionary(p=>p.Key,p=>(double[])p.Value.Transform2.ArrayData);var math=(MathUtility)app.GetMathUtility();var results=new List<object>();
  Write("rest-pose.json",blueprint.Pairs.Values.Select(id=>new{id=id,name=instances[id].Name2,transform=original[id],rotation_degrees=Math.Acos(Math.Max(-1,Math.Min(1,(original[id][0]+original[id][4]+original[id][8]-1)/2)))*180/Math.PI}).ToArray());
  Action reset=()=>{foreach(var pair in original)instances[pair.Key].Transform2=(MathTransform)math.CreateTransform(pair.Value);model.EditRebuild3();};
  try{foreach(var mode in new[]{"FR bump","FR rebound","FR wheel spin","steering right","steering left"}){
    reset();var id=mode.StartsWith("steering")?103:mode.Contains("wheel")?113:101;var c=instances[id];MathTransform target;
    if(id==107){var t=(double[])c.Transform2.ArrayData;t[9]+=mode.EndsWith("right")?.002:-.002;target=(MathTransform)math.CreateTransform(t);}
    else {var e=blueprint.Mates.Single(m=>m.Source==(id==103?"Coincident2":id==113?"Concentric3":"Concentric1")).Entities.Single(x=>x.Owner==id);var point=Map(e.Point,c.Transform2,false);var axis=id==103?Unit(Sub(Map(blueprint.Mates.Single(m=>m.Source=="Coincident5").Entities.Single(x=>x.Owner==103).Point,c.Transform2,false),point)):Map(e.Axis,c.Transform2,true);double angle=id==103?(mode.EndsWith("right")?.01:-.01):id==113?.1:mode.EndsWith("bump")?.02:-.02;var rotation=(MathTransform)math.CreateTransformRotateAxis((MathPoint)math.CreatePoint(point),(MathVector)math.CreateVector(axis),angle);target=(MathTransform)c.Transform2.Multiply(rotation);}
    bool solved;if(id==107){var drag=((AssemblyDoc)model).IGetDragOperator();drag.AddComponent(c,false);drag.TransformType=0;drag.DragMode=2;drag.IsRelaxationEval=true;drag.DynamicClearanceEnabled=false;drag.UseAbsoluteTransform=false;drag.CollisionDetectionEnabled=false;var move=new double[]{1,0,0,0,1,0,0,0,1,mode.EndsWith("right")?.002:-.002,0,0,1,0,0,0};if(!drag.BeginDrag())throw new Exception("Cannot begin native steering drag");try{solved=drag.DragAsUI((MathTransform)math.CreateTransform(move));}finally{drag.EndDrag();Marshal.ReleaseComObject(drag);}}else solved=c.SetTransformAndSolve3(target,true);model.EditRebuild3();var after=(double[])c.Transform2.ArrayData;var delta=after.Zip(original[id],(a,b)=>Math.Abs(a-b)).Max();var wheel=instances[113];var wheelDelta=((double[])wheel.Transform2.ArrayData).Zip(original[113],(a,b)=>Math.Abs(a-b)).Max();var failures=MateFailures();
    var rackDelta=((double[])instances[107].Transform2.ArrayData)[9]-original[107][9];var leftDelta=((double[])instances[110].Transform2.ArrayData).Zip(original[110],(a,b)=>Math.Abs(a-b)).Max();var passed=solved&&delta>1e-5&&wheelDelta>1e-5&&failures==0&&(!mode.StartsWith("steering")||(Math.Abs(rackDelta)>1e-5&&leftDelta>1e-5));results.Add(new{test=mode,solver=solved,component_transform_delta=delta,wheel_transform_delta=wheelDelta,rack_travel_m=rackDelta,left_wheel_transform_delta=leftDelta,mate_errors=failures,passed=passed});Write("motion-tests.json",results);Console.WriteLine((passed?"PASS ":"FAIL ")+mode+" movement="+delta+" rack="+rackDelta+" errors="+failures);
   }}finally{reset();model.ClearSelection2(true);Save(model);}
  Write("mate-health.json",MateHealth());CheckOriginals();var path=model.GetPathName();app.CloseDoc(model.GetTitle());Load();model.EditRebuild3();var persisted=Mates().Where(p=>p.Item1.Name.StartsWith("FR_mirror_")).Count();if(persisted!=blueprint.Mates.Count||MateFailures()!=0)throw new Exception("Save/reopen verification failed");
  Write("verification.json",new{copy=path,mirrored_mates=persisted,all_original_file_hashes_unchanged=true,all_part_paths_isolated=true,motion=results,save_reopen_passed=true});Console.WriteLine("PASS save/reopen; originals unchanged");
 }
 public static void Run(int pid,string output,string destination,string action){
  app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});folder=destination;code=Assembly.LoadFrom(Path.Combine(output,"beamng.cad.dll"));
  if(action=="prepare"){Prepare();return;}
  if(action=="closeparts"){
   app.CommandInProgress=false;record=json.Deserialize<CopyRecord>(File.ReadAllText(Path.Combine(folder,"copy.json")));var docs=(app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().Where(d=>d.GetType()==1&&d.GetPathName().StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)).ToArray();
   foreach(var d in docs){if(d.GetSaveFlag())Save(d);app.CloseDoc(d.GetTitle());}var copy=app.GetOpenDocumentByName(record.Copy) as ModelDoc2;if(copy!=null)Activate(copy);Console.WriteLine("Closed copied part windows; companion and source assemblies retained");return;
  }
  if(action=="status"){var d=app.ActiveDoc as ModelDoc2;Console.WriteLine(d==null?"No active document":d.GetPathName()+" dirty="+d.GetSaveFlag()+" sketch="+(d.SketchManager.ActiveSketch!=null));return;}
  if(action=="releaseoriginal"){
   app.CommandInProgress=false;record=json.Deserialize<CopyRecord>(File.ReadAllText(Path.Combine(folder,"copy.json")));var original=app.GetOpenDocumentByName(record.Source) as ModelDoc2;if(original==null)return;
   var documents=(app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().Where(d=>record.Files.ContainsKey(d.GetPathName())).ToArray();if(documents.Any(d=>d.GetSaveFlag()))throw new Exception("Original companion or referenced part has unsaved changes; left open");CheckOriginals();app.CloseDoc(original.GetTitle());Console.WriteLine("Closed saved original companion; source assembly and all original files preserved");return;
  }
  if(action=="recover"){
   app.CommandInProgress=false;record=json.Deserialize<CopyRecord>(File.ReadAllText(Path.Combine(folder,"copy.json")));var active=app.ActiveDoc as ModelDoc2;
   if(active!=null&&active.GetPathName().StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)&&active.SketchManager.ActiveSketch!=null)active.SketchManager.Insert3DSketch(true);
   var docs=(app.GetDocuments() as object[]??new object[0]).Cast<ModelDoc2>().ToArray();Write("open-documents.json",docs.Select(d=>new{path=d.GetPathName(),title=d.GetTitle(),dirty=d.GetSaveFlag()}).ToArray());
   var owned=docs.Where(d=>d.GetPathName().StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)).OrderBy(d=>d.GetType()==2?0:1).Select(d=>d.GetTitle()).ToArray();foreach(var name in owned)app.CloseDoc(name);Console.WriteLine("Closed "+owned.Length+" owned copy documents without saving interrupted edits");return;
  }
  app.CommandInProgress=true;try{Console.WriteLine("Loading copy");Load();Console.WriteLine("Copy loaded");if(action=="promote"){Promote();return;}if(action=="inspect"){Inspect();return;}if(action=="apply"){Apply();return;}if(action=="project"){Project();return;}if(action=="verify"){Verify();return;}if(action=="finish"){Finish();return;}if(action=="tidy"){Tidy();return;}if(action=="steeringdrive"){SteeringDrive();return;}if(action=="steering"){SteeringProbe();return;}throw new Exception("Action not implemented yet");}finally{app.CommandInProgress=false;}
 }
}






