public static class RearHubs {
 static readonly string root=@"H:\beamng project programs\BeamNG.cad\WorkingAsm";
 static readonly string working=Path.Combine(root,@"working-assembly-20261008-121423-3146e3\members-20261009-145459-2ddf1\Companion_e7c35c39.SLDASM");
 static readonly string review=Path.Combine(root,"rear-hub-review-20261010");
 static JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=int.MaxValue};
 static ISldWorks app;static List<ModelDoc2> opened=new List<ModelDoc2>();
 static Dictionary<string,object> Read(string p){return (Dictionary<string,object>)json.DeserializeObject(File.ReadAllText(p));}
 static Dictionary<string,object>[] Rows(Dictionary<string,object> d,string k){return ((object[])d[k]).Cast<Dictionary<string,object>>().ToArray();}
 static ModelDoc2 Open(string path){var d=app.GetOpenDocumentByName(path) as ModelDoc2;if(d!=null)return d;int e=0,w=0;var visible=app.GetDocumentVisible(1);try{app.DocumentVisible(false,1);d=app.OpenDoc6(path,1,3,"",ref e,ref w) as ModelDoc2;}finally{app.DocumentVisible(visible,1);}if(d==null)throw new Exception("Cannot inspect part: "+e+" "+path);opened.Add(d);return d;}
 static object Body(Body2 b){var cylinders=new List<object>();foreach(Face2 f in (object[])b.GetFaces()){var s=f.GetSurface() as Surface;if(s!=null&&s.IsCylinder())cylinders.Add(new{cylinder=s.CylinderParams,area=f.GetArea()});}return new{name=b.Name,faces=b.GetFaceCount(),box=b.GetBodyBox(),mass=b.GetMassProperties(1),cylinders=cylinders.OrderByDescending(v=>(double)v.GetType().GetProperty("area").GetValue(v,null)).Take(12).ToArray()};}
 static object Datums(Body2 b){return ((object[])b.GetFaces()).Cast<Face2>().Select(f=>{var s=(Surface)f.GetSurface();return (object)new{area=f.GetArea(),box=f.GetBox(),normal=f.Normal,cylinder=s.IsCylinder()?s.CylinderParams:null,plane=s.IsPlane()};}).ToArray();}
 public static void Run(int pid,string action,string output){
  app=(ISldWorks)typeof(CurrentAssignmentInspectionTest).GetMethod("Find",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{pid});var active=app.ActiveDoc as ModelDoc2;Directory.CreateDirectory(review);
  try{
   if(action=="state"){foreach(ModelDoc2 d in app.GetDocuments() as object[]??new object[0]){if(d is AssemblyDoc)Console.WriteLine(d.GetPathName()+" | dirty="+d.GetSaveFlag()+" | components="+(((AssemblyDoc)d).GetComponents(false) as object[]??new object[0]).Length+" | config="+d.ConfigurationManager.ActiveConfiguration.Name);}return;}
   var current=app.GetOpenDocumentByName(working) as ModelDoc2;if(current==null)throw new Exception("Working companion is not open");var dirty=current.GetSaveFlag();var stamp=current.GetUpdateStamp();
   var receipt=Read(Path.Combine(Path.GetDirectoryName(working),"working-assembly.json"));var backup=Read(Path.Combine(root,@"before-rear-donor-20261010-125553\restore-map.json"));var old=Read((string)backup[Path.Combine(Path.GetDirectoryName(working),"working-assembly.json")]);
   var project=Read(working+".beamng-project.json");var instances=((object[])((AssemblyDoc)current).GetComponents(true)).Cast<Component2>().ToArray();var results=new List<object>();
   foreach(var role in new[]{"rl_wheel","rr_wheel"}){
    var g=Rows(project,"Components").Single(c=>object.Equals(c["MvpRole"],role));var previous=Rows(old,"Groups").Single(c=>object.Equals(c["Id"],g["Id"]));var next=Rows(receipt,"Groups").Single(c=>object.Equals(c["Id"],g["Id"]));
    var native=instances.Single(c=>string.Equals(c.GetPathName(),(string)next["Part"],StringComparison.OrdinalIgnoreCase));var oldPart=Open((string)previous["Part"]);var nextPart=(ModelDoc2)native.GetModelDoc2();
    if(action=="datums"){var hub=((object[])((PartDoc)oldPart).GetBodies2(-1,false)).Cast<Body2>().Single(b=>b.Name=="TaggedBody_0001");var rim=((object[])((PartDoc)nextPart).GetBodies2(-1,false)).Cast<Body2>().Single(b=>b.Name.Contains("Rim"));results.Add(new{role=role,hub=Datums(hub),rim=Datums(rim)});continue;}
    results.Add(new{role=role,id=g["Id"],old_path=previous["Part"],current_path=next["Part"],transform=native.Transform2.ArrayData,original_bodies=((object[])((PartDoc)oldPart).GetBodies2(-1,false)).Cast<Body2>().Select(Body).ToArray(),current_bodies=((object[])((PartDoc)nextPart).GetBodies2(-1,false)).Cast<Body2>().Select(Body).ToArray()});Console.WriteLine("Inspected "+role);
   }
   File.WriteAllText(Path.Combine(review,action=="datums"?"hub-datums.json":"hub-inspection.json"),json.Serialize(new{working=working,dirty=dirty,groups=results}));if(current.GetSaveFlag()!=dirty||current.GetUpdateStamp()!=stamp)throw new Exception("Inspection altered working state");Console.WriteLine("PASS read-only hub inspection; working dirty="+dirty);
  }finally{foreach(var d in opened)app.CloseDoc(d.GetTitle());if(active!=null){int e=0;app.ActivateDoc3(active.GetTitle(),false,0,ref e);}}
 }
}
