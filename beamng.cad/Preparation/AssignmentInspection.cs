using System;
using System.IO;
using System.Linq;

namespace BeamNG.Cad.Preparation
{
    // Inspection never changes physical ownership or promotes an appearance.
    internal static class AssignmentInspection
    {
        public static FrameAssignment Capture(ComponentDefinition component,bool appearance)
        {
            if(component==null)throw new InvalidOperationException("Select a group in the Components list first.");
            var references=appearance?component.AppearanceSelections:component.Selections;
            var configuration=appearance?component.AppearanceConfiguration:component.Configuration;
            var label=appearance?"appearance":"physical CAD";
            if(references==null || references.Count==0)
                throw new InvalidOperationException(component.Name+": no saved "+label+" assignment. Choose the other assignment source or assign CAD to this group.");
            if(string.IsNullOrEmpty(configuration))
                throw new InvalidOperationException(component.Name+": the saved "+label+" assignment has no configuration. Reassign its CAD selection.");
            return new FrameAssignment {Id=component.Id,Role=component.Template,Configuration=configuration,Hull=component.Hull,
                Selections=references.Select(s=>new SelectionReference {Kind=s.Kind,Name=s.Name,Reference=s.Reference,ComponentReference=s.ComponentReference}).ToList()};
        }

        public static void CheckDocument(ComponentDefinition component,bool appearance,string document)
        {
            // Imported physics can retain references to a different assembly.
            // Do not try those opaque IDs against the user's current document.
            // New assignments retain their source even before an export exists.
            var source=ComponentAssignments.Source(component,appearance);
            if(!string.IsNullOrEmpty(source) && !string.Equals(Path.GetFullPath(source),Path.GetFullPath(document),StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException(component.Name+": this saved "+(appearance?"appearance":"physical CAD")+
                    " assignment belongs to another assembly: "+source+". Choose Appearance CAD for a replacement assigned in this assembly.");
        }
    }
}
