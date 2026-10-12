using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    // Resolves only the requested component chain; never unsuppresses geometry.
    internal sealed class SelectionNormalizer
    {
        private readonly ModelDoc2 model;
        public SelectionNormalizer(ModelDoc2 model) { this.model=model; }
        private string Reference(object item)
        {
            var bytes=model.Extension.GetPersistReference3(item) as byte[];
            if(bytes==null || bytes.Length==0)throw new InvalidOperationException("Cannot retain this selection while loading its component. Resolve the component and reselect the affected face/body.");
            return Convert.ToBase64String(bytes);
        }
        private object Resolve(string reference)
        {
            int error;
            var item=model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out error);
            if(error==(int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Suppressed)
                throw new InvalidOperationException("Selected item is genuinely suppressed in this configuration. Unsuppress it explicitly in SolidWorks or reselect available geometry.");
            if(item==null || error!=0)throw new InvalidOperationException("The selected item is no longer available after loading its component. Reselect that item.");
            return item;
        }
        public Component2 Available(Component2 component,bool load)
        {
            if(component==null)throw new InvalidOperationException("Selected geometry has no assembly component owner.");
            var state=(swComponentSuppressionState_e)component.GetSuppression2();
            if(state==swComponentSuppressionState_e.swComponentSuppressed)
                throw new InvalidOperationException("Component is genuinely suppressed in this configuration: "+component.Name2);
            if(state==swComponentSuppressionState_e.swComponentInternalIdMismatch)
                throw new InvalidOperationException("Component reference has an internal ID mismatch: "+component.Name2+". Reload the component and replace its saved selection.");
            if(state==swComponentSuppressionState_e.swComponentResolved || state==swComponentSuppressionState_e.swComponentFullyResolved)return component;
            if(state!=swComponentSuppressionState_e.swComponentLightweight && state!=swComponentSuppressionState_e.swComponentFullyLightweight)
                throw new InvalidOperationException("Unknown component loading state "+(int)state+": "+component.Name2);
            if(!load)throw new InvalidOperationException("Component is lightweight (not suppressed): "+component.Name2+". Run a selection/material action to load its model data.");
            var reference=Reference(component);var name=component.Name2;
            var parent=component.GetParent() as Component2;
            if(parent!=null)Available(parent,true);
            component=(Component2)Resolve(reference);
            // Resolved (3) affects this component only, unlike FullyResolved (2).
            var result=component.SetSuppression2((int)swComponentSuppressionState_e.swComponentResolved);
            component=(Component2)Resolve(reference);
            state=(swComponentSuppressionState_e)component.GetSuppression2();
            if(state!=swComponentSuppressionState_e.swComponentResolved && state!=swComponentSuppressionState_e.swComponentFullyResolved)
                throw new InvalidOperationException("Could not load lightweight component "+name+" (result "+result+", state "+(int)state+"). Resolve it in SolidWorks and retry.");
            return component;
        }
        private sealed class Pick
        {
            public string Item,Component,Description;
            public bool WholeComponent;
        }
        private IEnumerable<Body2> FolderBodies(Feature feature)
        {
            if(feature.GetSpecificFeature2() is BodyFolder folder)
                foreach(Body2 body in folder.GetBodies() as object[] ?? new object[0])yield return body;
            for(var child=feature.GetFirstSubFeature() as Feature;child!=null;child=child.GetNextSubFeature() as Feature)
                foreach(var body in FolderBodies(child))yield return body;
        }
        public FrameAssignment Capture()=>CaptureGeometry(false,false);
        public FrameAssignment CaptureComponentGeometry(bool wholeComponents)=>CaptureGeometry(true,wholeComponents);
        private FrameAssignment CaptureGeometry(bool allowSheets,bool wholeComponents)
        {
            var manager=(SelectionMgr)model.SelectionManager;
            var picks=new List<Pick>();
            // Capture every reference before any lightweight-to-resolved transition.
            for(var i=1;i<=manager.GetSelectedObjectCount2(-1);i++)
            {
                var item=manager.GetSelectedObject6(i,-1);
                if(item is Feature componentFeature && componentFeature.GetSpecificFeature2() is Component2 instance)item=instance;
                var owner=item as Component2 ?? manager.GetSelectedObjectsComponent4(i,-1) as Component2;
                var folder=item as Feature;
                if(!wholeComponents && !(item is Component2) && !(item is Body2) && !(item is Face2) && !(item is Edge) && !(item is Vertex) && !(item is Feature))
                    throw new InvalidOperationException("Selected item "+i+" is "+((swSelectType_e)manager.GetSelectedObjectType3(i,-1))+" and does not identify body geometry. Select a visible body, face, edge, vertex, geometry feature or component.");
                if(owner==null)throw new InvalidOperationException("Selected item "+i+" has no component owner.");
                picks.Add(new Pick {Item=wholeComponents?null:Reference(item),Component=Reference(owner),WholeComponent=wholeComponents||item is Component2,Description=owner.Name2+" / selected item "+i});
            }
            if(picks.Count==0)throw new InvalidOperationException("Select bodies, faces, body folders, or components in SolidWorks first.");
            var frame=new FrameAssignment {Configuration=model.ConfigurationManager.ActiveConfiguration.Name,SelectedItemCount=picks.Count};
            var bodiesByComponent=new Dictionary<string,ILookup<string,Body2>>();
            foreach(var pick in picks)
            {
                try
                {
                    var owner=Available((Component2)Resolve(pick.Component),true);
                    if(pick.WholeComponent)
                    {
                        frame.Selections.Add(new SelectionReference {Kind="component",Reference=pick.Component,Name=owner.Name2});
                        continue;
                    }
                    var item=Resolve(pick.Item);
                    IEnumerable<Body2> selectedBodies;
                    if(item is Body2 body)selectedBodies=new[]{body};
                    else if(item is Face2 face)selectedBodies=new[]{face.GetBody() as Body2};
                    else if(item is Edge edge)selectedBodies=new[]{edge.GetBody() as Body2};
                    else if(item is Vertex vertex)selectedBodies=(vertex.GetAdjacentFaces() as object[] ?? new object[0]).Cast<Face2>().Select(f=>f.GetBody() as Body2);
                    else if(item is Feature feature && feature.GetSpecificFeature2() is BodyFolder)selectedBodies=FolderBodies(feature);
                    else if(item is Feature surface)
                        selectedBodies=(surface.GetFaces() as object[] ?? new object[0]).Cast<Face2>().Select(f=>f.GetBody() as Body2);
                    else throw new InvalidOperationException("Selection changed type while its component was loaded. Reselect it.");
                    if(!bodiesByComponent.TryGetValue(pick.Component,out var candidates))
                    {
                        object info;
                        candidates=(owner.GetBodies3(allowSheets?(int)swBodyType_e.swAllBodies:(int)swBodyType_e.swSolidBody,out info) as object[] ?? new object[0]).Cast<Body2>().ToLookup(b=>b.Name);
                        bodiesByComponent.Add(pick.Component,candidates);
                    }
                    var count=0;
                    foreach(var selected in selectedBodies)
                    {
                        if(selected==null || (selected.GetType()!=(int)swBodyType_e.swSolidBody && (!allowSheets||selected.GetType()!=(int)swBodyType_e.swSheetBody)))
                            throw new InvalidOperationException(allowSheets?"Select a solid or surface body; wire bodies are not supported.":"Frame/material selection requires solid bodies. For surface panels use Components / mounts with a surface weight option.");
                        var matches=candidates[selected.Name].ToArray();
                        if(string.IsNullOrEmpty(selected.Name) || matches.Length!=1)throw new InvalidOperationException("Cannot uniquely map the selected body in its owning component. Reselect it after resolving the component.");
                        // Use the owning instance's body, not the part-context body
                        // returned by a cut-list folder shared by several instances.
                        frame.Selections.Add(new SelectionReference {Kind="body",Reference=Reference(matches[0]),ComponentReference=pick.Component,Name=owner.Name2+" / "+matches[0].Name});
                        count++;
                    }
                    if(count==0)throw new InvalidOperationException("This selection has no solid or surface body geometry. Reference sketches, axes and planes have no mesh to assign. No assignment changed.");
                }
                catch(Exception e){throw new InvalidOperationException(pick.Description+": "+e.Message,e);}
            }
            frame.Selections=frame.Selections.GroupBy(s=>s.Kind+"|"+s.ComponentReference+"|"+s.Reference).Select(g=>g.First()).ToList();
            return frame;
        }
    }
}
