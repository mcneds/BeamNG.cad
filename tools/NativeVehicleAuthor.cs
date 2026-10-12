
// Compiled by Author-NativeVehicle.ps1 with the existing owned-CAD helper.
public static class NativeVehicleAuthor {
 sealed class CadContext : System.Threading.SynchronizationContext {
  readonly System.Collections.Concurrent.ConcurrentQueue<Action> queue=new System.Collections.Concurrent.ConcurrentQueue<Action>();
  public override void Post(System.Threading.SendOrPostCallback action,object state){queue.Enqueue(()=>action(state));}
  public void Drain(){Action action;while(queue.TryDequeue(out action)){SetSynchronizationContext(this);action();}}
 }
 static readonly JavaScriptSerializer Json=new JavaScriptSerializer {MaxJsonLength=int.MaxValue};
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Set(object o,string n,object value){o.GetType().GetField(n).SetValue(o,value);}
 static object Call(object o,string n,params object[] args){return o.GetType().GetMethod(n).Invoke(o,args);}
 static object Create(Assembly code,string type,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+type),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,args,null);}
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine(label);}
 static object Wait(object value){var task=(System.Threading.Tasks.Task)value;var context=(CadContext)System.Threading.SynchronizationContext.Current;while(!task.IsCompleted){context.Drain();Application.DoEvents();System.Threading.SynchronizationContext.SetSynchronizationContext(context);System.Threading.Thread.Sleep(10);}task.GetAwaiter().GetResult();return task.GetType().GetProperty("Result").GetValue(task,null);}
 static void Save(ModelDoc2 doc){int e=0,w=0;Check(doc.Save3(1,ref e,ref w),"Saved "+doc.GetTitle()+" code="+e);}
 static Dictionary<string,object> Read(string path){return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));}
 static IEnumerable<Dictionary<string,object>> Rows(object value){return ((IEnumerable)value).Cast<Dictionary<string,object>>();}
 static IList ListLike(IList input,IEnumerable<object> values){var result=(IList)Activator.CreateInstance(input.GetType());foreach(var value in values)result.Add(value);return result;}
 static double[] Vec(object value){return ((IEnumerable)value).Cast<object>().Select(Convert.ToDouble).ToArray();}
 static object Resolve(ModelDoc2 doc,string reference){int state;var value=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out state);if(value==null||state!=0)throw new Exception("Native reference unavailable");return value;}
 static object Load(Assembly code,string path){return code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Load").Invoke(null,new object[]{path});}
 static void Activate(ISldWorks app,ModelDoc2 doc){int error=0;app.ActivateDoc3(doc.GetTitle(),false,0,ref error);}
 static ModelDoc2 Open(ISldWorks app,string path){int e=0,w=0;var doc=(ModelDoc2)app.OpenDoc6(path,2,1,"",ref e,ref w);Check(doc!=null,"Opened native assembly "+path+" code="+e);Activate(app,doc);return doc;}
 static object Assignment(Assembly code,object owner,IList refs){var a=Create(code,"Preparation.FrameAssignment");Set(a,"Configuration",Get(owner,"Configuration"));Set(a,"Selections",refs);Set(a,"Hull",Get(owner,"Hull"));return a;}
 static IEnumerable<Feature> Children(Feature parent){for(var f=parent.GetFirstSubFeature() as Feature;f!=null;f=f.GetNextSubFeature() as Feature){yield return f;foreach(var child in Children(f))yield return child;}}
 static IEnumerable<Feature> MateFeatures(ModelDoc2 doc){for(var f=doc.FirstFeature() as Feature;f!=null;f=f.GetNextFeature() as Feature)if(f.GetTypeName2()=="MateGroup")foreach(var child in Children(f))yield return child;}
 static Feature Named(ModelDoc2 doc,string name){
  // Native lookup avoids walking every component's bodies and sketch features
  // over the out-of-process COM boundary for each new fixture mate.
  var part=doc as PartDoc;if(part!=null)return part.FeatureByName(name) as Feature;
  var assembly=doc as AssemblyDoc;return assembly==null?null:assembly.FeatureByName(name) as Feature;
 }
 static Component2 Instance(ModelDoc2 doc,object project,string owner,string member){
  if(member!=null){var m=((IList)Get(Get(project,"JointWorkspace"),"Members")).Cast<object>().Single(x=>(string)Get(x,"ComponentId")==owner&&(string)Get(x,"Kind")==member);return (Component2)Resolve(doc,(string)Get(m,"ComponentReference"));}
  var group=((IList)Get(project,"Components")).Cast<object>().Single(c=>(string)Get(c,"Id")==owner);
  return (Component2)Resolve(doc,(string)Get(((IList)Get(group,"Selections"))[0],"ComponentReference"));
 }
 static string Member(Dictionary<string,object> row,string key="member"){return row.ContainsKey(key)?row[key] as string:null;}
 static bool SelectNative(object entity,SelectData data){
  var point=entity as SketchPoint;if(point!=null)return point.Select4(true,data);
  var geometry=entity as Entity;if(geometry!=null)return geometry.Select4(true,data);
  var feature=entity as Feature;return feature!=null&&feature.Select2(true,data.Mark);
 }
 static void Scan(Assembly code,ISldWorks app,ModelDoc2 doc,object project){
  var scanner=Create(code,"Preparation.NativeMateScanner",app,doc,project);var w=Get(project,"JointWorkspace");
  Set(w,"Mates",Wait(Call(scanner,"Capture",(Action<string>)(s=>Console.WriteLine(s)),System.Threading.CancellationToken.None)));
  Set(w,"ScanStamp",doc.GetUpdateStamp());Set(w,"ScanDocument",doc.GetPathName());Set(w,"ScanConfiguration",doc.ConfigurationManager.ActiveConfiguration.Name);Call(project,"Save");
 }
 public static void CopyProbe(object application,string dll,string sourceProject,string folder,string owner){
  var app=(ISldWorks)application;app.UserControl=true;app.Visible=true;app.CommandInProgress=false;
  System.Threading.SynchronizationContext.SetSynchronizationContext(new CadContext());var code=Assembly.LoadFrom(dll);
  var project=Load(code,sourceProject);var source=Open(app,(string)Get(project,"SourceDocument"));
  project=Call(project,"Fork",Path.Combine(folder,"probe-project.json"));
  var groups=(IList)Get(project,"Components");Set(project,"Components",ListLike(groups,groups.Cast<object>().Where(c=>(string)Get(c,"Id")==owner)));Call(project,"Save");
  var result=Wait(Call(Create(code,"Preparation.AssociationAssembly",app,source),"Create",project,Path.Combine(folder,"working"),(Action<int,string>)((i,s)=>Console.WriteLine(i+"% "+s)),System.Threading.CancellationToken.None));
  var doc=(ModelDoc2)Get(result,"Document");Check(((IList)Get(Get(result,"Project"),"Components")).Count==1,"Focused companion copy completed");
  File.WriteAllText(Path.Combine(folder,"result.json"),Json.Serialize(new{status="passed",component=owner,assembly=doc.GetPathName()}));app.CommandInProgress=false;
 }
 public static void Run(object application,string dll,string sourceProject,string planPath,string folder,bool resume){
  var app=(ISldWorks)application;app.UserControl=true;app.Visible=true;app.CommandInProgress=false;
  System.Threading.SynchronizationContext.SetSynchronizationContext(new CadContext());var code=Assembly.LoadFrom(dll);var plan=Read(planPath);
  var checkpoint=Path.Combine(folder,"companion.json");ModelDoc2 doc;object project;string receipt;string stage="split";
  if(resume){var state=Read(checkpoint);stage=state.ContainsKey("stage")?(string)state["stage"]:"mates";Check(File.ReadAllText(planPath)==File.ReadAllText(Path.Combine(folder,"authoring.json")),"Unchanged native authoring recipe");project=Load(code,(string)state["project"]);doc=Open(app,(string)Get(project,"SourceDocument"));receipt=(string)state["receipt"];}
  else{
   File.Copy(planPath,Path.Combine(folder,"authoring.json"));project=Load(code,sourceProject);var source=Open(app,(string)Get(project,"SourceDocument"));
   var original=File.ReadAllText(sourceProject);project=Call(project,"Fork",Path.Combine(folder,"source-snapshot.json"));
   foreach(var component in (IList)Get(project,"Components")){
    var geometry=Path.Combine((string)Get(component,"GeometryDirectory"),"geometry.json");var package=Read(geometry);
    var assignment=(Dictionary<string,object>)package["Assignment"];
    Set(component,"Hull",Json.Deserialize(Json.Serialize(assignment["Hull"]),Get(component,"Hull").GetType()));
   }
   Call(project,"Save");
   var result=Wait(Call(Create(code,"Preparation.AssociationAssembly",app,source),"Create",project,Path.Combine(folder,"working"),(Action<int,string>)((i,s)=>Console.WriteLine(i+"% "+s)),System.Threading.CancellationToken.None));
   doc=(ModelDoc2)Get(result,"Document");project=Get(result,"Project");receipt=(string)Get(result,"ReceiptPath");
   var saved=Read(receipt);var selector=Create(code,"Preparation.FrameSelection",app,doc,true);
   foreach(var owner in (Dictionary<string,object>)plan["members"]){
    var group=((IList)Get(project,"Components")).Cast<object>().Single(c=>(string)Get(c,"Id")==owner.Key);
    var groupReceipt=Rows(saved["Groups"]).Single(g=>(string)g["Id"]==owner.Key);
    var sourceBodies=((IEnumerable)groupReceipt["SourceBodies"]).Cast<string>().ToArray();var copiedBodies=((IEnumerable)groupReceipt["CopiedBodies"]).Cast<string>().ToArray();
    var byIndex=new Dictionary<int,object>();
    foreach(var reference in (IList)Get(group,"Selections")){
     var body=(Body2)Resolve(doc,(string)Get(reference,"Reference"));var at=Array.IndexOf(copiedBodies,body.Name);
     var sourceInstance=(Component2)Resolve(source,sourceBodies[at].Split('|')[0]);var file=Path.GetFileNameWithoutExtension(sourceInstance.GetPathName());
     byIndex.Add(int.Parse(file.Substring(owner.Key.Length+1)),reference);
    }
    foreach(var part in (Dictionary<string,object>)owner.Value){
     var refs=ListLike((IList)Get(group,"Selections"),((IEnumerable)part.Value).Cast<object>().Select(x=>byIndex[Convert.ToInt32(x)]));
     var m=Create(code,"Preparation.MovingMember");Set(m,"Id",owner.Key+"_"+part.Key);Set(m,"ComponentId",owner.Key);Set(m,"Kind",part.Key);Set(m,"Name",owner.Key+" "+part.Key);
     Set(m,"Selections",refs);Set(m,"BodyIds",Call(selector,"BodyIds",Assignment(code,group,refs)));((IList)Get(Get(project,"JointWorkspace"),"Members")).Add(m);
    }
    if(owner.Key.EndsWith("_spring_damper"))foreach(var piece in new[]{"housing","shaft","spring"}){
     int index=piece=="housing"?0:piece=="shaft"?1:2;var refs=ListLike((IList)Get(group,"Selections"),new[]{byIndex[index]});var a=Assignment(code,group,refs);
     code.GetType("BeamNG.Cad.Preparation.CoiloverAppearance").GetMethod("Assign").Invoke(null,new[]{group,piece,a,Call(selector,"BodyIds",a),doc.GetPathName()});
    }
   }
   Call(project,"Save");Save(doc);
   Check(File.ReadAllText(sourceProject)==original,"Source CAD assignments unchanged");Activate(app,doc);app.CloseDoc(source.GetTitle());
   File.WriteAllText(checkpoint,Json.Serialize(new{project=doc.GetPathName()+".beamng-project.json",receipt=receipt,stage="split"}));
  }
  if(stage=="split"){
   foreach(var owner in (Dictionary<string,object>)plan["members"]){
    if(((IList)Get(Get(project,"JointWorkspace"),"Members")).Cast<object>().Where(m=>(string)Get(m,"ComponentId")==owner.Key).All(m=>!string.IsNullOrEmpty((string)Get(m,"Part"))))continue;
    var previous=doc;
    var result=Wait(Call(Create(code,"Preparation.AssociationAssembly",app,doc),"SplitMembers",project,receipt,owner.Key,(Action<int,string>)((i,s)=>Console.WriteLine(owner.Key+" "+i+"% "+s)),System.Threading.CancellationToken.None));
    doc=(ModelDoc2)Get(result,"Document");project=Get(result,"Project");
    File.WriteAllText(checkpoint,Json.Serialize(new{project=doc.GetPathName()+".beamng-project.json",receipt=receipt,stage="split"}));
    Activate(app,doc);Application.DoEvents();app.CloseDoc(previous.GetTitle());Application.DoEvents();
   }
   File.WriteAllText(checkpoint,Json.Serialize(new{project=doc.GetPathName()+".beamng-project.json",receipt=receipt,stage="mates"}));
  }
  // A focused lifecycle regression repeats every production copy/split/close
  // from a fresh source. It deliberately produces no mate or physics evidence.
  if(plan.ContainsKey("preparation_only")&&(bool)plan["preparation_only"]){
   Save(doc);var preparedPath=doc.GetPathName();app.CloseDoc(doc.GetTitle());doc=Open(app,preparedPath);project=Load(code,preparedPath+".beamng-project.json");
   var savedGroups=(IList)Get(project,"Components");var savedMembers=(IList)Get(Get(project,"JointWorkspace"),"Members");
   foreach(var group in savedGroups)foreach(var reference in (IList)Get(group,"Selections")){
    Resolve(doc,(string)Get(reference,"Reference"));if((string)Get(reference,"Kind")=="body")Resolve(doc,(string)Get(reference,"ComponentReference"));
   }
   foreach(var member in savedMembers){Check(!string.IsNullOrEmpty((string)Get(member,"Part")),"Member retained: "+Get(member,"Id"));Resolve(doc,(string)Get(member,"ComponentReference"));}
   File.WriteAllText(Path.Combine(folder,"result.json"),Json.Serialize(new{status="native_preparation_completed",project=preparedPath+".beamng-project.json",groups=savedGroups.Count,members=savedMembers.Count}));
   app.CommandInProgress=false;Save(doc);app.CloseDoc(doc.GetTitle());Application.DoEvents();return;
  }
  var groups=((IList)Get(project,"Components")).Cast<object>().ToDictionary(c=>(string)Get(c,"Id"));
  var pointReferences=new Dictionary<string,string>();
  var datumCache=Path.Combine(folder,"point-references.json");
  if(File.Exists(datumCache)){
   var cached=Read(datumCache);Check((string)cached["assembly"]==doc.GetPathName(),"Datum checkpoint belongs to current companion");
   foreach(var pair in (Dictionary<string,object>)cached["points"])pointReferences.Add(pair.Key,(string)pair.Value);
   Check(pointReferences.Keys.OrderBy(k=>k).SequenceEqual(Rows(plan["datums"]).Select(d=>(string)d["id"]).OrderBy(k=>k)),"Datum checkpoint covers unchanged plan");
   foreach(var reference in pointReferences.Values)Resolve(doc,reference);
  }else{
  foreach(var set in Rows(plan["datums"]).GroupBy(d=>(string)d["owner"]+"|"+(Member(d)??""))){
   var first=set.First();var instance=Instance(doc,project,(string)first["owner"],Member(first));int partError=0,partWarning=0;
   var part=(ModelDoc2)app.OpenDoc6(instance.GetPathName(),1,1,"",ref partError,ref partWarning);Check(part!=null,"Opened member datums "+set.Key);Activate(app,part);
   var nativePoints=new Dictionary<string,SketchPoint>();
   foreach(var datum in set){
    var id=(string)datum["id"];var name="CAD_"+id;var feature=Named(part,name);SketchPoint point;
    if(feature!=null)point=((object[])((Sketch)feature.GetSpecificFeature2()).GetSketchPoints2()).Cast<SketchPoint>().Single();
    else{
     var p=Vec(datum["position"]);part.ClearSelection2(true);part.SketchManager.Insert3DSketch(true);var sketch=(Sketch)part.GetActiveSketch2();
     point=part.SketchManager.CreatePoint(p[0],p[2],-p[1]);feature=(Feature)sketch;part.SketchManager.Insert3DSketch(true);feature.Name=name;
    }
    nativePoints[id]=point;
   }
   Save(part);Activate(app,doc);
   foreach(var pair in nativePoints){
    var entity=instance.GetCorresponding(pair.Value);Check(entity!=null,"Native assembly datum "+pair.Key);
    pointReferences[pair.Key]=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(entity));
   }
   app.CloseDoc(part.GetTitle());Activate(app,doc);
  }
  Save(doc);File.WriteAllText(datumCache,Json.Serialize(new{assembly=doc.GetPathName(),points=pointReferences}));
  }
  var pointManager=(SelectionMgr)doc.SelectionManager;var pointData=pointManager.CreateSelectData();pointData.Mark=42;
  doc.ClearSelection2(true);var preservedPoint=Resolve(doc,pointReferences.First().Value);
  Check(SelectNative(preservedPoint,pointData),"Select native datum for restoration check");
  using((IDisposable)Create(code,"Preparation.SelectionSnapshot",doc))doc.ClearSelection2(true);
  Check(pointManager.GetSelectedObjectCount2(-1)==1&&pointManager.GetSelectedObjectMark(1)==42&&app.IsSame(pointManager.GetSelectedObject6(1,-1),preservedPoint)==(int)swObjectEquality.swObjectSame,"Native sketch point and selection mark survive restoration");doc.ClearSelection2(true);
  // Float each non-frame member; SolidWorks solves the real geometric mates.
  foreach(var instance in ((object[])((AssemblyDoc)doc).GetComponents(true)).Cast<Component2>()){
   if(app.IsSame(instance,Instance(doc,project,"frame",null))==(int)swObjectEquality.swObjectSame)continue;
   doc.ClearSelection2(true);instance.Select4(false,null,false);((AssemblyDoc)doc).UnfixComponent();
  }
  var manager=(SelectionMgr)doc.SelectionManager;var selectData=manager.CreateSelectData();selectData.Mark=1;
  foreach(var mate in Rows(plan["mates"])){
   var name=(string)mate["name"];var type=(string)mate["type"];
   int count=type=="planes"?3:1;
   for(int index=0;index<count;index++){
    var featureName=name+(type=="planes"?"_plane"+index:"");if(Named(doc,featureName)!=null)continue;
    doc.ClearSelection2(true);var entities=new List<object>();
    if(type=="point")entities.AddRange(new[]{Resolve(doc,pointReferences[(string)mate["a"]]),Resolve(doc,pointReferences[(string)mate["b"]])});
    else if(type=="concentric"){
     foreach(var key in new[]{"member_a","member_b"}){
      var instance=Instance(doc,project,(string)mate["owner"],(string)mate[key]);object info;
      var face=((object[])instance.GetBodies3(0,out info)).Cast<Body2>().SelectMany(b=>((object[])b.GetFaces()).Cast<Face2>()).Where(f=>((Surface)f.GetSurface()).IsCylinder()).OrderByDescending(f=>f.GetArea()).First();entities.Add(face);
     }
    }else{
     foreach(var instance in new[]{Instance(doc,project,"frame",null),Instance(doc,project,(string)mate["owner"],Member(mate))}){
      var part=(ModelDoc2)instance.GetModelDoc2();var plane=Named(part,new[]{"Front Plane","Top Plane","Right Plane"}[index]);entities.Add(instance.GetCorresponding(plane));
     }
    }
    foreach(var entity in entities)Check(entity!=null&&SelectNative(entity,selectData),"Selected geometry for "+featureName);
    int error;var created=((AssemblyDoc)doc).AddMate5((int)(type=="concentric"?swMateType_e.swMateCONCENTRIC:swMateType_e.swMateCOINCIDENT),0,false,0,0,0,0,0,0,0,0,false,type=="concentric"&&(string)mate["expected"]=="prismatic",0,out error);
    Check(created!=null&&error==(int)swAddMateError_e.swAddMateError_NoError,"Native mate "+featureName+" status="+error);
    var nativeFeature=MateFeatures(doc).First(f=>{var mateObject=f.GetSpecificFeature2();return mateObject is Mate2&&app.IsSame(mateObject,created)==(int)swObjectEquality.swObjectSame;});nativeFeature.Name=featureName;
   }
  }
  doc.EditRebuild3();Save(doc);
  var anchors=(IList)Get(project,"Anchors");anchors.Clear();var capture=Create(code,"Preparation.MountAnchors",app,doc);
  foreach(var d in Rows(plan["datums"])){
   var id=(string)d["id"];doc.ClearSelection2(true);Check(SelectNative(Resolve(doc,pointReferences[id]),manager.CreateSelectData()),"Selected captured datum "+id);
   var anchor=Call(capture,"Capture",groups[(string)d["owner"]],id);Set(anchor,"Id",id);anchors.Add(anchor);
  }
  var w=Get(project,"JointWorkspace");var bindings=(IList)Get(w,"Bindings");bindings.Clear();
  foreach(var b in Rows(plan["bindings"])){var v=Create(code,"Preparation.HardpointBinding");Set(v,"Request",b["request"]);Set(v,"ComponentId",b["owner"]);Set(v,"AnchorId",b["datum"]);bindings.Add(v);}
  var connections=(IList)Get(project,"Connections");connections.Clear();
  foreach(var c in Rows(plan["connections"])){var v=Create(code,"Preparation.MountConnection");Set(v,"Id",c["id"]);Set(v,"Name",c["id"]);Set(v,"AnchorA",c["a"]);Set(v,"AnchorB",c["b"]);Set(v,"Template",c["kind"]);Set(v,"ReleaseSet",c["release_set"]);Set(v,"Strength",Convert.ToDouble(c["strength"]));Set(v,"AttachmentLength",.006);connections.Add(v);}
  // Every physical/member/appearance input is exported from this exact assembly.
  var export=Create(code,"Preparation.FrameSelection",app,doc,true);
  var exported=0;
  foreach(var group in groups.Values){
   var owner=(string)Get(group,"Id");Console.WriteLine("Native CAD export "+(++exported)+"/"+groups.Count+": "+owner);
   var path=Path.Combine(folder,"cad-inputs",owner);Call(export,"Export",Assignment(code,group,(IList)Get(group,"Selections")),path);Set(group,"GeometryDirectory",path);
   foreach(var member in ((IList)Get(w,"Members")).Cast<object>().Where(m=>(string)Get(m,"ComponentId")==owner)){
    Console.WriteLine("Native member export: "+Get(member,"Id"));path=Path.Combine(folder,"member-inputs",(string)Get(member,"Id"));Call(export,"Export",Assignment(code,group,(IList)Get(member,"Selections")),path);Set(member,"GeometryDirectory",path);Set(member,"PlacementFixed",false);
   }
   var appearance=Get(group,"AppearanceCoilover");if(appearance!=null)foreach(var piece in (IList)Get(appearance,"Pieces")){
    path=Path.Combine(folder,"coilover-inputs",owner,(string)Get(piece,"Kind"));Call(export,"Export",Assignment(code,group,(IList)Get(piece,"Selections")),path);Set(piece,"GeometryDirectory",path);
   }
  }
  Call(project,"Save");Scan(code,app,doc,project);File.Copy(doc.GetPathName()+".beamng-project.json",Path.Combine(folder,"native-snapshot.json"),true);
  var assemblyPath=doc.GetPathName();app.CloseDoc(doc.GetTitle());doc=Open(app,assemblyPath);project=Load(code,assemblyPath+".beamng-project.json");
  capture=Create(code,"Preparation.MountAnchors",app,doc);foreach(var a in (IList)Get(project,"Anchors"))Call(capture,"Update",a);
  Scan(code,app,doc,project);File.Copy(assemblyPath+".beamng-project.json",Path.Combine(folder,"native-reopened.json"),true);
  doc.ClearSelection2(true);doc.ShowNamedView2("*Isometric",7);doc.ViewZoomtofit2();doc.GraphicsRedraw2();Application.DoEvents();
  var bmp=Path.Combine(folder,"native-authoring.bmp");if(doc.SaveBMP(bmp,0,0)){using(var image=new System.Drawing.Bitmap(bmp))image.Save(Path.Combine(folder,"native-authoring.png"));File.Delete(bmp);}
  File.WriteAllText(Path.Combine(folder,"result.json"),Json.Serialize(new{status="native_capture_completed",project=assemblyPath+".beamng-project.json",mates=((IList)Get(Get(project,"JointWorkspace"),"Mates")).Count,anchors=((IList)Get(project,"Anchors")).Count}));
  var sourceRecipe=Path.Combine(Path.GetDirectoryName(sourceProject),"recipe.json");File.Copy(sourceRecipe,Path.Combine(folder,"recipe.json"),true);
  File.WriteAllText(Path.Combine(folder,"native-capture.json"),Json.Serialize(new{assembly=assemblyPath,project=assemblyPath+".beamng-project.json",recipe_sha256=Read(sourceRecipe)["recipe_sha256"]}));
  app.CommandInProgress=false;
  Save(doc);app.CloseDoc(doc.GetTitle());Application.DoEvents();
 }
}
