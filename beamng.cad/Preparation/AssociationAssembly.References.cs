using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    internal sealed partial class AssociationAssembly
    {
        // Assembly-context persistent references include their document context.
        // Recapture them from the clone; resolving an old reference while both
        // documents are open can return the old document's component/body.
        private void RebaseReferences(ModelDoc2 previous,ModelDoc2 revised,VehicleProject output)
        {
            var oldInstances=(((AssemblyDoc)previous).GetComponents(false) as object[]??Array.Empty<object>()).Cast<Component2>().ToArray();
            var newInstances=(((AssemblyDoc)revised).GetComponents(false) as object[]??Array.Empty<object>()).Cast<Component2>().ToArray();
            var newIdentities=newInstances.Select(c=>new {Component=c,Name=c.Name2,Path=c.GetPathName()}).ToArray();
            var instances=new Dictionary<string,Component2>();
            foreach(var old in oldInstances)
            {
                var name=old.Name2;var path=old.GetPathName();
                var match=newIdentities.SingleOrDefault(c=>c.Name==name&&ComponentAssignments.SameDocument(c.Path,path));
                if(match==null)throw new InvalidOperationException("Could not identify copied companion instance: "+name);
                instances.Add(Reference(previous,old),match.Component);
            }
            var before=new FrameSelection(app,previous,true);var after=new FrameSelection(app,revised,true);
            var bodyMap=new Dictionary<string,SelectionReference>();
            // Geometry stays unchanged during rebasing. Snapshot each copied
            // instance once instead of enumerating every body for every match.
            // Scope the cache to this revision so stale geometry cannot survive
            // the next update or moving-member replacement.
            var copiedBodies=new Dictionary<string,Dictionary<string,Body2>>();
            var copiedReferences=new Dictionary<string,string>();
            Func<string,Dictionary<string,Body2>> bodiesFor=key=>{
                if(!copiedBodies.TryGetValue(key,out var bodies))
                {
                    object info;var instance=instances[key];
                    bodies=((object[])instance.GetBodies3((int)swBodyType_e.swAllBodies,out info)).Cast<Body2>().ToDictionary(b=>b.Name);
                    copiedBodies.Add(key,bodies);copiedReferences.Add(key,Reference(revised,instance));
                }
                return bodies;
            };
            Activate(previous);
            var snapshots=output.Components.SelectMany(c=>Scopes(c).Select(scope=>new {
                Component=c,Name=scope.Item1,Bodies=before.SnapshotBodies(scope.Item2)
            })).ToArray();
            Activate(revised);
            foreach(var snapshot in snapshots)
            {
                    var c=snapshot.Component;var oldBodies=snapshot.Bodies;
                    var refs=new List<SelectionReference>();
                    foreach(var pair in oldBodies)
                    {
                        var key=Reference(previous,pair.Item1);var name=pair.Item2.Name;var bodies=bodiesFor(key);
                        if(!bodies.TryGetValue(name,out var body))throw new InvalidOperationException("Copied companion body is unavailable: "+name);
                        var saved=new SelectionReference {Kind="body",Name=c.Name+" / "+name,ComponentReference=copiedReferences[key],Reference=Reference(revised,body)};
                        refs.Add(saved);bodyMap[key+"|"+Reference(previous,pair.Item2)]=saved;
                    }
                    var config=revised.ConfigurationManager.ActiveConfiguration.Name;
                    var ids=after.BodyIds(new FrameAssignment {Configuration=config,Selections=refs});
                    if(snapshot.Name=="cad"){c.Selections=refs;c.BodyIds=ids;c.Configuration=config;}
                    else if(snapshot.Name=="appearance"){c.AppearanceSelections=refs;c.AppearanceConfiguration=config;}
                    else {var piece=c.AppearanceCoilover.Pieces.Single(p=>"coilover:"+p.Kind==snapshot.Name);piece.Selections=refs;piece.BodyIds=ids;piece.Configuration=config;}
            }
            foreach(var member in output.JointWorkspace.Members)
            {
                try
                {
                    member.Selections=member.Selections.Select(s=>bodyMap[s.ComponentReference+"|"+s.Reference]).ToList();
                    member.BodyIds=after.BodyIds(new FrameAssignment {Configuration=revised.ConfigurationManager.ActiveConfiguration.Name,Selections=member.Selections});
                    if(member.ComponentReference!=null)member.ComponentReference=Reference(revised,instances[member.ComponentReference]);
                }
                catch {output.JointWorkspace.Invalidate(new[]{member.ComponentId},"Moving member references require repair after companion update");}
            }
            foreach(var mate in output.JointWorkspace.Mates)
                foreach(var entity in mate.Entities)
                    if(entity.ComponentReference!=null&&instances.TryGetValue(entity.ComponentReference,out var instance))entity.ComponentReference=Reference(revised,instance);
            output.JointWorkspace.ScanStamp=-1;output.JointWorkspace.ScanHash=null;
            foreach(var anchor in output.Anchors.Where(a=>a.Status=="resolved"))
            {
                try
                {
                    if(anchor.CoordinateSpace=="assembly")
                    {
                        anchor.References=anchor.References.Select(r=>{
                            var from=Resolve(previous,r);var to=Resolve(revised,r);
                            if(to==null||app.IsSame(from,to)==(int)swObjectEquality.swObjectSame)throw new InvalidOperationException("Copied datum could not be identified.");
                            return Reference(revised,to);
                        }).ToList();
                    }
                    else
                    {
                        var old=(Component2)Resolve(previous,anchor.ComponentReference);var instance=instances[Reference(previous,old)];
                        var part=(ModelDoc2)old.GetModelDoc2();
                        anchor.References=anchor.References.Select(r=>{
                            var entity=Resolve(previous,r);var local=part.Extension.GetCorresponding2(entity);
                            var copied=local==null?null:instance.GetCorresponding(local);
                            if(copied==null)throw new InvalidOperationException("Copied mounting geometry could not be identified.");
                            return Reference(revised,copied);
                        }).ToList();
                        anchor.BodyReferences=anchor.BodyReferences?.Select(r=>{
                            if(r==null)return null;var oldBody=(Body2)Resolve(previous,r);
                            var body=bodiesFor(Reference(previous,old))[oldBody.Name];return Reference(revised,body);
                        }).ToList();
                        anchor.ComponentReference=Reference(revised,instance);
                    }
                }
                catch {anchor.Status="needs_repair";}
            }
            Activate(revised);
        }
        private static void CanonicalReferences(ModelDoc2 document,VehicleProject project)
        {
            foreach(var c in project.Components)
                foreach(var scope in Scopes(c))
                    foreach(var saved in scope.Item2.Selections)
                    {
                        saved.Reference=Reference(document,Resolve(document,saved.Reference)??throw new InvalidOperationException(c.Name+": updated selection is missing."));
                        if(!string.IsNullOrEmpty(saved.ComponentReference))saved.ComponentReference=Reference(document,Resolve(document,saved.ComponentReference)??throw new InvalidOperationException(c.Name+": updated component is missing."));
                    }
            foreach(var anchor in project.Anchors.Where(a=>a.Status=="resolved"))
                try
                {
                    anchor.References=anchor.References.Select(r=>Reference(document,Resolve(document,r))).ToList();
                    anchor.BodyReferences=anchor.BodyReferences?.Select(r=>r==null?null:Reference(document,Resolve(document,r))).ToList();
                    if(!string.IsNullOrEmpty(anchor.ComponentReference))anchor.ComponentReference=Reference(document,Resolve(document,anchor.ComponentReference));
                }
                catch {anchor.Status="needs_repair";}
        }
    }
}
