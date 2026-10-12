using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    internal sealed partial class AssociationAssembly
    {
        private sealed class FacePaint
        {
            public VisualAppearance Visual;
            public NativeAppearance Native;
        }
        private sealed class PaintChange
        {
            public ModelDoc2 Part;
            public Face2 Face;
            public FacePaint Before,After;
            public string Reference,Geometry;
            public double[] BeforeLegacy;
        }
        private sealed class AppearanceSource : IDisposable
        {
            private readonly AssociationAssembly owner;
            private readonly Dictionary<string,ModelDoc2> documents=new Dictionary<string,ModelDoc2>(StringComparer.OrdinalIgnoreCase);
            private readonly Dictionary<string,SolidWorksAppearances.Scene> scenes=new Dictionary<string,SolidWorksAppearances.Scene>(StringComparer.OrdinalIgnoreCase);
            private readonly List<ModelDoc2> opened=new List<ModelDoc2>();
            private readonly Dictionary<RenderMaterial,NativeAppearance> snapshots=new Dictionary<RenderMaterial,NativeAppearance>();
            public AppearanceSource(AssociationAssembly owner){this.owner=owner;}
            private ModelDoc2 Document(Receipt receipt)
            {
                var path=Path.GetFullPath(receipt.SourceDocument);
                if(!documents.TryGetValue(path,out var document))
                {
                    document=owner.app.GetOpenDocumentByName(path) as ModelDoc2;
                    if(document==null)
                    {
                        int error=0,warning=0;
                        document=owner.app.OpenDoc6(path,(int)swDocumentTypes_e.swDocASSEMBLY,
                            (int)(swOpenDocOptions_e.swOpenDocOptions_Silent|swOpenDocOptions_e.swOpenDocOptions_ReadOnly),receipt.Configuration,ref error,ref warning) as ModelDoc2
                            ??throw new IOException("Cannot open original appearance source: "+path+" ("+error+").");
                        opened.Add(document);
                    }
                    documents.Add(path,document);
                }
                if(document.ConfigurationManager.ActiveConfiguration.Name!=receipt.Configuration)
                    throw new InvalidOperationException("Activate source configuration '"+receipt.Configuration+"' in "+path+" before refreshing appearances.");
                return document;
            }
            private static IEnumerable<Group> Flatten(IEnumerable<Group> groups)
            {
                foreach(var group in groups)
                    if(group.Members?.Count>0){foreach(var member in Flatten(group.Members))yield return member;}
                    else yield return group;
            }
            public Dictionary<string,FacePaint> Read(ModelDoc2 document,Component2 instance,Body2 body,HashSet<string> chain,CancellationToken token,bool useSnapshot=false)
            {
                token.ThrowIfCancellationRequested();
                var partPath=Path.GetFullPath(instance.GetPathName());
                var identity=document.GetPathName()+"|"+partPath+"|"+body.Name;
                if(!chain.Add(identity))throw new InvalidDataException("Appearance provenance contains a cycle: "+body.Name);
                try
                {
                    var receiptPath=partPath+".appearance-provenance.json";
                    if(!File.Exists(receiptPath))receiptPath=Path.Combine(Path.GetDirectoryName(partPath),"appearance-provenance.json");
                    if(!File.Exists(receiptPath))receiptPath=Path.Combine(Path.GetDirectoryName(partPath),"working-assembly.json");
                    if(!useSnapshot&&File.Exists(receiptPath))
                    {
                        // Use the immutable part-copy record, not promoted links to
                        // a newer companion, which can point back to this revision.
                        var receipt=JsonFile.Read<Receipt>(receiptPath);
                        if(receipt.Format!="beamng-association-assembly"||
                            (receipt.Status!="completed"&&receipt.Status!="parts_completed"))
                            throw new InvalidDataException("Incomplete appearance provenance: "+receiptPath);
                        var groups=Flatten(receipt.Groups).Where(g=>ComponentAssignments.SameDocument(g.Part,partPath)&&g.CopiedBodies.Contains(body.Name)).ToArray();
                        if(groups.Length==0&&receipt.SourceComponents!=null)
                        {
                            // Older moving-member revisions promoted the root
                            // receipt and replaced Group.Part with its first
                            // member. The original combined part is retained.
                            // Recover only its exact generated filename and full
                            // copied-body mapping; never guess by a display name.
                            groups=receipt.Groups.Where(g=>{
                                var ordinal=receipt.SourceComponents.FindIndex(c=>c.Id==g.Id);
                                if(ordinal<0||g.SourceBodies.Count!=g.CopiedBodies.Count||!g.CopiedBodies.Contains(body.Name))return false;
                                var prefix=(ordinal+1).ToString("D3")+"_"+SafeName(receipt.SourceComponents[ordinal].Name)+"_";
                                return System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(partPath),"^"+System.Text.RegularExpressions.Regex.Escape(prefix)+@"[0-9a-fA-F]{8}\.SLDPRT$",System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                            }).ToArray();
                        }
                        if(groups.Length!=1)throw new InvalidDataException("Cannot uniquely trace copied body '"+body.Name+"' in "+receiptPath);
                        var group=groups[0];var index=group.CopiedBodies.IndexOf(body.Name);
                        if(index>=group.SourceBodies.Count)throw new InvalidDataException("Incomplete copied-body mapping: "+body.Name);
                        var key=group.SourceBodies[index].Split('|');
                        if(key.Length!=2)throw new InvalidDataException("Invalid source body reference: "+body.Name);
                        var original=Document(AppearanceOrigin(receipt,group));
                        var sourceInstance=Resolve(original,key[0]) as Component2
                            ??throw new InvalidOperationException("Original source component is missing: "+body.Name);
                        sourceInstance=new SelectionNormalizer(original).Available(sourceInstance,true);
                        var sourceBody=Resolve(original,key[1]) as Body2
                            ??throw new InvalidOperationException("Original source body is missing: "+body.Name);
                        var paints=Read(original,sourceInstance,sourceBody,chain,token,group.AppearanceSnapshot);
                        var copy=(Body2)sourceBody.Copy2(false)??throw new InvalidOperationException("Cannot inspect source faces: "+body.Name);
                        var copiedFaces=((object[])copy.GetFaces()).Cast<Face2>().ToArray();
                        var values=copiedFaces.Select(f=>paints[FaceKey(f)]).ToArray();
                        if(!group.NativePartCopy&&sourceInstance.Transform2!=null&&!copy.ApplyTransform(sourceInstance.Transform2))
                            throw new InvalidOperationException("Cannot map source face placement: "+body.Name);
                        var transformed=new Dictionary<string,FacePaint>();
                        for(var i=0;i<copiedFaces.Length;i++)Add(transformed,FaceKey(copiedFaces[i]),values[i]);
                        var destinationFaces=((object[])body.GetFaces()).Cast<Face2>().ToArray();
                        if(destinationFaces.Length!=copiedFaces.Length||!destinationFaces.Select(FaceKey).OrderBy(k=>k).SequenceEqual(copiedFaces.Select(FaceKey).OrderBy(k=>k)))
                            throw new InvalidOperationException(body.Name+": source geometry or placement changed. Appearance-only refresh cannot replace geometry; no paint has been changed.");
                        return transformed;
                    }
                    var sceneKey=document.GetPathName()+"|"+document.ConfigurationManager.ActiveConfiguration.Name;
                    if(!scenes.TryGetValue(sceneKey,out var scene))scenes.Add(sceneKey,scene=new SolidWorksAppearances.Scene(document));
                    var reader=new SolidWorksAppearances(owner.app,instance,body,scene);var result=new Dictionary<string,FacePaint>();
                    foreach(Face2 face in (object[])body.GetFaces())
                    {
                        var native=reader.ReadNative(face);
                        NativeAppearance snapshot=null;
                        if(native!=null&&!snapshots.TryGetValue(native,out snapshot))snapshots.Add(native,snapshot=new NativeAppearance(native));
                        Add(result,FaceKey(face),new FacePaint {Visual=reader.Read(face),Native=snapshot});
                    }
                    return result;
                }
                finally {chain.Remove(identity);}
            }
            private static void Add(Dictionary<string,FacePaint> paints,string key,FacePaint paint)
            {
                if(paints.TryGetValue(key,out var previous)&&!SolidWorksAppearances.Same(previous.Visual,paint.Visual))
                    throw new InvalidOperationException("Coincident source faces have different appearances; refresh cannot map them safely.");
                paints[key]=paint;
            }
            public void Dispose()
            {
                owner.Activate(owner.source);
                try {foreach(var document in opened.AsEnumerable().Reverse())owner.app.CloseDoc(document.GetTitle());}
                finally {owner.Activate(owner.source);}
            }
        }
        private void ClearFacePaint(ModelDoc2 part,IEnumerable<Face2> faces)
        {
            var selected=faces.ToArray();
            // Both sets are in this part's context. Resolve the usual case by
            // persistent face identity instead of an O(faces * entities) COM
            // equality scan. Keep native equality for unusual wrapper identities.
            var references=new HashSet<string>(selected.Select(f=>Reference(part,f)),StringComparer.Ordinal);
            foreach(RenderMaterial material in part.Extension.GetRenderMaterials2((int)swDisplayStateOpts_e.swThisDisplayState,null) as object[]??Array.Empty<object>())
            {
                var entities=material.GetEntities() as object[]??Array.Empty<object>();
                var kept=entities.Where(e=>!(e is Face2)||
                    !(references.Contains(Reference(part,e))||selected.Any(f=>app.IsSame(e,f)==(int)swObjectEquality.swObjectSame))).ToArray();
                if(kept.Length==entities.Length)continue;
                if(kept.Length==0)
                {
                    int first,second;material.GetMaterialIds(out first,out second);
                    if(!part.Extension.DeleteDisplayStateSpecificRenderMaterial(new[]{first},new[]{second}))throw new InvalidOperationException("Cannot remove previous face appearance.");
                }
                else
                {
                    material.RemoveAllEntities();foreach(var entity in kept)if(!material.AddEntity(entity))throw new InvalidOperationException("Cannot preserve neighbouring appearance.");
                }
            }
        }
        private void Paint(ModelDoc2 part,PaintChange[] changes,bool restore,string folder,List<string> notes)
        {
            ClearFacePaint(part,changes.Select(c=>c.Face));
            foreach(var change in changes)
                if(!restore)change.Face.MaterialPropertyValues=Color(change.After.Visual);
                else if(change.BeforeLegacy!=null)change.Face.MaterialPropertyValues=change.BeforeLegacy;
                else change.Face.RemoveMaterialProperty2((int)swInConfigurationOpts_e.swThisConfiguration,null);
            foreach(var batch in changes.Where(c=>(restore?c.Before:c.After).Native!=null).GroupBy(c=>(restore?c.Before:c.After).Native))
                // Live assets belong beside the part, not inside a backup the
                // user may remove later to reclaim disk space.
                batch.Key.Apply(part,batch.Select(c=>c.Face),Path.GetDirectoryName(part.GetPathName()),notes);
            part.Extension.UpdateRenderMaterialsInSceneGraph(true);part.SetSaveFlag();
        }
        public async Task<string> RefreshAppearances(VehicleProject project,string receiptPath,string componentId,Action<int,string> progress,CancellationToken token)
        {
            var receipt=CompanionAssemblyLink.Read(receiptPath);
            if(!ComponentAssignments.SameDocument(receipt.Assembly,source.GetPathName())||!ComponentAssignments.SameDocument(receipt.Project,project.FilePath))
                throw new InvalidOperationException("Open the latest companion before refreshing its appearances.");
            if(source.GetSaveFlag())throw new InvalidOperationException("Save companion CAD first so its folders and mate work are retained.");
            var component=project.Components.Single(c=>c.Id==componentId);
            var selector=new FrameSelection(app,source,true);
            var bodies=Scopes(component).SelectMany(s=>selector.SnapshotBodies(s.Item2)).GroupBy(p=>Key(source,p)).Select(g=>g.First()).ToArray();
            if(bodies.Length==0)throw new InvalidOperationException("Assign CAD bodies to this group first.");
            var changes=new List<PaintChange>();var targetScene=new SolidWorksAppearances.Scene(source);
            var partScenes=new Dictionary<string,SolidWorksAppearances.Scene>(StringComparer.OrdinalIgnoreCase);
            var oldSnapshots=new Dictionary<RenderMaterial,NativeAppearance>();
            using(var originals=new AppearanceSource(this))
            {
                for(var i=0;i<bodies.Length;i++)
                {
                    token.ThrowIfCancellationRequested();var pair=bodies[i];
                    var part=pair.Item1.GetModelDoc2() as ModelDoc2??throw new InvalidOperationException("Resolve the companion part before refreshing.");
                    if(part.GetSaveFlag()||part.IsOpenedReadOnly())throw new InvalidOperationException("Save the companion part and make it writable: "+part.GetPathName());
                    var paints=originals.Read(source,pair.Item1,pair.Item2,new HashSet<string>(StringComparer.OrdinalIgnoreCase),token);
                    var target=((object[])((PartDoc)part).GetBodies2((int)swBodyType_e.swAllBodies,false)).Cast<Body2>().Single(b=>b.Name==pair.Item2.Name);
                    var reader=new SolidWorksAppearances(app,pair.Item1,pair.Item2,targetScene);
                    if(!partScenes.TryGetValue(part.GetPathName(),out var partScene))partScenes.Add(part.GetPathName(),partScene=new SolidWorksAppearances.Scene(part));
                    foreach(Face2 face in (object[])target.GetFaces())
                    {
                        // Rollback must restore face assignments only. Body and
                        // feature finishes remain in place throughout the edit.
                        var native=partScene.Materials.LastOrDefault(m=>m.Item1.Any(e=>e is Face2&&app.IsSame(e,face)==(int)swObjectEquality.swObjectSame))?.Item3;
                        NativeAppearance snapshot=null;if(native!=null&&!oldSnapshots.TryGetValue(native,out snapshot))oldSnapshots.Add(native,snapshot=new NativeAppearance(native));
                        changes.Add(new PaintChange {Part=part,Face=face,Reference=Reference(part,face),Geometry=FaceKey(face),After=paints[FaceKey(face)],BeforeLegacy=face.HasMaterialPropertyValues()?(double[])face.GetMaterialPropertyValues2((int)swInConfigurationOpts_e.swThisConfiguration,null):null,Before=new FacePaint {Visual=reader.Read(face),Native=snapshot}});
                    }
                    progress?.Invoke((i+1)*60/bodies.Length,"Checking original appearances: "+component.Name+" ("+(i+1)+" / "+bodies.Length+")");await Task.Yield();
                }
                token.ThrowIfCancellationRequested();
                if(source.GetSaveFlag()||changes.Any(c=>c.Part.GetSaveFlag()||Resolve(c.Part,c.Reference)==null||FaceKey(c.Face)!=c.Geometry))
                    throw new InvalidOperationException("Companion CAD changed during the appearance check. Save it and retry; no paint has been changed.");
                var folder=Path.Combine(Path.GetDirectoryName(source.GetPathName()),"appearance-backups",DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,6));
                Directory.CreateDirectory(folder);var parts=changes.GroupBy(c=>c.Part.GetPathName(),StringComparer.OrdinalIgnoreCase).ToArray();
                for(var i=0;i<parts.Length;i++)File.Copy(parts[i].Key,Path.Combine(folder,i.ToString("D3")+"_"+Path.GetFileName(parts[i].Key)));
                File.Copy(project.FilePath,Path.Combine(folder,"project-before-refresh.json"));
                var notes=new List<string>();var applied=new List<PaintChange[]>();
                var previousState=component.AppearancePackageState;var previousError=component.AppearancePackageError;
                try
                {
                    foreach(var partChanges in parts)
                    {
                        token.ThrowIfCancellationRequested();var items=partChanges.ToArray();applied.Add(items);Paint(items[0].Part,items,false,folder,notes);
                        foreach(var item in items)if(Resolve(item.Part,item.Reference)==null)throw new InvalidOperationException("Face identity changed while applying appearance; restoring previous finishes.");
                        int error=0,warning=0;if(!items[0].Part.Save3((int)swSaveAsOptions_e.swSaveAsOptions_Silent,ref error,ref warning)||error!=0)throw new IOException("Cannot save refreshed appearances: "+partChanges.Key);
                        progress?.Invoke(60+applied.Count*35/parts.Length,"Restoring colours: "+component.Name);await Task.Yield();
                    }
                    component.AppearancePackageState="pending";component.AppearancePackageError=null;project.Save();
                }
                catch(Exception error)
                {
                    component.AppearancePackageState=previousState;component.AppearancePackageError=previousError;
                    var failures=new List<string>();
                    foreach(var items in applied.AsEnumerable().Reverse())try {Paint(items[0].Part,items,true,folder,notes);int code=0,warning=0;if(!items[0].Part.Save3(1,ref code,ref warning)||code!=0)throw new IOException("Rollback save failed");}catch(Exception rollback){failures.Add(rollback.Message);}
                    throw new InvalidOperationException(error.Message+" Original part backups: "+folder+(failures.Count>0?". Restore failures: "+string.Join("; ",failures):". Previous finishes restored."),error);
                }
                source.GraphicsRedraw2();progress?.Invoke(100,"Source appearances restored; geometry, folders and mate references retained.");return folder;
            }
        }
    }
}
