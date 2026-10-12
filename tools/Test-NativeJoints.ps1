param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination,[ValidateSet('point','cylinder','hinge','rack','members','coilover','moving_ui','appearance_read','appearance_recopy','appearance_source','appearance_missing','appearance_refresh')][string]$Kind='point',[string]$CompanionAssembly)
$ErrorActionPreference='Stop'
if([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA'){throw 'Use -STA'}
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$Destination=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $Destination){throw 'Use a new owned fixture directory'}
[void][IO.Directory]::CreateDirectory($Destination)
if($Kind -in @('moving_ui','appearance_read','appearance_recopy','appearance_refresh')){
 if(-not $CompanionAssembly -or -not (Test-Path -LiteralPath $CompanionAssembly)){throw 'Provide an owned fixture companion assembly'}
 [IO.File]::WriteAllText((Join-Path $Destination 'companion-path.txt'),[IO.Path]::GetFullPath($CompanionAssembly))
}
$refs=@('System.Core','System.Web.Extensions','System.Windows.Forms','System.Drawing','System.Runtime.Serialization',(Join-Path $OutputDirectory 'SolidWorks.Interop.sldworks.dll'),(Join-Path $OutputDirectory 'SolidWorks.Interop.swconst.dll'))
foreach($ref in $refs[5..6]){[void][Reflection.Assembly]::LoadFrom($ref)}
$helper=Get-Content -Raw (Join-Path $PSScriptRoot 'New-SyntheticVehicle.ps1')
$start=$helper.IndexOf('using System;');$end=$helper.IndexOf("'@",$start)
$source=$helper.Substring($start,$end-$start)+@'

public static class NativeJointsTest {
 static string PartBytes(string path){using(var input=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var output=new MemoryStream()){input.CopyTo(output);return Convert.ToBase64String(output.ToArray());}}
 static void MovingUi(Assembly code,ISldWorks app,string folder,bool appearanceOnly,bool recopy,bool refresh=false){
  var path=File.ReadAllText(Path.Combine(folder,"companion-path.txt"));int error=0,warning=0;
  var model=(ModelDoc2)app.OpenDoc6(path,2,1,"",ref error,ref warning);Check(model!=null,"open owned companion fixture");app.ActivateDoc3(model.GetTitle(),false,0,ref error);
  var project=code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Load").Invoke(null,new object[]{path+".beamng-project.json"});
  var component=((IList)Get(project,"Components"))[0];Set(component,"MvpRole","FL_spring_damper");
  if(recopy){
   var fork=Call(project,"Fork",Path.Combine(folder,"copy-input.json"));Call(fork,"Save");
   var result=Wait(Call(Create(code,"Preparation.AssociationAssembly",app,model),"Create",fork,Path.Combine(folder,"companion"),null,System.Threading.CancellationToken.None));
   model=(ModelDoc2)Get(result,"Document");project=Get(result,"Project");
  }
  if(refresh){
   component=((IList)Get(project,"Components"))[0];
   var physical="retained-physical-package";Set(project,"LastBuildReceipt",physical);Call(project,"Save");
   var nativeMembers=(IList)Get(Get(project,"JointWorkspace"),"Members");var faceRefs=new Dictionary<string,List<string>>();var instanceRefs=new List<string>();
   var geometry=new Dictionary<string,string>();var targetParts=new Dictionary<string,ModelDoc2>();
   model.ClearSelection2(true);
   foreach(var member in nativeMembers){int state;var reference=(string)Get(member,"ComponentReference");instanceRefs.Add(reference);var instance=(Component2)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out state);instance.Select4(true,null,false);var part=(ModelDoc2)instance.GetModelDoc2();targetParts[part.GetPathName()]=part;
    foreach(Body2 body in (object[])((PartDoc)part).GetBodies2(0,false)){geometry[part.GetPathName()+"|"+body.Name]=string.Join(",",(double[])body.GetBodyBox());foreach(Face2 face in (object[])body.GetFaces()){List<string> refs;if(!faceRefs.TryGetValue(part.GetPathName(),out refs))faceRefs.Add(part.GetPathName(),refs=new List<string>());refs.Add(Convert.ToBase64String((byte[])part.Extension.GetPersistReference3(face)));}}
   }
   var folderFeature=(Feature)model.FeatureManager.InsertFeatureTreeFolder2((int)swFeatureTreeFolderType_e.swFeatureTreeFolder_Containing);Check(folderFeature!=null,"create native organization folder");folderFeature.Name="Organized coilover";
   var folderRef=Convert.ToBase64String((byte[])model.Extension.GetPersistReference3(folderFeature));model.ClearSelection2(true);Save(model,model.GetPathName());
   var mateData=((SelectionMgr)model.SelectionManager).CreateSelectData();mateData.Mark=1;
   for(int i=0;i<2;i++){int state;var instance=(Component2)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(instanceRefs[i]),out state);if(i==1){model.ClearSelection2(true);instance.Select4(false,null,false);((AssemblyDoc)model).UnfixComponent();}model.ClearSelection2(true);}
   model.ClearSelection2(true);
   for(int i=0;i<2;i++){int state;object info;var instance=(Component2)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(instanceRefs[i]),out state);var body=(Body2)((object[])instance.GetBodies3(0,out info))[0];var face=((object[])body.GetFaces()).Cast<Face2>().Where(f=>((Surface)f.GetSurface()).IsPlane()).OrderBy(f=>((double[])f.GetBox())[2]).First();Check(((Entity)face).Select4(i>0,mateData),"select existing member mate face");}
   int mateError;var mate=((AssemblyDoc)model).AddMate5((int)swMateType_e.swMateCOINCIDENT,0,false,0,0,0,0,0,0,0,0,false,false,0,out mateError);Check(mate!=null&&mateError==(int)swAddMateError_e.swAddMateError_NoError,"create actual companion mate");
   Feature mateFeature=null;for(var group=(Feature)model.FirstFeature();group!=null;group=(Feature)group.GetNextFeature())for(var feature=(Feature)group.GetFirstSubFeature();feature!=null;feature=(Feature)feature.GetNextSubFeature())if(feature.GetSpecificFeature2() is Mate2)mateFeature=feature;
   Check(mateFeature!=null,"find actual mate feature");var mateRef=Convert.ToBase64String((byte[])model.Extension.GetPersistReference3(mateFeature));model.ClearSelection2(true);Save(model,model.GetPathName());
   foreach(var part in targetParts.Values){
    foreach(RenderMaterial material in part.Extension.GetRenderMaterials2(1,null) as object[]??new object[0])if((material.GetEntities() as object[]??new object[0]).Any(e=>e is Face2)){int a,b;material.GetMaterialIds(out a,out b);Check(part.Extension.DeleteDisplayStateSpecificRenderMaterial(new[]{a},new[]{b}),"remove fixture face paint");}
    foreach(Body2 body in (object[])((PartDoc)part).GetBodies2(0,false))foreach(Face2 face in (object[])body.GetFaces())face.MaterialPropertyValues=new[]{.2,.2,.2,.3,.8,.3,.3,0.0,0.0};Save(part,part.GetPathName());
   }
   Save(model,model.GetPathName());
   var link=code.GetType("BeamNG.Cad.Preparation.CompanionAssemblyLink");var receipt=(string)link.GetMethod("Find").Invoke(null,new[]{project});
   var service=Create(code,"Preparation.AssociationAssembly",app,model);var beforeWorkspace=code.GetType("BeamNG.Cad.Preparation.CompanionAssemblyLink").GetMethod("Serialized",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new[]{Get(project,"JointWorkspace"),(object)Get(project,"JointWorkspace").GetType()});
   var backup=(string)Wait(Call(service,"RefreshAppearances",project,receipt,Get(component,"Id"),null,System.Threading.CancellationToken.None));Check(Directory.GetFiles(backup,"*.SLDPRT").Length==3,"back up only three affected parts");
   Check((string)Get(project,"LastBuildReceipt")==physical,"physical package receipt retained");Check((string)Get(component,"AppearancePackageState")=="pending","appearance packaging marked pending");
   Check((string)beforeWorkspace==(string)link.GetMethod("Serialized",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new[]{Get(project,"JointWorkspace"),(object)Get(project,"JointWorkspace").GetType()}),"moving member and joint definitions retained");
   int nativeState;Check(model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(folderRef),out nativeState)!=null&&nativeState==0,"native organization folder reference retained");
   Check(model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(mateRef),out nativeState)!=null&&nativeState==0,"actual native mate identity retained");
   Check(((FeatureFolder)folderFeature.GetSpecificFeature2()).GetFeatureCount()==3,"three components remain in organization folder");
   foreach(var reference in instanceRefs)Check(model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out nativeState)!=null&&nativeState==0,"native component identity retained");
   foreach(var item in faceRefs)foreach(var reference in item.Value)Check(targetParts[item.Key].Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out nativeState)!=null&&nativeState==0,"native face identity retained");
   foreach(var part in targetParts.Values)foreach(Body2 body in (object[])((PartDoc)part).GetBodies2(0,false))Check(geometry[part.GetPathName()+"|"+body.Name]==string.Join(",",(double[])body.GetBodyBox()),"body geometry unchanged");
   Check(app.IsSame(app.ActiveDoc,model)==(int)swObjectEquality.swObjectSame,"refresh restores companion activation");
   using(var form=(Form)Create(code,"UI.ComponentWorkflow",app,model,Create(code,"UI.ExporterSettings",Path.Combine(folder,"refresh-ui-settings.xml")))){Check(form.Controls.Find("RefreshCompanionAppearances",true).Length==1,"workflow exposes appearance-only source refresh");}
   using(var form=(Form)Create(code,"UI.MovingMembersPanel",app,model,project,component)){Check(form.Controls.Find("RefreshMovingAppearances",true).Length==1,"moving pieces dialog exposes colour refresh without splitting");}
   Save(model,model.GetPathName());
   var partBytes=targetParts.Keys.ToDictionary(p=>p,p=>PartBytes(p));
   var canceled=new System.Threading.CancellationTokenSource();canceled.Cancel();bool canceledSafely=false;
   try{Wait(Call(service,"RefreshAppearances",project,receipt,Get(component,"Id"),null,canceled.Token));}catch(Exception failure){canceledSafely=failure.ToString().Contains("canceled")||failure.ToString().Contains("cancelled");}
   Check(canceledSafely&&targetParts.Keys.All(p=>partBytes[p]==PartBytes(p)),"cancellation leaves saved parts unchanged");
   var receiptType=code.GetType("BeamNG.Cad.Preparation.AssociationAssembly+Receipt");var jsonType=code.GetType("BeamNG.Cad.Preparation.JsonFile");
   var readReceipt=jsonType.GetMethod("Read").MakeGenericMethod(receiptType);var writeReceipt=jsonType.GetMethod("Write").MakeGenericMethod(receiptType);
   var provenancePath=Path.Combine(folder,"companion","appearance-provenance.json");var provenanceBytes=File.ReadAllBytes(provenancePath);var provenance=readReceipt.Invoke(null,new object[]{provenancePath});Set(provenance,"SourceDocument",Path.Combine(folder,"missing-source.SLDASM"));writeReceipt.Invoke(null,new[]{(object)provenancePath,provenance});bool missingSafely=false;
   try{Wait(Call(service,"RefreshAppearances",project,receipt,Get(component,"Id"),null,System.Threading.CancellationToken.None));}catch(Exception failure){missingSafely=failure.ToString().Contains("Cannot open original appearance source");}finally{File.WriteAllBytes(provenancePath,provenanceBytes);}
   Check(missingSafely&&targetParts.Keys.All(p=>partBytes[p]==PartBytes(p)),"missing source leaves saved parts unchanged");
   var firstPart=targetParts.Keys.First();var memberProvenance=readReceipt.Invoke(null,new object[]{Path.Combine(Path.GetDirectoryName(firstPart),"appearance-provenance.json")});var combinedPath=(string)Get(memberProvenance,"SourceDocument");var combined=(ModelDoc2)app.GetOpenDocumentByName(combinedPath);Check(combined!=null,"owned intermediate source remains available");
   var sourceInstance=((object[])((AssemblyDoc)combined).GetComponents(true)).Cast<Component2>().Single();var savedTransform=(double[])sourceInstance.Transform2.ArrayData;var moved=(double[])savedTransform.Clone();moved[11]+=.001;sourceInstance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(moved);app.ActivateDoc3(model.GetTitle(),false,0,ref error);bool changedSafely=false;
   try{Wait(Call(service,"RefreshAppearances",project,receipt,Get(component,"Id"),null,System.Threading.CancellationToken.None));}catch(Exception failure){changedSafely=failure.ToString().Contains("source geometry or placement changed");}finally{sourceInstance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(savedTransform);Save(combined,combinedPath);app.ActivateDoc3(model.GetTitle(),false,0,ref error);}
   Check(changedSafely&&targetParts.Keys.All(p=>partBytes[p]==PartBytes(p)),"changed source placement rejected without changing saved parts");
   File.WriteAllText(model.GetPathName()+".appearance-contract.json",new JavaScriptSerializer().Serialize(new {folderRef,mateRef,instanceRefs,faceRefs,geometry}));
   File.WriteAllText(Path.Combine(folder,"refreshed-assembly.txt"),model.GetPathName());
  }
  if(appearanceOnly){
   var contractPath=model.GetPathName()+".appearance-contract.json";
   if(File.Exists(contractPath)){
    var contract=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(contractPath));int state;
    var folderFeature=(Feature)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String((string)contract["folderRef"]),out state);Check(folderFeature!=null&&state==0,"organization folder survives fresh reopen");Check(((FeatureFolder)folderFeature.GetSpecificFeature2()).GetFeatureCount()==3,"folder membership survives fresh reopen");
    Check(model.Extension.GetObjectByPersistReference3(Convert.FromBase64String((string)contract["mateRef"]),out state)!=null&&state==0,"actual native mate survives fresh reopen");
    foreach(string reference in (IEnumerable)contract["instanceRefs"])Check(model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out state)!=null&&state==0,"component identity survives fresh reopen");
    foreach(var entry in (Dictionary<string,object>)contract["faceRefs"]){var part=(ModelDoc2)app.GetOpenDocumentByName(entry.Key);Check(part!=null,"refreshed part loaded on reopen");foreach(string reference in (IEnumerable)entry.Value)Check(part.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out state)!=null&&state==0,"face identity survives fresh reopen");}
   }
   var members=(IList)Get(Get(project,"JointWorkspace"),"Members");
   foreach(var member in members){int state;var instance=(Component2)model.Extension.GetObjectByPersistReference3(Convert.FromBase64String((string)Get(member,"ComponentReference")),out state);object info;
    var start=(string)Get(member,"Kind")=="housing"?0:(string)Get(member,"Kind")=="shaft"?1:2;var index=0;
    foreach(var body in ((object[])instance.GetBodies3(0,out info)).Cast<Body2>().OrderBy(b=>b.Name)){
     var nativePart=(ModelDoc2)instance.GetModelDoc2();
     var nativeBody=((object[])((PartDoc)nativePart).GetBodies2(0,false)).Cast<Body2>().Single(b=>b.Name==body.Name);string materialDatabase;
     Check(nativeBody.GetMaterialPropertyName(nativePart.ConfigurationManager.ActiveConfiguration.Name,out materialDatabase)=="Plain Carbon Steel","physical material preserved: "+Get(member,"Kind")+" / "+body.Name);
     foreach(RenderMaterial appearance in nativePart.Extension.GetRenderMaterials2((int)swDisplayStateOpts_e.swThisDisplayState,null) as object[]??new object[0])
      Console.WriteLine("PART_APPEARANCE "+appearance.PrimaryColor+" "+appearance.FileName+" entities="+string.Join(",",(appearance.GetEntities() as object[]??new object[0]).Select(e=>e is Face2?"face":e is Body2?"body":"other")));
     var reader=Create(code,"Preparation.SolidWorksAppearances",app,instance,body);var expected=new[]{(start+index+1)/7.0,.1,.9-(start+index)*.1}.Select(x=>Math.Round(x*255)/255).ToArray();
     foreach(Face2 face in (object[])body.GetFaces()){var actual=(double[])Get(Call(reader,"Read",face),"BaseColor");Check(actual.Take(3).Zip(expected,(a,b)=>Math.Abs(a-b)).Max()<1e-6,"appearance "+Get(member,"Kind")+" / "+body.Name+" actual="+string.Join(",",actual)+" expected="+string.Join(",",expected));}index++;
    }
   }
   File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS preserved multi-body split appearances");return;
  }
  using(var form=(Form)Create(code,"UI.MovingMembersPanel",app,model,project,component)){
   form.Show();Application.DoEvents();var grid=(DataGridView)form.Controls.Find("MovingBodyRows",true).Single();
   Call(form,"OperationFeedback","Failed: Save companion CAD first.",true);
   var operation=(Label)form.Controls.Find("MovingOperationFeedback",true).Single();Check(operation.Visible&&operation.Text.Contains("Save companion CAD"),"operation failure is visible inside moving-pieces dialog");
   Check(grid.Columns[1] is DataGridViewComboBoxColumn,"moving-piece cells use dropdowns");
   var column=(DataGridViewComboBoxColumn)grid.Columns[1];Check(column.Items.Cast<object>().Select(v=>v.ToString()).Where(v=>v.Length>0).OrderBy(v=>v).SequenceEqual(new[]{"housing","shaft","spring"}),"coilover dropdown has hardware-specific choices");
   grid.ClearSelection();grid.CurrentCell=grid.Rows[1].Cells[0];grid.Rows[1].Selected=true;Application.DoEvents();
   var manager=(SelectionMgr)model.SelectionManager;Check(manager.GetSelectedObjectCount2(-1)==1,"row change highlights one CAD body automatically");
   var body=manager.GetSelectedObject6(1,-1) as Body2;Check(body!=null,"automatic highlight selects physical body");
   grid.Rows[2].Selected=true;Application.DoEvents();Check(manager.GetSelectedObjectCount2(-1)==2,"multiple rows highlight both CAD bodies");
   Check(operation.Text.Contains("Save companion CAD")&&operation.ForeColor==System.Drawing.Color.DarkRed,"CAD row highlighting does not erase the operation error");
   var picker=(ComboBox)form.Controls.Find("MovingPieceChoice",true).Single();Check(picker.DropDownStyle==ComboBoxStyle.DropDownList,"bulk assignment prevents free-text input");
   picker.SelectedItem="shaft";var assign=form.Controls.Cast<Control>().SelectMany(c=>c.Controls.Cast<Control>()).OfType<Button>().Single(b=>b.Text=="Assign to selected bodies");assign.PerformClick();
   Check(grid.SelectedRows.Cast<DataGridViewRow>().All(r=>Convert.ToString(r.Cells[1].Value)=="shaft"),"bulk assignment updates selected rows together");
   using(var bitmap=new System.Drawing.Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new System.Drawing.Rectangle(0,0,bitmap.Width,bitmap.Height));bitmap.Save(Path.Combine(folder,"moving-pieces-ui.png"));}
  }
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS moving-piece dropdowns, native row highlighting and bulk assignment; no CAD or classification changes saved");
 }
 sealed class CadContext : System.Threading.SynchronizationContext {
  readonly System.Collections.Concurrent.ConcurrentQueue<Action> queue=new System.Collections.Concurrent.ConcurrentQueue<Action>();
  public override void Post(System.Threading.SendOrPostCallback action,object state){queue.Enqueue(()=>action(state));}
  public void Drain(){Action action;while(queue.TryDequeue(out action)){SetSynchronizationContext(this);action();}}
 }
 static object Get(object o,string n){return o.GetType().GetField(n).GetValue(o);}
 static void Set(object o,string n,object value){o.GetType().GetField(n).SetValue(o,value);}
 static object Call(object o,string n,params object[] args){return o.GetType().GetMethod(n).Invoke(o,args);}
 static object Create(Assembly code,string type,params object[] args){return Activator.CreateInstance(code.GetType("BeamNG.Cad."+type),BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,args,null);}
 static void Check(bool ok,string label){if(!ok)throw new Exception(label);Console.WriteLine("PASS "+label);}
 static object Wait(object value){var task=(System.Threading.Tasks.Task)value;var context=(CadContext)System.Threading.SynchronizationContext.Current;while(!task.IsCompleted){context.Drain();Application.DoEvents();System.Threading.SynchronizationContext.SetSynchronizationContext(context);System.Threading.Thread.Sleep(10);}task.GetAwaiter().GetResult();return task.GetType().GetProperty("Result").GetValue(task,null);}
 static void Save(ModelDoc2 doc,string path){int error=0,warning=0;if(!doc.Extension.SaveAs(path,0,1,null,ref error,ref warning))throw new Exception("Save "+error);}
 static IList One(object value){var list=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(value.GetType()));list.Add(value);return list;}
 static void Members(Assembly code,ISldWorks app,ModelDoc2 source,object project,string folder){
  var groups=(IList)Get(project,"Components");var owner=groups[0];var other=groups[1];
  foreach(var key in new[]{"Selections","BodyIds"})foreach(var value in (IList)Get(other,key))((IList)Get(owner,key)).Add(value);
  groups.RemoveAt(1);Set(owner,"Name","Native rack pair");Call(project,"Save");
  var sourceProject=File.ReadAllText(source.GetPathName()+".beamng-project.json");
  var sourceService=Create(code,"Preparation.AssociationAssembly",app,source);
  var result=Wait(Call(sourceService,"Create",project,Path.Combine(folder,"working"),null,System.Threading.CancellationToken.None));
  var working=(ModelDoc2)Get(result,"Document");var copy=Get(result,"Project");var receipt=(string)Get(result,"ReceiptPath");
  var group=((IList)Get(copy,"Components"))[0];var selections=(IList)Get(group,"Selections");var ids=(IList)Get(group,"BodyIds");
  Check(selections.Count==2&&ids.Count==2,"logical CAD group retains two native bodies");
  for(int i=0;i<2;i++){
   var member=Create(code,"Preparation.MovingMember");Set(member,"Id",i==0?"housing_member":"slider_member");Set(member,"Kind",i==0?"housing":"rack");
   Set(member,"Name",i==0?"Housing":"Rack");Set(member,"ComponentId",Get(group,"Id"));Set(member,"Selections",One(selections[i]));Set(member,"BodyIds",One(ids[i]));((IList)Get(Get(copy,"JointWorkspace"),"Members")).Add(member);
  }
  Call(copy,"Save");Save(working,working.GetPathName());
  result=Wait(Call(Create(code,"Preparation.AssociationAssembly",app,working),"SplitMembers",copy,receipt,Get(group,"Id"),null,System.Threading.CancellationToken.None));
  working=(ModelDoc2)Get(result,"Document");copy=Get(result,"Project");
  Check(((object[])((AssemblyDoc)working).GetComponents(true)).Length==2,"moving revision creates two native member instances");
  Check(((IList)Get(copy,"Components")).Count==1&&((IList)Get(((IList)Get(copy,"Components"))[0],"BodyIds")).Count==2,"logical owner and complete body partition survive splitting");
  Check(File.ReadAllText(source.GetPathName()+".beamng-project.json")==sourceProject,"splitting leaves the source project unchanged");
  var path=working.GetPathName();app.CloseDoc(working.GetTitle());int error=0,warning=0;working=(ModelDoc2)app.OpenDoc6(path,2,1,"",ref error,ref warning);Check(working!=null,"moving revision reopens");app.ActivateDoc3(working.GetTitle(),false,0,ref error);
  copy=code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Load").Invoke(null,new object[]{path+".beamng-project.json"});
  var selector=Create(code,"Preparation.FrameSelection",app,working,true);
  foreach(var member in (IList)Get(Get(copy,"JointWorkspace"),"Members")){
   var assignment=Create(code,"Preparation.FrameAssignment");Set(assignment,"Configuration",working.ConfigurationManager.ActiveConfiguration.Name);Set(assignment,"Selections",Get(member,"Selections"));
   Check(((IList)Call(selector,"BodyIds",assignment)).Count==1,"member reference resolves after reopen: "+Get(member,"Name"));
  }
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);Set(owner,"Name","Updated native rack");Call(project,"Save");
  result=Wait(Call(sourceService,"Update",project,receipt,true,null,System.Threading.CancellationToken.None));
  var updated=(ModelDoc2)Get(result,"Document");var updatedProject=Get(result,"Project");
  Check(((object[])((AssemblyDoc)updated).GetComponents(true)).Length==2&&((IList)Get(Get(updatedProject,"JointWorkspace"),"Members")).Count==2,"source geometry refresh preserves the native moving-member partition");
  // Reclassify the source bodies without changing their union. An ordinary
  // update must rebuild the member partition even without Refresh geometry.
  var sourceMembers=(IList)Get(Get(project,"JointWorkspace"),"Members");
  for(int i=0;i<2;i++){
   var member=Create(code,"Preparation.MovingMember");Set(member,"Id","source_"+i);Set(member,"ComponentId",Get(owner,"Id"));
   Set(member,"Kind",i==0?"housing":"rack");Set(member,"Name",i==0?"Housing":"Rack");
   Set(member,"Selections",One(((IList)Get(owner,"Selections"))[1-i]));Set(member,"BodyIds",One(((IList)Get(owner,"BodyIds"))[1-i]));sourceMembers.Add(member);
  }
  app.ActivateDoc3(source.GetTitle(),false,0,ref error);Call(project,"Save");
  result=Wait(Call(sourceService,"Update",project,receipt,false,null,System.Threading.CancellationToken.None));
  updated=(ModelDoc2)Get(result,"Document");updatedProject=Get(result,"Project");
  Check(((object[])((AssemblyDoc)updated).GetComponents(true)).Length==2,"source reclassification creates exactly two member instances");
  var receiptText=File.ReadAllText(receipt);
  Check(receiptText.Contains("housing_member")&&receiptText.Contains("slider_member"),"member identity persists across source reclassification");
  var updatedSelector=Create(code,"Preparation.FrameSelection",app,updated,true);
  foreach(var member in (IList)Get(Get(updatedProject,"JointWorkspace"),"Members")){
   var assignment=Create(code,"Preparation.FrameAssignment");Set(assignment,"Configuration",updated.ConfigurationManager.ActiveConfiguration.Name);Set(assignment,"Selections",Get(member,"Selections"));
   Check(((IList)Call(updatedSelector,"BodyIds",assignment)).Count==1,"reclassified member body resolves: "+Get(member,"Kind"));
  }
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS native split, reopen, source refresh and source reclassification");
 }
 static object Scan(Assembly code,ISldWorks app,ModelDoc2 doc,object project,string path){
  var scan=Create(code,"Preparation.NativeMateScanner",app,doc,project);
  var mates=Wait(Call(scan,"Capture",(Action<string>)(s=>Console.WriteLine(s)),System.Threading.CancellationToken.None));
  var workspace=Get(project,"JointWorkspace");Set(workspace,"Mates",mates);Set(workspace,"ScanStamp",doc.GetUpdateStamp());
  var write=code.GetType("BeamNG.Cad.Preparation.JsonFile").GetMethod("Write").MakeGenericMethod(workspace.GetType());write.Invoke(null,new[]{(object)path,workspace});
  return mates;
 }
 public static void Run(object application,string dll,string folder,string kind){
  var missingAsset=kind=="appearance_missing";var sourceOnly=kind=="appearance_source"||missingAsset;if(sourceOnly)kind="coilover";
  var app=(ISldWorks)application;app.CommandInProgress=true;var code=Assembly.LoadFrom(dll);System.Threading.SynchronizationContext.SetSynchronizationContext(new CadContext());
  if(kind=="moving_ui"||kind=="appearance_read"||kind=="appearance_recopy"||kind=="appearance_refresh"){MovingUi(code,app,folder,kind!="moving_ui",kind=="appearance_recopy"||kind=="appearance_refresh",kind=="appearance_refresh");app.CommandInProgress=false;return;}
  var doc=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly),0,0,0);
  var path=Path.Combine(folder,"NativeJoints.SLDASM");Save(doc,path);var instances=new List<Component2>();int error=0;
  for(int i=0;i<(sourceOnly?1:kind=="coilover"?6:2);i++){
   var part=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
   var shape=new Dictionary<string,object>{{"kind","box"},{"center",new[]{0.0,0.0,0.0}},{"size",new[]{.2,.1,.08}}};
   if(kind!="point"&&kind!="members"&&kind!="coilover")shape=new Dictionary<string,object>{{"kind","cylinder"},{"a",new[]{0.0,0.0,0.0}},{"b",new[]{0.0,0.0,.2}},{"radius",.03}};
   typeof(SyntheticNativeCad).GetMethod("MakeShape",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{app,part,shape,true});
   if(kind=="coilover"){
    var db=((IEnumerable)app.GetMaterialDatabases()).Cast<string>().Single(p=>Path.GetFileName(p).Equals("solidworks materials.sldmat",StringComparison.OrdinalIgnoreCase));
    ((PartDoc)part).SetMaterialPropertyName2("",db,"Plain Carbon Steel");
    var colourFile=Path.Combine(folder,"colour"+i+".p2m");
    var colourValues=new[]{(i+1)/7.0,.1,.9-i*.1}.Select(x=>Math.Round(x*255)/255).ToArray();
    var colourTemplate=File.ReadAllText(Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.ProgramFiles),@"SOLIDWORKS Corp\SOLIDWORKS\data\graphics\materials\color.p2m"));
    File.WriteAllText(colourFile,System.Text.RegularExpressions.Regex.Replace(colourTemplate,"(?m)^\"col1\".*$","\"col1\" "+string.Join(" ",colourValues.Select(x=>x.ToString("R",System.Globalization.CultureInfo.InvariantCulture)))));
    var finish=part.Extension.CreateRenderMaterial(colourFile);
    finish.PrimaryColor=(int)Math.Round((i+1)/7.0*255)|((int)Math.Round(.1*255)<<8)|((int)Math.Round((.9-i*.1)*255)<<16);
    foreach(Body2 body in (object[])((PartDoc)part).GetBodies2(0,false))foreach(Face2 face in (object[])body.GetFaces())Check(finish.AddEntity(face),"paint source face");
    int finish1=0,finish2=0;Check(part.Extension.AddDisplayStateSpecificRenderMaterial(finish,(int)swDisplayStateOpts_e.swSpecifyDisplayState,part.ConfigurationManager.ActiveConfiguration.GetDisplayStates(),out finish1,out finish2),"save source native appearance");
    part.Extension.UpdateRenderMaterialsInSceneGraph(true);part.SetSaveFlag();
   }
   var partPath=Path.Combine(folder,"member"+i+".SLDPRT");Save(part,partPath);app.ActivateDoc3(doc.GetTitle(),false,0,ref error);
   if(sourceOnly){
    app.CloseDoc(part.GetTitle());int sourceWarning=0;part=(ModelDoc2)app.OpenDoc6(partPath,1,1,"",ref error,ref sourceWarning);Check(part!=null,"reopen source appearance fixture");
    var appearances=part.Extension.GetRenderMaterials2((int)swDisplayStateOpts_e.swThisDisplayState,null) as object[]??new object[0];
    foreach(RenderMaterial appearance in appearances)Console.WriteLine("SOURCE_APPEARANCE "+appearance.PrimaryColor+" "+appearance.FileName+" entities="+(appearance.GetEntities() as object[]??new object[0]).Length);
    Check(appearances.Cast<RenderMaterial>().Any(a=>a.PrimaryColor==15079972),"source native face colour persists through save/reopen");
    if(missingAsset){
     var painted=appearances.Cast<RenderMaterial>().Single(a=>a.PrimaryColor==15079972);
     var captured=Create(code,"Preparation.NativeAppearance",painted);
     Check(Path.GetFullPath(painted.FileName)==Path.GetFullPath(Path.Combine(folder,"colour0.p2m")),"missing-asset fixture owns its external file");
     File.Delete(painted.FileName); // Only this owned fixture's external paint asset.
     part=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
     typeof(SyntheticNativeCad).GetMethod("MakeShape",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{app,part,shape,true});
     partPath=Path.Combine(folder,"reconstructed.SLDPRT");Save(part,partPath);
     var faces=((object[])((Body2)((object[])((PartDoc)part).GetBodies2(0,false))[0]).GetFaces()).Cast<Face2>().ToArray();
     Call(captured,"Apply",part,faces,folder,new List<string>());Save(part,partPath);
     app.CloseDoc(part.GetTitle());part=(ModelDoc2)app.OpenDoc6(partPath,1,1,"",ref error,ref sourceWarning);Check(part!=null,"reopen reconstructed appearance");
     var restored=(part.Extension.GetRenderMaterials2(1,null) as object[]??new object[0]).Cast<RenderMaterial>().Where(a=>File.Exists(a.FileName)&&(a.GetEntities() as object[]??new object[0]).Any(e=>e is Face2)).ToArray();
     Check(restored.Length>0&&restored.All(a=>a.PrimaryColor==15079972),"missing appearance asset preserves captured colour through reopen; actual="+string.Join(",",restored.Select(a=>a.PrimaryColor)));
     File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS missing-asset native appearance reconstruction");return;
    }
    File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS native source appearance round trip");return;
   }
   var instance=((AssemblyDoc)doc).AddComponent5(partPath,0,"",false,"",0,0,0);Check(instance!=null,"insert member "+i);instances.Add(instance);
   if(kind=="members"&&i==1){var placement=(double[])instance.Transform2.ArrayData;placement[9]+=.3;instance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(placement);}
   doc.ClearSelection2(true);instance.Select4(false,null,false);if(i==0)((AssemblyDoc)doc).FixComponent();else ((AssemblyDoc)doc).UnfixComponent();
  }
  Save(doc,path);var project=code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Open").Invoke(null,new object[]{path});
  var selection=Create(code,"Preparation.FrameSelection",app,doc,true);var groups=(IList)Get(project,"Components");
  foreach(var instance in instances){
   doc.ClearSelection2(true);instance.Select4(false,null,false);var assignment=Call(selection,"Capture");var group=Create(code,"Preparation.ComponentDefinition");
   Set(group,"Id","owner"+groups.Count);Set(group,"Name",instance.Name2);Set(group,"Configuration",Get(assignment,"Configuration"));Set(group,"Selections",Get(assignment,"Selections"));Set(group,"BodyIds",Call(selection,"BodyIds",assignment));groups.Add(group);
  }
  if(kind=="members"){Call(project,"Save");Members(code,app,doc,project,folder);app.CommandInProgress=false;return;}
  if(kind=="coilover"){
   for(int i=0;i<instances.Count;i++){
    object info;var body=(Body2)((object[])instances[i].GetBodies3(0,out info))[0];var reader=Create(code,"Preparation.SolidWorksAppearances",app,instances[i],body);
    var expected=new[]{(i+1)/7.0,.1,.9-i*.1}.Select(x=>Math.Round(x*255)/255).ToArray();
    var actual=(double[])Get(Call(reader,"Read",((object[])body.GetFaces())[0]),"BaseColor");
    Check(actual.Take(3).Zip(expected,(a,b)=>Math.Abs(a-b)).Max()<1e-6,"source colour "+i+" actual="+string.Join(",",actual)+" expected="+string.Join(",",expected));
   }
   var owner=groups[0];var appearance=Create(code,"Preparation.CoiloverAppearance");var pieces=(IList)Get(appearance,"Pieces");
   var selections=(IList)Get(owner,"Selections");var ids=(IList)Get(owner,"BodyIds");
   for(int i=0;i<3;i++){
    var group=groups[i];var piece=Create(code,"Preparation.CoiloverMeshAssignment");Set(piece,"Kind",new[]{"housing","shaft","spring"}[i]);
    Set(piece,"Selections",Get(group,"Selections"));Set(piece,"BodyIds",Get(group,"BodyIds"));Set(piece,"Configuration",Get(group,"Configuration"));Set(piece,"SourceDocument",path);pieces.Add(piece);
   }
   // Clone lists before union, so each saved piece retains its own body partition.
   var allSelections=(IList)Activator.CreateInstance(selections.GetType());var allIds=(IList)Activator.CreateInstance(ids.GetType());
   foreach(var group in groups){foreach(var item in (IList)Get(group,"Selections"))allSelections.Add(item);foreach(var item in (IList)Get(group,"BodyIds"))allIds.Add(item);}
   var spring=pieces[2];var springSelections=(IList)Activator.CreateInstance(selections.GetType());var springIds=(IList)Activator.CreateInstance(ids.GetType());
   for(int i=2;i<groups.Count;i++){foreach(var item in (IList)Get(groups[i],"Selections"))springSelections.Add(item);foreach(var item in (IList)Get(groups[i],"BodyIds"))springIds.Add(item);}
   Set(spring,"Selections",springSelections);Set(spring,"BodyIds",springIds);
   Set(owner,"Selections",allSelections);Set(owner,"BodyIds",allIds);Set(owner,"AppearanceCoilover",appearance);groups.Clear();groups.Add(owner);Call(project,"Save");
   var builder=Create(code,"Preparation.AssociationAssembly",app,doc);var result=Wait(Call(builder,"Create",project,Path.Combine(folder,"companion"),null,System.Threading.CancellationToken.None));
   var copied=Get(result,"Project");var copiedOwners=(IList)Get(copied,"Components");var members=(IList)Get(Get(copied,"JointWorkspace"),"Members");
   Check(copiedOwners.Count==1&&members.Count==3,"automatic coilover split keeps one logical owner and three members");
   Check(members.Cast<object>().Select(m=>(string)Get(m,"Part")).Distinct().Count()==3,"automatic moving members have separate native parts");
   var revised=(ModelDoc2)Get(result,"Document");var revisedPath=revised.GetPathName();Save(revised,revisedPath);
   foreach(var member in members){int state;var resolved=revised.Extension.GetObjectByPersistReference3(Convert.FromBase64String((string)Get(member,"ComponentReference")),out state);Check(resolved!=null&&state==0,"automatic member reference resolves: "+Get(member,"Kind"));}
   foreach(var member in members){
    int state;var instance=(Component2)revised.Extension.GetObjectByPersistReference3(Convert.FromBase64String((string)Get(member,"ComponentReference")),out state);object info;
    var bodyIndex=0;var start=(string)Get(member,"Kind")=="housing"?0:(string)Get(member,"Kind")=="shaft"?1:2;
    foreach(var body in ((object[])instance.GetBodies3(0,out info)).Cast<Body2>().OrderBy(b=>b.Name)){
     var reader=Create(code,"Preparation.SolidWorksAppearances",app,instance,body);var expected=new[]{(start+bodyIndex+1)/7.0,.1,.9-(start+bodyIndex)*.1}.Select(x=>Math.Round(x*255)/255).ToArray();
     foreach(Face2 face in (object[])body.GetFaces()){var appearanceValue=Call(reader,"Read",face);var color=(double[])Get(appearanceValue,"BaseColor");Check(color.Take(3).Zip(expected,(a,b)=>Math.Abs(a-b)).Max()<1e-6,"split member preserves body face appearance: "+Get(member,"Kind")+" / "+body.Name+" actual="+string.Join(",",color)+" expected="+string.Join(",",expected));}
     bodyIndex++;
    }
   }
   File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS automatic native coilover splitting, member ownership and multi-body appearances");app.CommandInProgress=false;return;
  }
  doc.ClearSelection2(true);var manager=(SelectionMgr)doc.SelectionManager;var selectData=manager.CreateSelectData();selectData.Mark=1;
  for(int i=0;i<2;i++){
   object info;var bodies=(object[])instances[i].GetBodies3(0,out info);var body=(Body2)bodies[0];
   var entity=kind=="point"?(Entity)((object[])body.GetVertices()).Cast<Vertex>().OrderBy(v=>string.Join(",",(double[])v.GetPoint())).First():
    (Entity)((object[])body.GetFaces()).Cast<Face2>().Single(f=>((Surface)f.GetSurface()).IsCylinder());
   Check(entity.Select4(i>0,selectData),"select native mate geometry "+i);
  }
  int mateError=0;var mate=((AssemblyDoc)doc).AddMate5((int)(kind=="point"?swMateType_e.swMateCOINCIDENT:swMateType_e.swMateCONCENTRIC),0,false,0,0,0,0,0,0,0,0,false,kind=="rack",0,out mateError);
  Check(mate!=null&&mateError==(int)swAddMateError_e.swAddMateError_NoError,"create native "+kind+" mate; status="+mateError);
  if(kind=="hinge"){
   doc.ClearSelection2(true);
   for(int i=0;i<2;i++){object info;var body=(Body2)((object[])instances[i].GetBodies3(0,out info))[0];var face=((object[])body.GetFaces()).Cast<Face2>().Where(f=>((Surface)f.GetSurface()).IsPlane()).OrderBy(f=>((double[])f.GetBox())[2]).First();Check(((Entity)face).Select4(i>0,selectData),"select axial stop "+i);}
   mate=((AssemblyDoc)doc).AddMate5((int)swMateType_e.swMateCOINCIDENT,0,false,0,0,0,0,0,0,0,0,false,false,0,out mateError);Check(mate!=null&&mateError==1,"create hinge axial stop");
  }
  doc.EditRebuild3();Save(doc,path);Call(project,"Save");
  var first=(IList)Scan(code,app,doc,project,Path.Combine(folder,"snapshot.json"));Check(first.Count==(kind=="hinge"?2:1),"native mate count captured");
  Check(Get(first[0],"Issue")==null&&((IList)Get(first[0],"Entities")).Count==2,"both mate entities resolve to owned CAD geometry");
  var firstId=(string)Get(first[0],"Id");
  doc.ClearSelection2(true);doc.ShowNamedView2("*Isometric",7);doc.ViewZoomtofit2();doc.GraphicsRedraw2();Application.DoEvents();
  var bmp=Path.Combine(folder,"native-joints.bmp");if(doc.SaveBMP(bmp,0,0)){using(var image=new System.Drawing.Bitmap(bmp))image.Save(Path.Combine(folder,"native-joints.png"));File.Delete(bmp);}
  app.CloseDoc(doc.GetTitle());int warning=0;doc=(ModelDoc2)app.OpenDoc6(path,2,1,"",ref error,ref warning);Check(doc!=null,"native assembly reopens");app.ActivateDoc3(doc.GetTitle(),false,0,ref error);
  project=code.GetType("BeamNG.Cad.Preparation.VehicleProject").GetMethod("Load").Invoke(null,new object[]{path+".beamng-project.json"});
  var second=(IList)Scan(code,app,doc,project,Path.Combine(folder,"reopened.json"));Check(second.Count==first.Count&&(string)Get(second[0],"Id")==firstId&&Get(second[0],"Issue")==null,"mate identity and ownership survive close/reopen");
  var preferences=Create(code,"UI.ExporterSettings",Path.Combine(folder,"ui-settings.xml"));
  using(var form=(Form)Create(code,"UI.ComponentWorkflow",app,doc,preferences)){
   form.Show();Application.DoEvents();var tabs=(TabControl)form.Controls.Find("WorkflowPages",true).Single();
   var page=tabs.TabPages.Cast<TabPage>().Single(p=>p.Text=="Joints & mounts");tabs.SelectedTab=page;Application.DoEvents();
   Check(!tabs.TabPages.Cast<TabPage>().Any(p=>p.Text=="Mounting points"||p.Text=="Connections"||p.Text=="Reference skeleton"),"native workflow has one unified top-level joints page");
   Check(page.Controls.Find("JointRequests",true).Single().ClientSize.Width>100,"native workflow joint request list is visible");
   using(var bitmap=new System.Drawing.Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new System.Drawing.Rectangle(0,0,bitmap.Width,bitmap.Height));bitmap.Save(Path.Combine(folder,"native-workflow.png"));}
  }
  File.WriteAllText(Path.Combine(folder,"result.txt"),"PASS native "+kind+" mate extraction and persisted ownership");app.CommandInProgress=false;
 }
}
'@
Add-Type -ReferencedAssemblies $refs -TypeDefinition $source
$existing=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | ForEach-Object Id)
$ownedPid=$null
try {
 $process=Start-Process -FilePath (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS\sldworks.exe') -ArgumentList '/r' -WindowStyle Hidden -PassThru
 $ownedPid=$process.Id
 if($existing -contains $ownedPid){throw 'Refusing existing user process'}
 $until=(Get-Date).AddSeconds(120)
 do {$app=[SyntheticNativeCad]::Find($ownedPid);if(-not $app){Start-Sleep -Milliseconds 500}}while(-not $app -and (Get-Date) -lt $until)
 if(-not $app){throw 'Owned SolidWorks did not register'}
 Write-Output "OWNED_CAD_PROCESS=$ownedPid"
 [SyntheticNativeCad]::GuardOwnedPrompt($ownedPid)
 [NativeJointsTest]::Run($app,(Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination,$Kind)
} catch {
 [IO.File]::WriteAllText((Join-Path $Destination 'failure.txt'),($_ | Out-String))
 Write-Warning ('Native fixture failed: '+$_.Exception.Message)
 throw
} finally {
 if($ownedPid -and $existing -notcontains $ownedPid){
  try{if($app){[SyntheticNativeCad]::Finish($app)}}catch{Write-Warning ('Owned cleanup: '+$_.Exception.Message)}
  $remaining=Get-Process -Id $ownedPid -ErrorAction SilentlyContinue
  if($remaining -and -not $remaining.WaitForExit(10000)){Stop-Process -Id $ownedPid -ErrorAction SilentlyContinue}
 }
}
