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
        private sealed class UpdateGroup
        {
            public ComponentDefinition Source,Before;
            public Group Old;
            public Dictionary<string,string[]> Scopes=new Dictionary<string,string[]>();
            public Dictionary<string,string[]> MemberSources=new Dictionary<string,string[]>();
            public bool Replace,Rebind;
        }
        private ModelDoc2 OpenAssembly(string path,out bool opened)
        {
            var document=app.GetOpenDocumentByName(path) as ModelDoc2;opened=document==null;
            if(document!=null)return document;
            int error=0,warning=0;
            return app.OpenDoc6(path,(int)swDocumentTypes_e.swDocASSEMBLY,(int)swOpenDocOptions_e.swOpenDocOptions_Silent,"",ref error,ref warning) as ModelDoc2
                ??throw new IOException("Could not open companion assembly: "+path+" ("+error+").");
        }
        private static object Resolve(ModelDoc2 document,string reference)
        {
            if(string.IsNullOrEmpty(reference))return null;
            int status;var item=document.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out status);
            return status==0?item:null;
        }
        private static Component2 FindInstance(ModelDoc2 assembly,Group group,ComponentDefinition component)
        {
            var saved=Resolve(assembly,group?.ComponentReference) as Component2;
            if(saved!=null)return saved;
            if(component!=null)
                foreach(var scope in Scopes(component))foreach(var item in scope.Item2.Selections)
                {
                    var value=Resolve(assembly,item.Kind=="component"?item.Reference:item.ComponentReference) as Component2;
                    if(value!=null)return value;
                }
            if(group==null)return null;
            var candidates=(((AssemblyDoc)assembly).GetComponents(true) as object[]??Array.Empty<object>()).Cast<Component2>()
                .Where(c=>ComponentAssignments.SameDocument(c.GetPathName(),group.Part)).ToArray();
            if(candidates.Length>1)throw new InvalidOperationException(group.Name+": companion instance is ambiguous. Repair its assignment before updating.");
            return candidates.SingleOrDefault();
        }
        private static readonly HashSet<string> mappedFields=new HashSet<string> {
            "Id","Selections","BodyIds","Configuration","CadSourceDocument","AppearanceSelections","AppearanceConfiguration","AppearanceSourceDocument","AppearanceCoilover"};
        private static void MergeSettings(ComponentDefinition target,ComponentDefinition before,ComponentDefinition next)
        {
            foreach(var field in CompanionAssemblyLink.Fields.Where(f=>!mappedFields.Contains(f.Name)))
                if(before==null||CompanionAssemblyLink.Serialized(field.GetValue(before),field.FieldType)!=CompanionAssemblyLink.Serialized(field.GetValue(next),field.FieldType))
                    field.SetValue(target,field.GetValue(next));
            if(target.AppearanceCoilover!=null&&next.AppearanceCoilover!=null&&
                (before==null||before.AppearanceCoilover?.HousingMount!=next.AppearanceCoilover.HousingMount))
                target.AppearanceCoilover.HousingMount=next.AppearanceCoilover.HousingMount;
        }
        private static void Retarget(ComponentDefinition c,string oldPath,string newPath)
        {
            if(ComponentAssignments.SameDocument(c.CadSourceDocument,oldPath))c.CadSourceDocument=newPath;
            if(ComponentAssignments.SameDocument(c.AppearanceSourceDocument,oldPath))c.AppearanceSourceDocument=newPath;
            foreach(var piece in c.AppearanceCoilover?.Pieces??new List<CoiloverMeshAssignment>())
                if(ComponentAssignments.SameDocument(piece.SourceDocument,oldPath))piece.SourceDocument=newPath;
            ClearArtifacts(c);
        }
        private void BindGroup(ModelDoc2 assembly,Component2 instance,ComponentDefinition c,Group group,UpdateGroup update)
        {
            if(group?.Members?.Count>0){BindMemberGroup(assembly,c,group,update);return;}
            var document=assembly.GetPathName();var configuration=assembly.ConfigurationManager.ActiveConfiguration.Name;
            c.Selections=new List<SelectionReference>();c.BodyIds=new List<string>();c.CadSourceDocument=null;c.Configuration=null;
            c.AppearanceSelections=new List<SelectionReference>();c.AppearanceSourceDocument=null;c.AppearanceConfiguration=null;
            var housingMount=c.AppearanceCoilover?.HousingMount;
            c.AppearanceCoilover=update.Source.AppearanceCoilover;
            if(c.AppearanceCoilover!=null&&housingMount!=null)c.AppearanceCoilover.HousingMount=housingMount;
            if(instance==null)return;
            object info;var bodies=((object[])instance.GetBodies3((int)swBodyType_e.swAllBodies,out info)).Cast<Body2>().ToDictionary(b=>b.Name);
            var selector=new FrameSelection(app,assembly,true);
            group.ComponentReference=Reference(assembly,instance);group.Scopes=update.Scopes;group.Name=c.Name;group.Part=instance.GetPathName();
            foreach(var scope in update.Scopes)
            {
                var refs=scope.Value.Select(key=>{
                    var index=group.SourceBodies.IndexOf(key);
                    if(index<0||!bodies.TryGetValue(group.CopiedBodies[index],out var body))throw new InvalidOperationException(c.Name+": copied body mapping is missing. Enable Refresh assigned geometry too.");
                    return new SelectionReference {Kind="body",Name=c.Name+" / "+body.Name,Reference=Reference(assembly,body),ComponentReference=group.ComponentReference};
                }).ToList();
                var ids=selector.BodyIds(new FrameAssignment {Configuration=configuration,Selections=refs});
                if(scope.Key=="cad"){c.Selections=refs;c.BodyIds=ids;c.Configuration=configuration;c.CadSourceDocument=document;}
                else if(scope.Key=="appearance"){c.AppearanceSelections=refs;c.AppearanceConfiguration=configuration;c.AppearanceSourceDocument=document;c.AppearancePackageState="pending";}
                else {var piece=c.AppearanceCoilover.Pieces.Single(p=>"coilover:"+p.Kind==scope.Key);piece.Selections=refs;piece.BodyIds=ids;piece.Configuration=configuration;piece.SourceDocument=document;piece.GeometryDirectory=null;c.AppearancePackageState="pending";}
            }
        }
        private static bool EqualScopes(Dictionary<string,string[]> a,Dictionary<string,string[]> b)=>a!=null&&a.Count==b.Count&&b.All(p=>a.TryGetValue(p.Key,out var old)&&old.OrderBy(x=>x).SequenceEqual(p.Value.OrderBy(x=>x)));
        private void Rename(Component2 component,string name)
        {
            // Keep native instance names stable: changing Name2 alters serialized
            // body IDs again on reopen under the user's automatic-name preference.
            // The reference label is assembly metadata and leaves those IDs intact.
            component.ComponentReference=name;
            if(component.ComponentReference!=name)throw new InvalidOperationException("SolidWorks did not retain the companion group label: "+name);
        }
        public async Task<Result> Update(VehicleProject sourceProject,string receiptPath,bool refreshGeometry,Action<int,string> progress,CancellationToken token)
        {
            var selector=new FrameSelection(app,source,true);selector.ValidateDocument();
            var old=CompanionAssemblyLink.Read(receiptPath);
            if(!ComponentAssignments.SameDocument(old.SourceProject,sourceProject.FilePath)||!ComponentAssignments.SameDocument(old.SourceDocument,selector.Document))
                throw new InvalidOperationException("Activate the source assembly and project linked to this companion.");
            var input=VehicleProject.Load(sourceProject.FilePath);
            var current=VehicleProject.Load(old.Project);
            var before=(old.SourceComponents??new List<ComponentDefinition>()).ToDictionary(c=>c.Id);
            var plan=new List<UpdateGroup>();
            var retained=ReplacementIds(old);
            foreach(var c in input.Components)
            {
                token.ThrowIfCancellationRequested();var item=new UpdateGroup {Source=c,Before=before.TryGetValue(c.Id,out var b)?b:null,Old=old.Groups.SingleOrDefault(g=>g.Id==c.Id)};
                if(KeepsReplacement(item.Old))
                {
                    RetainReplacement(item,current);plan.Add(item);
                    progress?.Invoke(plan.Count*15/Math.Max(1,input.Components.Count),"Retaining reviewed replacement: "+item.Source.Name);await Task.Yield();continue;
                }
                foreach(var scope in Scopes(c))
                {
                    if(!string.IsNullOrEmpty(scope.Item3)&&!ComponentAssignments.SameDocument(scope.Item3,selector.Document))throw new InvalidOperationException(c.Name+": source assignment belongs to another assembly.");
                    item.Scopes.Add(scope.Item1,selector.SnapshotBodies(scope.Item2).Select(pair=>Key(source,pair)).ToArray());
                }
                var keys=item.Scopes.Values.SelectMany(v=>v).Distinct().OrderBy(x=>x).ToArray();
                item.Replace=refreshGeometry||item.Old==null?keys.Length>0:!keys.SequenceEqual(item.Old.SourceBodies.OrderBy(x=>x));
                if(item.Old?.Members?.Count>0)
                {
                    var authored=input.JointWorkspace.Members.Where(m=>m.ComponentId==c.Id).ToArray();
                    foreach(var member in item.Old.Members)
                    {
                        var kind=current.JointWorkspace.Members.Single(m=>m.Id==member.Id).Kind;
                        var choice=authored.SingleOrDefault(m=>m.Kind==kind);
                        if(authored.Length>0&&choice==null)throw new InvalidOperationException(c.Name+": source member classification must retain "+kind+". Change member kinds in a new companion revision first.");
                        var bodyKeys=choice==null?member.SourceBodies.ToArray():selector.SnapshotBodies(new FrameAssignment {Configuration=c.Configuration,Selections=choice.Selections}).Select(p=>Key(source,p)).ToArray();
                        item.MemberSources.Add(member.Id,bodyKeys);
                        if(!bodyKeys.OrderBy(v=>v).SequenceEqual(member.SourceBodies.OrderBy(v=>v)))item.Replace=true;
                    }
                    var partition=item.MemberSources.Values.SelectMany(v=>v).ToArray();
                    if(partition.Distinct().Count()!=partition.Length||!partition.OrderBy(v=>v).SequenceEqual(keys)||authored.Length>0&&authored.Length!=item.Old.Members.Count)
                        throw new InvalidOperationException(c.Name+": classify every assigned source body exactly once in Moving members, using the existing member kinds, before updating the companion.");
                }
                if(item.Before!=null)
                {
                    var configurations=Scopes(item.Before).ToDictionary(s=>s.Item1,s=>s.Item2.Configuration);
                    if(Scopes(c).Any(s=>configurations.TryGetValue(s.Item1,out var config)&&config!=s.Item2.Configuration))item.Replace=keys.Length>0;
                }
                item.Rebind=item.Replace||!(item.Old==null&&item.Scopes.Count==0)&&!EqualScopes(item.Old?.Scopes,item.Scopes);
                plan.Add(item);
                progress?.Invoke(plan.Count*15/Math.Max(1,input.Components.Count),"Checking "+c.Name);await Task.Yield();
            }
            token.ThrowIfCancellationRequested();
            var assembly=OpenAssembly(old.Assembly,out var opened);
            // The on-disk revision must include the user's reference work. Never
            // save unrelated pending CAD changes or substitute an older disk state.
            if(assembly.GetSaveFlag()||(((AssemblyDoc)assembly).GetComponents(false) as object[]??Array.Empty<object>()).Cast<Component2>().Any(c=>(c.GetModelDoc2() as ModelDoc2)?.GetSaveFlag()==true))
                throw new InvalidOperationException("Save the companion assembly and its edited parts in SolidWorks before updating, so the revision includes your reference work.");
            foreach(var item in plan)
                if(!KeepsReplacement(item.Old)&&item.Scopes.Count>0&&FindInstance(assembly,item.Old,current.Components.SingleOrDefault(c=>c.Id==item.Source.Id))==null)item.Replace=item.Rebind=true;
            foreach(var group in old.Groups.Where(KeepsReplacement))
            {
                if(!current.Components.Any(c=>c.Id==group.Id))throw new InvalidDataException(group.Name+": reviewed replacement assignment is missing. Restore it before updating.");
                foreach(var part in group.Members?.Count>0?group.Members:new List<Group>{group})
                    if(FindInstance(assembly,part,null)==null)throw new InvalidDataException(part.Name+": reviewed replacement part is missing. Restore it before updating; the old source will not be substituted.");
            }
            var sourceIds=new HashSet<string>(input.Components.Select(c=>c.Id));
            var removed=RemovedSourceIds(old,sourceIds);
            var metadata=old.SourceComponents==null||input.Components.Any(c=>CompanionAssemblyLink.State(c)!=CompanionAssemblyLink.State(before.TryGetValue(c.Id,out var prior)?prior:null))||
                !input.Components.Select(c=>c.Id).SequenceEqual((old.SourceComponents??new List<ComponentDefinition>()).Select(c=>c.Id))||
                CompanionAssemblyLink.Serialized(input.MvpTemplates,typeof(List<MvpTemplateChoice>))!=CompanionAssemblyLink.Serialized(old.SourceTemplates,typeof(List<MvpTemplateChoice>));
            if(!metadata&&!plan.Any(p=>p.Rebind)&&removed.Count==0)
            {
                Activate(assembly);CompanionAssemblyLink.Register(receiptPath);progress?.Invoke(100,"Companion is already up to date");
                return new Result {Document=assembly,Project=current,ReceiptPath=receiptPath};
            }
            var revision=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(receiptPath)),"r"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,5));
            Directory.CreateDirectory(revision);
            var assemblyPath=Path.Combine(revision,"Companion_"+Guid.NewGuid().ToString("N").Substring(0,8)+".SLDASM");
            var receipt=new Receipt {SourceProject=input.FilePath,SourceDocument=input.SourceDocument,Configuration=selector.Configuration,Assembly=assemblyPath,Project=VehicleProject.PathFor(assemblyPath),PreviousAssembly=old.Assembly,
                SourceComponents=VehicleProject.Load(input.FilePath).Components,SourceTemplates=input.MvpTemplates};
            receipt.Notes.Add("Assignment update revision. Unchanged part files and their reference work are retained. Previous assembly: "+old.Assembly);
            if(retained.Count>0)receipt.Notes.Add(retained.Count+" reviewed replacement groups retained, including during full geometry refresh. Edit these groups in the companion; the original source no longer owns them.");
            if(!refreshGeometry)receipt.Notes.Add("Changes inside the same assigned bodies are copied only with Refresh assigned geometry too.");
            if(old.SourceComponents==null)receipt.Notes.Add("Legacy receipt upgraded: source group settings applied; unknown local groups retained.");
            var revisionReceipt=Path.Combine(revision,"working-assembly.json");JsonFile.Write(revisionReceipt,receipt);
            JsonFile.Write(Path.Combine(revision,"previous-working-assembly.json"),old);
            ModelDoc2 revised=null;var success=false;
            try
            {
                var replacements=plan.Where(p=>p.Replace&&p.Scopes.Count>0).ToArray();Receipt generated=null;
                if(replacements.Length>0)
                {
                    Activate(source);
                    var export=input.Fork(Path.Combine(revision,"export-input.beamng-project.json"));
                    export.Components=ReplacementComponents(replacements,selector);export.Anchors.Clear();export.Connections.Clear();export.JointWorkspace=new JointWorkspace();export.TemplateDefinitionPath="";export.Save();
                    var result=await Create(export,Path.Combine(revision,"parts"),(p,message)=>progress?.Invoke(15+p*55/100,message),token);
                    generated=CompanionAssemblyLink.Read(result.ReceiptPath);app.CloseDoc(result.Document.GetTitle());
                }
                token.ThrowIfCancellationRequested();
                // Byte-copy preserves the assembly's internal entity identities,
                // sketches and references. Only the new revision is then edited.
                File.Copy(old.Assembly,assemblyPath);File.Copy(old.Project,receipt.Project);
                var output=VehicleProject.Load(receipt.Project);output.SourceDocument=assemblyPath;
                foreach(var c in output.Components)Retarget(c,old.Assembly,assemblyPath);
                revised=OpenAssembly(assemblyPath,out var ignored);Activate(revised);
                using(var quiet=new MaterialUiUpdateScope(app))
                {
                    quiet.CoverDocumentTransitions();
                    RebaseReferences(assembly,revised,output);
                    foreach(var id in removed)
                    {
                        var component=output.Components.SingleOrDefault(c=>c.Id==id);var group=old.Groups.SingleOrDefault(g=>g.Id==id);var instance=FindInstance(revised,null,component);
                        RemoveInstances(revised,component);
                        output.Components.RemoveAll(c=>c.Id==id);receipt.Notes.Add("Removed group: "+(component?.Name??id)+". Its previous part file is retained with the prior revision.");
                    }
                    var changed=new HashSet<string>();
                    foreach(var item in plan)
                    {
                        token.ThrowIfCancellationRequested();Activate(revised);
                        var target=output.Components.SingleOrDefault(c=>c.Id==item.Source.Id);
                        var instance=FindInstance(revised,null,target);
                        var group=item.Old;
                        if(target==null){target=new ComponentDefinition {Id=item.Source.Id};output.Components.Add(target);}
                        MergeSettings(target,item.Before,item.Source);
                        if(item.Old?.Scopes!=null)
                        {
                            item.Old.Scopes.TryGetValue("cad",out var oldCad);item.Scopes.TryGetValue("cad",out var newCad);
                            if(!(oldCad??Array.Empty<string>()).OrderBy(x=>x).SequenceEqual((newCad??Array.Empty<string>()).OrderBy(x=>x)))changed.Add(target.Id);
                        }
                        if(item.Replace||item.Scopes.Count==0&&instance!=null&&item.Rebind)
                        {
                            changed.Add(target.Id);
                            if(instance!=null){RemoveInstances(revised,target);instance=null;}
                            if(item.Scopes.Count>0)
                            {
                                var memberIds=item.Old?.Members?.Select(m=>m.Id).ToArray()??Array.Empty<string>();
                                if(memberIds.Length>0)
                                {
                                    group=item.Old;group.Members=memberIds.Select(id=>generated.Groups.Single(g=>g.Id==id)).ToList();group.SourceBodies=item.Scopes.Values.SelectMany(v=>v).Distinct().ToList();
                                    foreach(var member in group.Members)InsertMember(revised,member);
                                    instance=(Component2)Resolve(revised,group.Members[0].ComponentReference);
                                }
                                else
                                {
                                group=generated.Groups.Single(g=>g.Id==target.Id);int error=0,warning=0;
                                var part=(ModelDoc2)app.OpenDoc6(group.Part,1,(int)swOpenDocOptions_e.swOpenDocOptions_Silent,"",ref error,ref warning)??throw new IOException("Could not load replacement part.");
                                Activate(revised);instance=((AssemblyDoc)revised).AddComponent5(group.Part,0,"",false,"",0,0,0)??throw new InvalidOperationException("Could not insert "+target.Name);
                                instance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(new[]{1d,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0});
                                revised.ClearSelection2(true);if(!instance.Select4(false,null,false))throw new InvalidOperationException("Could not fix "+target.Name);((AssemblyDoc)revised).FixComponent();app.CloseDoc(part.GetTitle());Activate(revised);
                                }
                            }
                        }
                        if(item.Rebind)BindGroup(revised,instance,target,group,item);
                        if(group?.Members?.Count>0)SynchronizeMembers(revised,output,target,group);
                        if(instance!=null)
                        {
                            if(item.Before?.Name!=item.Source.Name)Rename(instance,target.Name);
                            if(group!=null){group.Name=target.Name;group.ComponentReference=Reference(revised,instance);group.Part=instance.GetPathName();receipt.Groups.Add(group);}
                        }
                        progress?.Invoke(70+(plan.IndexOf(item)+1)*20/Math.Max(1,plan.Count),"Updating "+target.Name);await Task.Yield();
                    }
                    // Keep provenance for companion-only groups and replacements
                    // deleted from the old source list as well as their geometry.
                    foreach(var group in old.Groups.Where(g=>!receipt.Groups.Any(n=>n.Id==g.Id)&&output.Components.Any(c=>c.Id==g.Id)))
                        receipt.Groups.Add(group);
                    // The source owns its list order. Locally added companion-only
                    // groups remain appended and are never mistaken for deletions.
                    output.Components=input.Components.Select(c=>output.Components.Single(t=>t.Id==c.Id)).Concat(output.Components.Where(c=>!sourceIds.Contains(c.Id))).ToList();
                    var removedAnchors=new HashSet<string>(output.Anchors.Where(a=>removed.Contains(a.ComponentId)).Select(a=>a.Id));
                    output.Anchors.RemoveAll(a=>removedAnchors.Contains(a.Id));output.Connections.RemoveAll(c=>removedAnchors.Contains(c.AnchorA)||removedAnchors.Contains(c.AnchorB));
                    CanonicalReferences(revised,output);
                    foreach(var group in receipt.Groups)
                    {
                        var component=output.Components.Single(c=>c.Id==group.Id);
                        var instance=FindInstance(revised,null,component);
                        if(instance!=null){group.ComponentReference=Reference(revised,instance);group.Part=instance.GetPathName();}
                        foreach(var member in group.Members??new List<Group>())
                            member.ComponentReference=Reference(revised,MemberInstance(revised,member));
                    }
                    var updatedSelection=new FrameSelection(app,revised,true);
                    foreach(var c in output.Components)
                    {
                        if(c.Selections.Count>0)c.BodyIds=updatedSelection.BodyIds(new FrameAssignment {Configuration=c.Configuration,Selections=c.Selections});
                        foreach(var piece in c.AppearanceCoilover?.Pieces??new List<CoiloverMeshAssignment>())
                            if(piece.Selections.Count>0)piece.BodyIds=updatedSelection.BodyIds(CoiloverAppearance.Assignment(piece));
                    }
                    foreach(var anchor in output.Anchors)
                    {
                        if(changed.Contains(anchor.ComponentId)){anchor.Status="needs_repair";anchor.References.Clear();anchor.BodyReferences?.Clear();anchor.ComponentReference=null;}
                        else if(anchor.Status=="resolved")try{new MountAnchors(app,revised).Update(anchor);}catch{anchor.Status="needs_repair";}
                    }
                    output.JointWorkspace.Invalidate(changed.Concat(removed),"Companion geometry changed; rescan and repair affected joints");
                    if(output.Anchors.Any(a=>a.Status!="resolved"))receipt.Notes.Add("Some mounting references need repair. Unchanged valid references remain associated.");
                    if(old.SourceTemplates==null||CompanionAssemblyLink.Serialized(input.MvpTemplates,typeof(List<MvpTemplateChoice>))!=CompanionAssemblyLink.Serialized(old.SourceTemplates,typeof(List<MvpTemplateChoice>)))output.MvpTemplates=input.MvpTemplates;
                    output.LastBuildReceipt="";output.FrameBuildReceipt="";output.PhysicsBuildReceipt="";output.PhysicsTemplateReceipt="";
                    // Preserve locally reviewed hardpoints independently of the previous revision.
                    if(File.Exists(output.TemplateDefinitionPath)){var copied=Path.Combine(revision,"template-definition.json");File.Copy(output.TemplateDefinitionPath,copied);output.TemplateDefinitionPath=copied;}
                    var profile=FramePipeline.ModProfile.Load(current.ProfilePath);if(!File.Exists(profile.PreviewImage))profile.PreviewImage="";profile.Save(output.ProfilePath);
                    foreach(var c in output.Components.Where(c=>c.Template=="calibrated_frame"&&c.Selections.Count>0))PreparationFile.Load(assemblyPath).Save(new FrameAssignment {Id=c.Id,Configuration=c.Configuration,Selections=c.Selections,Hull=c.Hull});
                    revised.ClearSelection2(true);Save(revised,assemblyPath);output.Save();
                    // Check every saved scope before promoting the revision link.
                    var verify=new FrameSelection(app,revised,true);
                    foreach(var c in output.Components)foreach(var scope in Scopes(c))verify.SnapshotBodies(scope.Item2);
                    token.ThrowIfCancellationRequested();receipt.Status="completed";JsonFile.Write(revisionReceipt,receipt);
                    CompanionAssemblyLink.Promote(receiptPath,receipt);
                    success=true;progress?.Invoke(100,"Companion updated. Previous revision retained.");
                    return new Result {Document=revised,Project=output,ReceiptPath=receiptPath};
                }
            }
            finally
            {
                if(!success&&revised!=null)try{app.CloseDoc(revised.GetTitle());}catch{}
                if(opened)try{app.CloseDoc(assembly.GetTitle());}catch{}
                Activate(success?revised:source);
            }
        }
    }
}
