using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace BeamNG.Cad.Preparation
{
    internal static class ComponentAssignments
    {
        public static ComponentDefinition CreateGroup(VehicleProject project,MvpRole role)=>CreateNamedGroup(project,role,null);
        public static ComponentDefinition CreateNamedGroup(VehicleProject project,MvpRole role,string requestedName)
        {
            // Repeated panels/shaft sections can keep their role. A new row must
            // never inherit an existing frame or other unique physical owner.
            var repeat=role?.Repeatable==true;
            var basis=!string.IsNullOrWhiteSpace(requestedName)?requestedName.Trim():repeat?role.Label:"New component";var name=basis;var index=2;
            while(project.Components.Any(c=>string.Equals(c.Name,name,StringComparison.OrdinalIgnoreCase)))name=basis+" "+index++;
            var component=new ComponentDefinition {Name=name,MvpRole=repeat?role.Id:"",Template=repeat?role.Representation:"auto"};
            project.Components.Add(component);return component;
        }
        public static string Source(ComponentDefinition c,bool appearance)
        {
            var source=appearance?c.AppearanceSourceDocument:c.CadSourceDocument;
            if(!string.IsNullOrEmpty(source))return source;
            var directory=appearance?c.AppearanceDirectory:c.GeometryDirectory;
            if(string.IsNullOrEmpty(directory))return null;
            var path=Path.Combine(directory,"geometry.json");
            return File.Exists(path)?JsonFile.Read<GeometryPackage>(path)?.SourceDocument:null;
        }
        public static bool SameDocument(string a,string b)=>!string.IsNullOrWhiteSpace(a)&&!string.IsNullOrWhiteSpace(b)&&
            string.Equals(Path.GetFullPath(a),Path.GetFullPath(b),StringComparison.OrdinalIgnoreCase);
        public static string State(VehicleProject project,ComponentDefinition c,bool appearance)
        {
            var refs=appearance?c.AppearanceSelections:c.Selections;
            if(refs==null||refs.Count==0)return "missing";
            try
            {
                var source=Source(c,appearance);
                if(!string.IsNullOrWhiteSpace(source))return SameDocument(source,project.SourceDocument)?"saved":"other assembly";
                return "unverified";
            }
            catch(Exception e)when(e is IOException||e is UnauthorizedAccessException||e is System.Runtime.Serialization.SerializationException||e is ArgumentException){return "unavailable";}
        }
        public static void UpdateStatus(VehicleProject project)
        {
            foreach(var c in project.Components)
            {
                var cad=State(project,c,false);var visual=State(project,c,true);
                var custom=visual!="missing";
                if(CoiloverAppearance.Active(c))
                {
                    var assigned=CoiloverAppearance.Kinds.Count(k=>c.AppearanceCoilover.Pieces.Any(p=>p.Kind==k&&p.Selections?.Count>0));
                    visual="coilover "+assigned+"/3";custom=true;
                }
                else if(visual=="missing")visual=cad=="saved"?"uses CAD":cad=="other assembly"?"source CAD":cad=="missing"?"unassigned":"check CAD";
                else if(visual=="saved")visual="custom";
                if(custom&&c.AppearancePackageState=="pending")visual+=" (pending)";
                if(custom&&c.AppearancePackageState=="failed")visual+=" (update failed)";
                c.AssignmentSummary="CAD: "+(cad=="missing"?"unassigned":cad)+" | Appearance: "+visual;
            }
        }
        public static void Appearance(ComponentDefinition component,FrameAssignment selection,string document)
        {
            RequireSelection(selection);
            component.AppearanceSelections=Copy(selection.Selections);component.AppearanceConfiguration=selection.Configuration;
            component.AppearanceSourceDocument=document;component.AppearanceDirectory=null;component.AppearanceTransform=null;
            component.AppearancePackageState="pending";component.AppearancePackageError=null;
        }
        public static FrameAssignment CombinedPhysical(ComponentDefinition component,FrameAssignment selection,string document)
        {
            RequireSelection(selection);
            var existing=component.Selections??new List<SelectionReference>();
            if(existing.Count>0)
            {
                if(!SameDocument(Source(component,false),document))
                    throw new InvalidOperationException("The group's saved CAD belongs to another or unverified assembly. Set to selected to replace it. No assignment changed.");
                if(component.Configuration!=selection.Configuration)
                    throw new InvalidOperationException("Activate the group's saved configuration before adding CAD. No assignment changed.");
            }
            // Resolve the combined references before committing so unavailable
            // saved geometry and overlapping body/component picks are checked too.
            return new FrameAssignment {Configuration=selection.Configuration,Selections=Copy(existing.Concat(selection.Selections)
                .GroupBy(s=>new {s.Kind,s.Reference,s.ComponentReference}).Select(g=>g.First()).ToList())};
        }
        public static void Physical(VehicleProject project,ComponentDefinition component,FrameAssignment selection,List<string> bodyIds,string document)
        {
            RequireSelection(selection);
            if(bodyIds==null||bodyIds.Count==0)throw new InvalidOperationException("The selection has no available bodies.");
            var conflicts=project.Components.Where(c=>c.Id!=component.Id && (c.BodyIds??new List<string>()).Intersect(bodyIds).Any()).ToList();
            if(conflicts.Count>0)throw new InvalidOperationException("Selected bodies already belong to: "+string.Join(", ",conflicts.Select(c=>c.Name))+". No assignment changed.");
            component.Selections=Copy(selection.Selections);component.Configuration=selection.Configuration;component.BodyIds=bodyIds.ToList();
            component.CadSourceDocument=document;component.GeometryDirectory=null;
        }
        private static void RequireSelection(FrameAssignment selection)
        {
            if(selection==null||selection.Selections==null||selection.Selections.Count==0||string.IsNullOrEmpty(selection.Configuration))
                throw new InvalidOperationException("Select this group's CAD bodies or component instances first. No assignment changed.");
        }
        private static List<SelectionReference> Copy(List<SelectionReference> values)=>values.Select(s=>new SelectionReference {Kind=s.Kind,Name=s.Name,Reference=s.Reference,ComponentReference=s.ComponentReference}).ToList();
    }
}
