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
        internal static List<MovingMember> AssignedCoiloverMembers(ComponentDefinition component)
        {
            var pieces=component.AppearanceCoilover?.Pieces;
            if(pieces==null||!CoiloverAppearance.Kinds.All(k=>pieces.Count(p=>p.Kind==k&&p.BodyIds?.Count>0)==1))return null;
            var ids=pieces.SelectMany(p=>p.BodyIds??new List<string>()).ToArray();
            if(ids.Length==0||ids.Distinct().Count()!=ids.Length||!ids.OrderBy(x=>x).SequenceEqual(component.BodyIds.OrderBy(x=>x)))return null;
            return pieces.Select(p=>new MovingMember {ComponentId=component.Id,Kind=p.Kind,Name=component.Name+" / "+p.Kind,
                BodyIds=p.BodyIds.ToList(),Selections=p.Selections.ToList()}).ToList();
        }

        public async Task<Result> SplitMembers(VehicleProject project,string receiptPath,string componentId,Action<int,string> progress,CancellationToken token)
        {
            var old=CompanionAssemblyLink.Read(receiptPath);
            if(!ComponentAssignments.SameDocument(old.Project,project.FilePath)||!ComponentAssignments.SameDocument(source.GetPathName(),old.Assembly))
                throw new InvalidOperationException("Open the latest companion before splitting moving members.");
            if(source.GetSaveFlag())throw new InvalidOperationException("Save companion CAD first so this revision retains all reference work.");
            var current=VehicleProject.Load(project.FilePath);var component=current.Components.Single(c=>c.Id==componentId);
            var members=current.JointWorkspace.Members.Where(m=>m.ComponentId==componentId).ToArray();
            if(members.Length<2)throw new InvalidOperationException("Classify at least two moving members.");
            var ids=members.SelectMany(m=>m.BodyIds).ToArray();
            if(ids.Length!=ids.Distinct().Count()||!ids.OrderBy(s=>s).SequenceEqual(component.BodyIds.OrderBy(s=>s)))
                throw new InvalidOperationException("Assign every physical body to exactly one moving member before splitting.");
            var selector=new FrameSelection(app,source,true);var sourceBodies=selector.SnapshotBodies(new FrameAssignment {Configuration=component.Configuration,Selections=component.Selections});
            var scopes=Scopes(component).ToDictionary(s=>s.Item1,s=>selector.SnapshotBodies(s.Item2).Select(b=>Key(source,b)).ToArray());
            var memberKeys=members.ToDictionary(m=>m.Id,m=>selector.SnapshotBodies(new FrameAssignment {Configuration=component.Configuration,Selections=m.Selections}).Select(b=>Key(source,b)).ToArray());
            if(scopes.Values.SelectMany(v=>v).Except(memberKeys.Values.SelectMany(v=>v)).Any())
                throw new InvalidOperationException("Some appearance bodies are outside the physical moving-member assignment. Review the appearance ownership before splitting.");
            var revision=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(receiptPath)),"members-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,5));
            Directory.CreateDirectory(revision);var outputPath=Path.Combine(revision,"Companion_"+Guid.NewGuid().ToString("N").Substring(0,8)+".SLDASM");
            var export=current.Fork(Path.Combine(revision,"member-input.beamng-project.json"));
            export.Components=members.Select(m=>new ComponentDefinition {Id=m.Id,Name=m.Name,Template=component.Template,Configuration=component.Configuration,
                Selections=m.Selections,BodyIds=m.BodyIds,CadSourceDocument=source.GetPathName(),AppearanceSelections=m.Selections,
                AppearanceConfiguration=component.Configuration,AppearanceSourceDocument=source.GetPathName(),SurfaceMassMode=component.SurfaceMassMode,Thickness=component.Thickness}).ToList();
            export.Anchors.Clear();export.Connections.Clear();export.JointWorkspace=new JointWorkspace();export.TemplateDefinitionPath="";export.Save();
            var copier=new AssociationAssembly(app,source) {copyPartsOnly=true};
            var generated=await copier.Create(export,Path.Combine(revision,"parts"),(value,message)=>progress?.Invoke(value*65/100,message),token);
            var generatedReceipt=JsonFile.Read<Receipt>(generated.ReceiptPath);
            if(generatedReceipt.Status!="parts_completed"||generatedReceipt.Groups.Any(g=>!File.Exists(g.Part)))
                throw new IOException("Moving member part copy did not complete.");
            Activate(source);
            File.Copy(old.Assembly,outputPath);File.Copy(old.Project,VehicleProject.PathFor(outputPath));
            var output=VehicleProject.Load(VehicleProject.PathFor(outputPath));output.SourceDocument=outputPath;
            foreach(var c in output.Components)Retarget(c,old.Assembly,outputPath);
            ModelDoc2 revised=null;var success=false;
            try
            {
                revised=OpenAssembly(outputPath,out var ignored);Activate(revised);RebaseReferences(source,revised,output);
                var target=output.Components.Single(c=>c.Id==componentId);var previousGroup=old.Groups.Single(g=>g.Id==componentId);
                // Record original-source keys for subsequent source assignment updates.
                var sourceKeys=new Dictionary<string,string>();
                foreach(var pair in sourceBodies)
                {
                    var subgroup=(previousGroup.Members??new List<Group>()).FirstOrDefault(g=>ComponentAssignments.SameDocument(g.Part,pair.Item1.GetPathName()))??previousGroup;
                    var index=subgroup.CopiedBodies.IndexOf(pair.Item2.Name);
                    // Overrides have a different source than the root receipt.
                    // Keep this split's direct companion origin and immutable
                    // appearance history instead of rewriting to root-source keys.
                    if(index>=0&&!KeepsReplacement(previousGroup))sourceKeys[Key(source,pair)]=subgroup.SourceBodies[index];
                }
                var oldInstances=target.Selections.Select(s=>Resolve(revised,s.ComponentReference) as Component2).Where(c=>c!=null).GroupBy(c=>c.Name2).Select(g=>g.First()).ToArray();
                foreach(var instance in oldInstances)
                {
                    var reference=Reference(revised,instance);
                    if(output.Components.Any(c=>c.Id!=componentId&&c.Selections.Any(s=>s.ComponentReference==reference)))throw new InvalidOperationException("Another group shares this companion instance; repair ownership before splitting.");
                    revised.ClearSelection2(true);if(!instance.Select4(false,null,false)||!revised.Extension.DeleteSelection2(0))throw new InvalidOperationException("Could not replace moving member instance.");
                }
                var newRefs=new Dictionary<string,SelectionReference>();var receiptMembers=new List<Group>();
                var configuration=revised.ConfigurationManager.ActiveConfiguration.Name;var outputSelection=new FrameSelection(app,revised,true);
                foreach(var member in members)
                {
                    token.ThrowIfCancellationRequested();var group=generatedReceipt.Groups.Single(g=>g.Id==member.Id);int error=0,warning=0;
                    var part=OpenBackgroundPart(group.Part,ref error,ref warning)??throw new IOException("Could not load moving member part.");
                    Activate(revised);var instance=((AssemblyDoc)revised).AddComponent5(group.Part,0,"",false,"",0,0,0)??throw new IOException("Could not insert moving member.");
                    instance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(new[]{1d,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0});
                    revised.ClearSelection2(true);instance.Select4(false,null,false);((AssemblyDoc)revised).FixComponent();Rename(instance,member.Name);
                    group.ComponentReference=Reference(revised,instance);object info;
                    var bodies=((object[])instance.GetBodies3(-1,out info)).Cast<Body2>().ToDictionary(b=>b.Name);
                    var refs=new List<SelectionReference>();
                    for(var i=0;i<group.SourceBodies.Count;i++)
                    {
                        var body=bodies[group.CopiedBodies[i]];
                        var saved=new SelectionReference {Kind="body",Name=member.Name+" / "+body.Name,Reference=Reference(revised,body),ComponentReference=group.ComponentReference};
                        newRefs.Add(group.SourceBodies[i],saved);refs.Add(saved);
                    }
                    var replacement=output.JointWorkspace.Members.Single(m=>m.Id==member.Id);replacement.Selections=refs;
                    replacement.BodyIds=outputSelection.BodyIds(new FrameAssignment {Configuration=configuration,Selections=refs});replacement.ComponentReference=group.ComponentReference;
                    replacement.Part=group.Part;replacement.PlacementFixed=true;
                    group.SourceBodies=group.SourceBodies.Select(k=>sourceKeys.TryGetValue(k,out var original)?original:k).ToList();
                    if(KeepsReplacement(previousGroup))
                    {
                        group.SourceOverride=true;group.SourceDocument=source.GetPathName();
                        group.SourceProject=current.FilePath;group.SourceConfiguration=component.Configuration;
                    }
                    receiptMembers.Add(group);app.CloseDoc(part.GetTitle());Activate(revised);
                }
                foreach(var scope in scopes)
                {
                    var refs=scope.Value.Select(k=>newRefs[k]).ToList();var bodyIds=outputSelection.BodyIds(new FrameAssignment {Configuration=configuration,Selections=refs});
                    if(scope.Key=="cad"){target.Selections=refs;target.BodyIds=bodyIds;target.Configuration=configuration;target.CadSourceDocument=outputPath;}
                    else if(scope.Key=="appearance"){target.AppearanceSelections=refs;target.AppearanceConfiguration=configuration;target.AppearanceSourceDocument=outputPath;}
                    else {var piece=target.AppearanceCoilover.Pieces.Single(p=>"coilover:"+p.Kind==scope.Key);piece.Selections=refs;piece.BodyIds=bodyIds;piece.Configuration=configuration;piece.SourceDocument=outputPath;}
                }
                foreach(var a in output.Anchors.Where(a=>a.ComponentId==componentId)){a.Status="needs_repair";a.References.Clear();a.BodyReferences?.Clear();a.ComponentReference=null;}
                output.JointWorkspace.Invalidate(new[]{componentId},"Moving members replaced the original CAD instance; rescan/repair its joints");
                output.FrameBuildReceipt=output.LastBuildReceipt=output.PhysicsBuildReceipt=output.PhysicsTemplateReceipt="";
                var receipt=new Receipt {SourceProject=old.SourceProject,SourceDocument=old.SourceDocument,Configuration=old.Configuration,Assembly=outputPath,Project=output.FilePath,
                    SourceComponents=old.SourceComponents,SourceTemplates=old.SourceTemplates,PreviousAssembly=old.Assembly,Groups=old.Groups};
                previousGroup.Members=receiptMembers;previousGroup.ComponentReference=receiptMembers[0].ComponentReference;previousGroup.Part=receiptMembers[0].Part;
                var profile=FramePipeline.ModProfile.Load(current.ProfilePath);profile.Save(output.ProfilePath);
                foreach(var c in output.Components.Where(c=>c.Template=="calibrated_frame"&&c.Selections.Count>0))PreparationFile.Load(outputPath).Save(new FrameAssignment {Id=c.Id,Configuration=configuration,Selections=c.Selections,Hull=c.Hull});
                revised.ClearSelection2(true);Save(revised,outputPath);output.Save();
                foreach(var c in output.Components)foreach(var scope in Scopes(c))outputSelection.SnapshotBodies(scope.Item2);
                receipt.Status="completed";receipt.Notes.Add("Moving-member revision; logical groups, total CAD ownership and unchanged native reference work retained. Changed references require repair.");
                JsonFile.Write(Path.Combine(revision,"working-assembly.json"),receipt);CompanionAssemblyLink.Promote(receiptPath,receipt);
                success=true;progress?.Invoke(100,"Moving members ready");return new Result {Document=revised,Project=output,ReceiptPath=receiptPath};
            }
            finally {if(!success&&revised!=null)try{app.CloseDoc(revised.GetTitle());}catch{}Activate(success?revised:source);}
        }
    }
}
