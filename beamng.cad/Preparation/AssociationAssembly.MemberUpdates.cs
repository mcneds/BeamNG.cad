using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization.Json;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    internal sealed partial class AssociationAssembly
    {
        private static ComponentDefinition CopyDefinition(ComponentDefinition value)
        {
            var serializer=new DataContractJsonSerializer(typeof(ComponentDefinition));
            using(var stream=new MemoryStream()){serializer.WriteObject(stream,value);stream.Position=0;return (ComponentDefinition)serializer.ReadObject(stream);}
        }
        private List<ComponentDefinition> ReplacementComponents(UpdateGroup[] replacements,FrameSelection selector)
        {
            var result=new List<ComponentDefinition>();
            foreach(var item in replacements)
            {
                if(item.Old?.Members?.Count>0)
                {
                    var keys=item.Scopes.Values.SelectMany(v=>v).Distinct().ToArray();
                    if(keys.Except(item.MemberSources.Values.SelectMany(m=>m)).Any())
                        throw new InvalidOperationException(item.Source.Name+": newly assigned bodies need moving-member classification. Keep the saved companion; classify the changed selection before regenerating its members.");
                    var all=Scopes(item.Source).SelectMany(s=>selector.SnapshotBodies(s.Item2)).GroupBy(p=>Key(source,p)).ToDictionary(g=>g.Key,g=>g.First());
                    foreach(var member in item.Old.Members)
                    {
                        var copy=CopyDefinition(item.Source);copy.Id=member.Id;copy.Name=member.Name;
                        var selected=item.MemberSources[member.Id].Where(k=>all.ContainsKey(k)).Select(k=>all[k]).ToArray();
                        if(selected.Length==0)throw new InvalidOperationException(member.Name+": all member bodies were removed. Review the moving-member classification before updating.");
                        copy.Selections=selected.Select(p=>new SelectionReference {Kind="body",Name=member.Name+" / "+p.Item2.Name,Reference=Reference(source,p.Item2),ComponentReference=Reference(source,p.Item1)}).ToList();
                        copy.BodyIds=selector.BodyIds(new FrameAssignment {Configuration=copy.Configuration,Selections=copy.Selections});
                        copy.AppearanceSelections=copy.Selections;copy.AppearanceSourceDocument=copy.CadSourceDocument;copy.AppearanceConfiguration=copy.Configuration;copy.AppearanceCoilover=null;
                        result.Add(copy);
                    }
                }
                else result.Add(CopyDefinition(item.Source));
            }
            return result;
        }
        private static void RemoveInstances(ModelDoc2 assembly,ComponentDefinition component)
        {
            if(component==null)return;
            var instances=Scopes(component).SelectMany(s=>s.Item2.Selections).Select(s=>Resolve(assembly,s.ComponentReference) as Component2).Where(c=>c!=null).GroupBy(c=>c.Name2).Select(g=>g.First()).ToArray();
            foreach(var instance in instances)
            {
                assembly.ClearSelection2(true);
                if(!instance.Select4(false,null,false)||!assembly.Extension.DeleteSelection2(0))throw new InvalidOperationException("Could not replace companion member of "+component.Name);
            }
        }
        private Component2 InsertMember(ModelDoc2 assembly,Group member)
        {
            int error=0,warning=0;
            var part=(ModelDoc2)app.OpenDoc6(member.Part,1,(int)swOpenDocOptions_e.swOpenDocOptions_Silent,"",ref error,ref warning)??throw new IOException("Could not open member: "+member.Name);
            Activate(assembly);var instance=((AssemblyDoc)assembly).AddComponent5(member.Part,0,"",false,"",0,0,0)??throw new IOException("Could not insert member: "+member.Name);
            instance.Transform2=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(new[]{1d,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0});
            assembly.ClearSelection2(true);instance.Select4(false,null,false);((AssemblyDoc)assembly).FixComponent();Rename(instance,member.Name);
            member.ComponentReference=Reference(assembly,instance);app.CloseDoc(part.GetTitle());Activate(assembly);return instance;
        }
        private static Component2 MemberInstance(ModelDoc2 assembly,Group member)
        {
            var matches=(((AssemblyDoc)assembly).GetComponents(true) as object[]??Array.Empty<object>()).Cast<Component2>()
                .Where(c=>ComponentAssignments.SameDocument(c.GetPathName(),member.Part)).ToArray();
            if(matches.Length!=1)throw new InvalidOperationException(member.Name+": member instance is missing or ambiguous.");
            return matches[0];
        }
        private void BindMemberGroup(ModelDoc2 assembly,ComponentDefinition c,Group group,UpdateGroup update)
        {
            var refs=new Dictionary<string,SelectionReference>();var config=assembly.ConfigurationManager.ActiveConfiguration.Name;
            foreach(var member in group.Members)
            {
                var instance=MemberInstance(assembly,member);member.ComponentReference=Reference(assembly,instance);object info;
                var bodies=((object[])instance.GetBodies3(-1,out info)).Cast<Body2>().ToDictionary(b=>b.Name);
                for(var i=0;i<member.SourceBodies.Count;i++)
                    refs.Add(member.SourceBodies[i],new SelectionReference {Kind="body",Name=member.Name+" / "+member.CopiedBodies[i],
                        Reference=Reference(assembly,bodies[member.CopiedBodies[i]]),ComponentReference=member.ComponentReference});
            }
            var selector=new FrameSelection(app,assembly,true);group.Scopes=update.Scopes;
            foreach(var scope in update.Scopes)
            {
                var selections=scope.Value.Select(k=>refs.TryGetValue(k,out var value)?value:throw new InvalidOperationException(c.Name+": member body mapping needs repair.")).ToList();
                var ids=selector.BodyIds(new FrameAssignment {Configuration=config,Selections=selections});
                if(scope.Key=="cad"){c.Selections=selections;c.BodyIds=ids;c.Configuration=config;c.CadSourceDocument=assembly.GetPathName();}
                else if(scope.Key=="appearance"){c.AppearanceSelections=selections;c.AppearanceConfiguration=config;c.AppearanceSourceDocument=assembly.GetPathName();c.AppearancePackageState="pending";}
                else {var kind=scope.Key.Substring("coilover:".Length);var piece=c.AppearanceCoilover?.Pieces.SingleOrDefault(p=>p.Kind==kind);
                    if(piece==null){c.AppearanceCoilover=c.AppearanceCoilover??new CoiloverAppearance();piece=new CoiloverMeshAssignment {Kind=kind};c.AppearanceCoilover.Pieces.Add(piece);}
                    piece.Selections=selections;piece.BodyIds=ids;piece.Configuration=config;piece.SourceDocument=assembly.GetPathName();piece.GeometryDirectory=null;}
            }
        }
        private void SynchronizeMembers(ModelDoc2 assembly,VehicleProject output,ComponentDefinition owner,Group group)
        {
            var selector=new FrameSelection(app,assembly,true);
            foreach(var member in group.Members)
            {
                var instance=MemberInstance(assembly,member);member.ComponentReference=Reference(assembly,instance);
                var declaration=output.JointWorkspace.Members.SingleOrDefault(m=>m.Id==member.Id);
                if(declaration==null)throw new InvalidOperationException("Moving-member declaration missing: "+member.Name);
                declaration.ComponentReference=member.ComponentReference;declaration.Part=member.Part;declaration.PlacementFixed=instance.IsFixed();
                declaration.Selections=owner.Selections.Where(s=>s.ComponentReference==member.ComponentReference).ToList();
                declaration.BodyIds=selector.BodyIds(new FrameAssignment {Configuration=owner.Configuration,Selections=declaration.Selections});
            }
        }
    }
}
