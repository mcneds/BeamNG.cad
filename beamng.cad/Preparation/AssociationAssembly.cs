using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    // Independent native geometry. No Save Bodies / in-context features are inserted
    // into source documents, and no source document is ever saved or closed here.
    internal sealed partial class AssociationAssembly
    {
        [DataContract] internal sealed class Receipt
        {
            [DataMember] public string Format="beamng-association-assembly";
            [DataMember] public int Version=4;
            [DataMember] public string SourceProject,SourceDocument,Configuration,Assembly,Project;
            [DataMember] public string Status="incomplete";
            [DataMember] public List<Group> Groups=new List<Group>();
            [DataMember] public List<string> Notes=new List<string>();
            [DataMember] public List<ComponentDefinition> SourceComponents;
            [DataMember] public List<MvpTemplateChoice> SourceTemplates;
            [DataMember] public string PreviousAssembly;
        }
        [DataContract] internal sealed class Group
        {
            [DataMember] public string Id,Name,Part;
            [DataMember] public List<string> SourceBodies=new List<string>();
            [DataMember] public List<string> CopiedBodies=new List<string>();
            [DataMember] public Dictionary<string,string[]> Scopes=new Dictionary<string,string[]>();
            [DataMember] public string ComponentReference;
            [DataMember] public List<Group> Members=new List<Group>();
            // A reviewed replacement is owned by the companion. Root-source
            // assignment/geometry refresh must not overwrite it or its mates.
            [DataMember] public bool SourceOverride;
            [DataMember] public string SourceDocument,SourceProject,SourceConfiguration;
            // Native part copies retain local coordinates; ordinary body exports
            // bake the source instance transform into their geometry.
            [DataMember] public bool NativePartCopy,AppearanceSnapshot;
        }
        public sealed class Result
        {
            public ModelDoc2 Document;
            public VehicleProject Project;
            public string ReceiptPath;
        }
        private sealed class BodyCopy
        {
            public Body2 Geometry;
            public Dictionary<int,double[]> FaceColors=new Dictionary<int,double[]>();
            public ILookup<string,double[]> Finishes;
            public Dictionary<int,NativeAppearance> NativeFinishes=new Dictionary<int,NativeAppearance>();
            public ILookup<string,NativeAppearance> NativeKeys;
        }
        private readonly ISldWorks app;
        private readonly ModelDoc2 source;
        private SolidWorksAppearances.Scene appearanceScene;
        // Moving-member replacement consumes copied parts, not an intermediate
        // assembly. Avoid creating a native document window only to destroy it.
        private bool copyPartsOnly;
        private int nextCopiedFaceId;
        public AssociationAssembly(ISldWorks app,ModelDoc2 source){this.app=app;this.source=source;}
        private static string Reference(ModelDoc2 document,object entity)
        {
            var bytes=document.Extension.GetPersistReference3(entity) as byte[];
            if(bytes==null||bytes.Length==0)throw new InvalidOperationException("Native geometry has no persistent reference.");
            return Convert.ToBase64String(bytes);
        }
        private static string Key(ModelDoc2 document,Tuple<Component2,Body2> body)=>Reference(document,body.Item1)+"|"+Reference(document,body.Item2);
        private static string SafeName(string name)
        {
            var value=Regex.Replace(name??"Group","[^a-zA-Z0-9_-]+","_").Trim('_');
            return string.IsNullOrEmpty(value)?"Group":value.Substring(0,Math.Min(48,value.Length));
        }
        private void Activate(ModelDoc2 document)
        {
            int error=0;var activated=app.ActivateDoc3(document.GetTitle(),false,(int)swRebuildOnActivation_e.swDontRebuildActiveDoc,ref error);
            if(activated==null||app.IsSame(activated,document)!=(int)swObjectEquality.swObjectSame)
                throw new InvalidOperationException("Could not activate "+document.GetTitle()+" ("+error+").");
        }
        private static void Save(ModelDoc2 document,string path)
        {
            int error=0,warning=0;
            if(!document.Extension.SaveAs(path,0,(int)swSaveAsOptions_e.swSaveAsOptions_Silent,null,ref error,ref warning)||error!=0)
                throw new IOException("Could not save working CAD: "+path+" ("+error+").");
        }
        private ModelDoc2 NewBackgroundPart(string template)
        {
            var type=(int)swDocumentTypes_e.swDocPART;
            var visible=app.GetDocumentVisible(type);
            try
            {
                app.DocumentVisible(false,type);
                return (ModelDoc2)app.NewDocument(template,0,0,0);
            }
            finally { app.DocumentVisible(visible,type); }
        }
        private ModelDoc2 OpenBackgroundPart(string path,ref int error,ref int warning)
        {
            var type=(int)swDocumentTypes_e.swDocPART;
            var visible=app.GetDocumentVisible(type);
            try
            {
                app.DocumentVisible(false,type);
                return (ModelDoc2)app.OpenDoc6(path,type,(int)swOpenDocOptions_e.swOpenDocOptions_Silent,"",ref error,ref warning);
            }
            finally { app.DocumentVisible(visible,type); }
        }
        private static IEnumerable<Tuple<string,FrameAssignment,string>> Scopes(ComponentDefinition c)
        {
            if(c.Selections?.Count>0)yield return Tuple.Create("cad",new FrameAssignment {Configuration=c.Configuration,Selections=c.Selections},c.CadSourceDocument);
            if(c.AppearanceSelections?.Count>0)yield return Tuple.Create("appearance",new FrameAssignment {Configuration=c.AppearanceConfiguration,Selections=c.AppearanceSelections},c.AppearanceSourceDocument);
            foreach(var piece in c.AppearanceCoilover?.Pieces??new List<CoiloverMeshAssignment>())
                if(piece.Selections?.Count>0)yield return Tuple.Create("coilover:"+piece.Kind,CoiloverAppearance.Assignment(piece),piece.SourceDocument);
        }
        private static double[] Color(VisualAppearance appearance)=>new[]{appearance.BaseColor[0],appearance.BaseColor[1],appearance.BaseColor[2],.3,.8,.3,1-appearance.Roughness,1-appearance.BaseColor[3],0};
        private static string FaceKey(Face2 face)=>string.Join("|",((double[])face.GetBox()).Concat(new[]{face.GetArea()}).Select(x=>Math.Round(x,9).ToString("G17",CultureInfo.InvariantCulture)));
        private BodyCopy CopyBody(Tuple<Component2,Body2> pair,List<string> notes)
        {
            // Rebind detached appearances/materials to destination entities rather
            // than carrying native attributes owned by the source document.
            var copy=(Body2)pair.Item2.Copy2(false);
            if(copy==null)throw new InvalidOperationException("Could not copy body "+pair.Item2.Name);
            try
            {
                // Match in the unchanged part coordinates before applying placement.
                // Never stamp face IDs or appearance properties on the source body.
                var reader=new SolidWorksAppearances(app,pair.Item1,pair.Item2,appearanceScene);
                var colors=((object[])pair.Item2.GetFaces()).Cast<Face2>().ToLookup(FaceKey);
                var native=new List<Tuple<RenderMaterial,NativeAppearance>>();
                var result=new BodyCopy {Geometry=copy};
                var capturedFaces=new List<Tuple<Face2,double[],NativeAppearance>>();
                foreach(Face2 face in (object[])copy.GetFaces())
                {
                    var originals=colors[FaceKey(face)].ToArray();var matches=originals.Select(reader.Read).ToArray();
                    var faceId=++nextCopiedFaceId;
                    face.SetFaceId(faceId); // Unique throughout this generated part, never on source geometry.
                    if(matches.Length>0&&matches.All(a=>SolidWorksAppearances.Same(a,matches[0])))
                    {
                        var color=Color(matches[0]);result.FaceColors.Add(faceId,color);NativeAppearance captured=null;
                        var finish=reader.ReadNative(originals[0]);
                        if(finish!=null)
                        {
                            captured=native.FirstOrDefault(n=>app.IsSame(n.Item1,finish)==(int)swObjectEquality.swObjectSame)?.Item2;
                            if(captured==null){captured=new NativeAppearance(finish);native.Add(Tuple.Create(finish,captured));}
                            result.NativeFinishes.Add(faceId,captured);
                        }
                        capturedFaces.Add(Tuple.Create(face,color,captured));
                    }
                    else notes.Add(pair.Item1.Name2+" / "+pair.Item2.Name+": an ambiguous face finish kept its native copied appearance.");
                }
                if(pair.Item1.Transform2!=null&&!copy.ApplyTransform(pair.Item1.Transform2))throw new InvalidOperationException("Could not preserve body placement: "+pair.Item2.Name);
                // Temporary bodies do not reliably retain visual property setters.
                // Keep the captured values in managed data until the native part exists.
                // Temporary/imported face IDs can be cleared by SolidWorks.
                // Retain the captured face wrappers through placement instead
                // of rebuilding these lookups from IDs that may now be zero.
                result.Finishes=capturedFaces.ToLookup(f=>FaceKey(f.Item1),f=>f.Item2);
                result.NativeKeys=capturedFaces.Where(f=>f.Item3!=null).ToLookup(f=>FaceKey(f.Item1),f=>f.Item3);
                return result;
            }
            catch{Marshal.ReleaseComObject(copy);throw;}
        }
        private static void ClearArtifacts(ComponentDefinition c)
        {
            c.GeometryDirectory=null;c.AppearanceDirectory=null;c.AppearancePackageState=null;c.AppearancePackageError=null;
            foreach(var piece in c.AppearanceCoilover?.Pieces??new List<CoiloverMeshAssignment>())piece.GeometryDirectory=null;
        }
        public async Task<Result> Create(VehicleProject project,string folder,Action<int,string> progress,CancellationToken token)
        {
            var selection=new FrameSelection(app,source,true);selection.ValidateDocument();
            if(!ComponentAssignments.SameDocument(project.SourceDocument,selection.Document))throw new InvalidOperationException("This project belongs to another assembly.");
            // Freeze the saved project, with no modification of the caller's objects.
            var snapshot=VehicleProject.Load(project.FilePath);
            appearanceScene=new SolidWorksAppearances.Scene(source);
            foreach(var c in snapshot.Components)foreach(var scope in Scopes(c))
            {
                if(!string.IsNullOrEmpty(scope.Item3)&&!ComponentAssignments.SameDocument(scope.Item3,selection.Document))
                    throw new InvalidOperationException(c.Name+": this assignment comes from another CAD document. Reassign it in the active assembly before making a working copy.");
                if(scope.Item2.Configuration!=selection.Configuration)throw new InvalidOperationException(c.Name+": activate its assigned configuration before making a working copy.");
            }
            if(!snapshot.Components.Any(c=>Scopes(c).Any()))throw new InvalidOperationException("Assign CAD geometry to at least one group first.");
            var partTemplate=app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart);
            var assemblyTemplate=app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateAssembly);
            if(!File.Exists(partTemplate)||!File.Exists(assemblyTemplate))throw new InvalidOperationException("Set default SolidWorks part and assembly templates first.");
            folder=Path.GetFullPath(folder);
            if(Directory.Exists(folder)||File.Exists(folder))throw new IOException("Choose a new working folder. Existing files are preserved.");
            var suffix=Guid.NewGuid().ToString("N").Substring(0,8);
            var path=Path.Combine(folder,SafeName(Path.GetFileNameWithoutExtension(source.GetPathName()))+"_working_"+suffix+".SLDASM");
            if(path.Length>220)throw new IOException("Choose a shorter working folder path for native CAD files.");
            Directory.CreateDirectory(folder);
            var baseline=VehicleProject.Load(project.FilePath);
            var receipt=new Receipt {SourceProject=project.FilePath,SourceDocument=selection.Document,Configuration=selection.Configuration,Assembly=path,Project=VehicleProject.PathFor(path),SourceComponents=baseline.Components,SourceTemplates=baseline.MvpTemplates};
            receipt.Notes.Add("Independent geometry snapshot. Native face appearances, exposed finish/mapping properties and available texture assets are copied; decals are not transferred. Native physical material assignments are copied separately.");
            var receiptPath=Path.Combine(folder,"working-assembly.json");JsonFile.Write(receiptPath,receipt);
            var owned=new List<ModelDoc2>();ModelDoc2 assembly=null;
            var success=false;
            try
            {
                using(var quiet=new MaterialUiUpdateScope(app))
                {
                    quiet.CoverDocumentTransitions();
                    for(var index=0;index<snapshot.Components.Count;index++)
                    {
                        token.ThrowIfCancellationRequested();var c=snapshot.Components[index];
                        progress?.Invoke(index*80/snapshot.Components.Count,"Copying "+c.Name+" ("+(index+1)+" / "+snapshot.Components.Count+")");
                        quiet.SetStatus("Creating working assembly: "+c.Name);
                        Activate(source);
                        var group=new Group {Id=c.Id,Name=c.Name};
                        var unique=new Dictionary<string,Tuple<Component2,Body2>>();
                        foreach(var scope in Scopes(c))
                        {
                            var bodies=selection.SnapshotBodies(scope.Item2);var keys=new List<string>();
                            foreach(var pair in bodies){var key=Key(source,pair);unique[key]=pair;keys.Add(key);}
                            group.Scopes.Add(scope.Item1,keys.ToArray());
                        }
                        ClearArtifacts(c);
                        if(unique.Count==0){receipt.Notes.Add(c.Name+": unassigned group retained without geometry.");continue;}
                        group.Part=Path.Combine(folder,(index+1).ToString("D3")+"_"+SafeName(c.Name)+"_"+suffix+".SLDPRT");
                        var copies=new List<Tuple<string,BodyCopy,BodyMaterial>>();
                        nextCopiedFaceId=0;
                        try
                        {
                            var materials=new SolidWorksMaterials(app);
                            foreach(var pair in unique)
                            {
                                token.ThrowIfCancellationRequested();
                                var material=materials.Read(pair.Value.Item1,pair.Value.Item2,pair.Key);
                                // Preserve a missing/unsupported assignment as such, never substitute steel.
                                if(material.Error!=null)receipt.Notes.Add(c.Name+" / "+pair.Value.Item2.Name+": "+material.Error);
                                copies.Add(Tuple.Create(pair.Key,CopyBody(pair.Value,receipt.Notes),material));
                            }
                            // These generated parts need geometry/material APIs,
                            // not document windows. Restore the creation setting
                            // immediately, including when native creation fails.
                            var part=NewBackgroundPart(partTemplate)??throw new InvalidOperationException("Could not create working part.");owned.Add(part);
                            if((((PartDoc)part).GetBodies2((int)swBodyType_e.swAllBodies,false) as object[])?.Length>0)
                                throw new InvalidOperationException("Choose an empty default part template before creating a working assembly.");
                            ((PartDoc)part).SetMaterialPropertyName2(part.ConfigurationManager.ActiveConfiguration.Name,"","");
                            var bodyIndex=0;var imported=new List<Tuple<string,BodyCopy>>();
                            foreach(var copy in copies)
                            {
                                token.ThrowIfCancellationRequested();
                                var feature=((PartDoc)part).CreateFeatureFromBody3(copy.Item2.Geometry,false,(int)swCreateFeatureBodyOpts_e.swCreateFeatureBodyCheck) as Feature;
                                if(feature==null)throw new InvalidOperationException(c.Name+": native body import failed.");
                                var body=(Body2)feature.GetBody();
                                if(body==null)throw new InvalidOperationException(c.Name+": imported feature has no body.");
                                var bodyName="TaggedBody_"+(++bodyIndex).ToString("D4");body.Name=bodyName;
                                if(body.Name!=bodyName)throw new InvalidOperationException("Native body name was not retained.");
                                group.SourceBodies.Add(copy.Item1);group.CopiedBodies.Add(bodyName);
                                if(!string.IsNullOrWhiteSpace(copy.Item3.Name)&&!string.IsNullOrWhiteSpace(copy.Item3.Database))
                                {
                                    if(!body.Select2(false,null))throw new InvalidOperationException("Could not select imported body for material assignment.");
                                    var applied=body.SetMaterialProperty(part.ConfigurationManager.ActiveConfiguration.Name,Path.GetFileName(copy.Item3.Database),copy.Item3.Name);
                                    string db;var assigned=body.GetMaterialPropertyName(part.ConfigurationManager.ActiveConfiguration.Name,out db);
                                    if(applied!=1||assigned!=copy.Item3.Name)throw new InvalidOperationException(c.Name+": could not preserve physical material "+copy.Item3.Name+" (status "+applied+")");
                                    part.ClearSelection2(true);
                                }
                                imported.Add(Tuple.Create(bodyName,copy.Item2));
                            }
                            // Commit imported topology before binding appearances.
                            part.ClearSelection2(true);part.ForceRebuild3(false);Save(part,group.Part);
                            var savedBodies=((object[])((PartDoc)part).GetBodies2((int)swBodyType_e.swAllBodies,false))
                                .Cast<Body2>().ToDictionary(b=>b.Name);
                            // Restore visual finishes after all body imports and
                            // physical material assignments have completed.
                            foreach(var importedBody in imported)
                            {
                                token.ThrowIfCancellationRequested();
                                var body=savedBodies[importedBody.Item1];var copied=importedBody.Item2;var finishes=copied.Finishes;
                                var nativeFaces=new Dictionary<NativeAppearance,List<Face2>>();
                                foreach(Face2 face in (object[])body.GetFaces())
                                {
                                    var values=finishes[FaceKey(face)].ToArray();
                                    if(copied.FaceColors.TryGetValue(face.GetFaceId(),out var color))face.MaterialPropertyValues=color;
                                    else if(values.Length>0&&values.All(v=>v.SequenceEqual(values[0])))face.MaterialPropertyValues=values[0];
                                    else receipt.Notes.Add(c.Name+" / "+body.Name+": an imported face finish could not be mapped uniquely.");
                                    var candidates=copied.NativeKeys[FaceKey(face)].Distinct().ToArray();
                                    if(!copied.NativeFinishes.TryGetValue(face.GetFaceId(),out var finish)&&candidates.Length==1)finish=candidates[0];
                                    if(finish!=null)
                                    {if(!nativeFaces.TryGetValue(finish,out var faces))nativeFaces.Add(finish,faces=new List<Face2>());faces.Add(face);}
                                }
                                foreach(var finish in nativeFaces)finish.Key.Apply(part,finish.Value,folder,receipt.Notes);
                            }
                            part.ClearSelection2(true);int finishError=0,finishWarning=0;
                            if(!part.Save3((int)swSaveAsOptions_e.swSaveAsOptions_Silent,ref finishError,ref finishWarning)||finishError!=0)
                                throw new IOException("Could not save copied appearances: "+group.Part+" ("+finishError+").");
                            // Closing an active generated part makes SolidWorks
                            // destroy its window and implicitly choose the next
                            // document in one native callback. Activate the stable
                            // source first, then close the now inactive copy.
                            Activate(source);
                            app.CloseDoc(part.GetTitle());owned.Remove(part);
                            receipt.Groups.Add(group);JsonFile.Write(receiptPath,receipt);
                        }
                        finally {foreach(var copy in copies)Marshal.ReleaseComObject(copy.Item2.Geometry);}
                        await Task.Yield();
                    }
                    token.ThrowIfCancellationRequested();
                    if(copyPartsOnly)
                    {
                        receipt.Status="parts_completed";JsonFile.Write(receiptPath,receipt);
                        JsonFile.Write(Path.Combine(folder,"appearance-provenance.json"),receipt);success=true;
                        progress?.Invoke(100,"Moving member parts copied");
                        return new Result {ReceiptPath=receiptPath};
                    }
                    progress?.Invoke(82,"Assembling tagged groups");quiet.SetStatus("Assembling tagged groups");
                    assembly=(ModelDoc2)app.NewDocument(assemblyTemplate,0,0,0)??throw new InvalidOperationException("Could not create working assembly.");owned.Add(assembly);
                    if((((AssemblyDoc)assembly).GetComponents(false) as object[])?.Length>0)
                        throw new InvalidOperationException("Choose an empty default assembly template before creating a working assembly.");
                    Save(assembly,path);
                    var newSelection=new FrameSelection(app,assembly,true);
                    var configuration=assembly.ConfigurationManager.ActiveConfiguration.Name;
                    var instances=new Dictionary<string,Component2>();
                    foreach(var group in receipt.Groups)
                    {
                        token.ThrowIfCancellationRequested();int error=0,warning=0;
                        var part=OpenBackgroundPart(group.Part,ref error,ref warning);
                        if(part==null)throw new IOException("Could not load working part: "+group.Part);owned.Add(part);
                        Activate(assembly);
                        var instance=((AssemblyDoc)assembly).AddComponent5(group.Part,0,"",false,"",0,0,0)??throw new InvalidOperationException("Could not insert "+group.Name);
                        instance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(new[]{1d,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0});
                        assembly.ClearSelection2(true);if(!instance.Select4(false,null,false))throw new InvalidOperationException("Could not fix "+group.Name);
                        ((AssemblyDoc)assembly).FixComponent();instances.Add(group.Id,instance);
                        app.CloseDoc(part.GetTitle());owned.Remove(part);
                    }
                    Activate(assembly);Save(assembly,path);assembly.ClearSelection2(true);
                    foreach(var group in receipt.Groups)
                    {
                        var c=snapshot.Components.Single(item=>item.Id==group.Id);var instance=instances[group.Id];
                        group.ComponentReference=Reference(assembly,instance);
                        object info;var bodies=((object[])instance.GetBodies3((int)swBodyType_e.swAllBodies,out info)).Cast<Body2>().ToDictionary(b=>b.Name);
                        foreach(var scope in group.Scopes)
                        {
                            var refs=scope.Value.Select(key=>{
                                var body=bodies[group.CopiedBodies[group.SourceBodies.IndexOf(key)]];
                                return new SelectionReference {Kind="body",Name=group.Name+" / "+body.Name,Reference=Reference(assembly,body),ComponentReference=Reference(assembly,instance)};
                            }).ToList();
                            var ids=newSelection.BodyIds(new FrameAssignment {Configuration=configuration,Selections=refs});
                            if(scope.Key=="cad"){c.Selections=refs;c.BodyIds=ids;c.Configuration=configuration;c.CadSourceDocument=path;}
                            else if(scope.Key=="appearance"){c.AppearanceSelections=refs;c.AppearanceConfiguration=configuration;c.AppearanceSourceDocument=path;c.AppearancePackageState="pending";}
                            else {var piece=c.AppearanceCoilover.Pieces.Single(p=>"coilover:"+p.Kind==scope.Key);piece.Selections=refs;piece.BodyIds=ids;piece.SourceDocument=path;piece.Configuration=configuration;c.AppearancePackageState="pending";}
                        }
                    }
                    token.ThrowIfCancellationRequested();progress?.Invoke(95,"Saving working assignments");
                    // New documents invalidate native face references and build provenance.
                    // Keep names/IDs/connection topology and recorded positions for explicit repair.
                    foreach(var anchor in snapshot.Anchors){anchor.Status="needs_repair";anchor.References.Clear();anchor.BodyReferences?.Clear();anchor.ComponentReference=null;}
                    if(snapshot.Anchors.Count>0)receipt.Notes.Add(snapshot.Anchors.Count+" mounting points retained with their connections and recorded coordinates; use Repair selected point to bind them to the copied CAD.");
                    var copyProject=VehicleProject.Open(path);
                    copyProject.Components=snapshot.Components;copyProject.Anchors=snapshot.Anchors;copyProject.Connections=snapshot.Connections;copyProject.MvpTemplates=snapshot.MvpTemplates;
                    copyProject.JointWorkspace=snapshot.JointWorkspace;
                    copyProject.JointWorkspace.Invalidate(snapshot.Components.Select(c=>c.Id),"Copied CAD needs new native joint references");
                    // A reviewed definition is editable input, but its old source identities are not acceptance evidence.
                    if(File.Exists(snapshot.TemplateDefinitionPath))
                    {
                        copyProject.TemplateDefinitionPath=Path.Combine(folder,"template-definition.json");File.Copy(snapshot.TemplateDefinitionPath,copyProject.TemplateDefinitionPath);
                        receipt.Notes.Add("Template definition copied for review. Recheck its hardpoints and recalibrate against this CAD before generating physics.");
                    }
                    var profile=FramePipeline.ModProfile.Load(project.ProfilePath);
                    if(!File.Exists(profile.PreviewImage))profile.PreviewImage="";
                    profile.Save(copyProject.ProfilePath);
                    foreach(var c in copyProject.Components.Where(c=>c.Template=="calibrated_frame"&&c.Selections.Count>0))
                        PreparationFile.Load(path).Save(new FrameAssignment {Id=c.Id,Configuration=configuration,Selections=c.Selections,Hull=c.Hull});
                    copyProject.Save();Save(assembly,path);
                    receipt.Status="completed";JsonFile.Write(receiptPath,receipt);
                    JsonFile.Write(Path.Combine(folder,"appearance-provenance.json"),receipt);success=true;
                    var result=new Result {Document=assembly,Project=copyProject,ReceiptPath=receiptPath};
                    var splitOwners=copyProject.Components.Where(c=>CoiloverAppearance.Active(c)&&AssignedCoiloverMembers(c)!=null).Select(c=>c.Id).ToArray();
                    foreach(var c in copyProject.Components.Where(c=>CoiloverAppearance.Active(c)&&AssignedCoiloverMembers(c)==null))
                        receipt.Notes.Add(c.Name+": moving pieces remain combined because housing/shaft/spring assignments do not partition every physical body. Review Moving members.");
                    JsonFile.Write(receiptPath,receipt);
                    for(var i=0;i<splitOwners.Length;i++)
                    {
                        token.ThrowIfCancellationRequested();var owner=result.Project.Components.Single(c=>c.Id==splitOwners[i]);
                        var members=AssignedCoiloverMembers(owner);
                        result.Project.JointWorkspace.Members.RemoveAll(m=>m.ComponentId==owner.Id);
                        result.Project.JointWorkspace.Members.AddRange(members);result.Project.Save();
                        var index=i;
                        result=await new AssociationAssembly(app,result.Document).SplitMembers(result.Project,receiptPath,owner.Id,
                            (value,message)=>progress?.Invoke(95+(index*5+value*5/100)/splitOwners.Length,message),token);
                        assembly=result.Document;
                    }
                    progress?.Invoke(100,"Working assembly ready"+(splitOwners.Length==0?"":"; coilover moving pieces separated"));
                    return result;
                }
            }
            finally
            {
                if(!success)
                {
                    foreach(var document in owned.AsEnumerable().Reverse())try{app.CloseDoc(document.GetTitle());}catch{}
                    Activate(source);
                }
                else if(assembly!=null){Activate(assembly);assembly.ShowNamedView2("*Isometric",7);assembly.ViewZoomtofit2();assembly.GraphicsRedraw2();}
                else Activate(source);
            }
        }
    }
}
