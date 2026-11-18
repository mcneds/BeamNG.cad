using System;
using System.IO;
using BeamNG.Cad.Preparation;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.UI
{
    // UI lifetime only. Saved projects and receipts retain their existing contracts.
    internal sealed class ProjectSession
    {
        public VehicleProject Project {get;private set;}
        public ModelDoc2 Model {get;private set;}
        public string Configuration {get;private set;}
        public event Action Changed;
        public void Select(VehicleProject project,ModelDoc2 model)
        {
            Project=project;Model=model;Configuration=model?.ConfigurationManager.ActiveConfiguration.Name;Changed?.Invoke();
        }
        public void Refresh()
        {
            if(Project!=null)Project=VehicleProject.Load(Project.FilePath);
            Changed?.Invoke();
        }
        public string ContextProblem(ISldWorks app)
        {
            if(Project==null)return "Choose New from CAD or open a saved project.";
            var active=app.ActiveDoc as ModelDoc2;
            if(Model==null||active==null||!ComponentAssignments.SameDocument(active.GetPathName(),Project.SourceDocument))return "Activate this project's source assembly to edit CAD.";
            if(active.ConfigurationManager.ActiveConfiguration.Name!=Configuration)return "Activate configuration '"+Configuration+"', or resume the project in the current configuration.";
            // The same saved assembly can be reopened as a new native document.
            // Future editors must receive the current wrapper, not the closed one.
            Model=active;
            return null;
        }
        public string PackageLabel=>Project==null||!File.Exists(Project.LastBuildReceipt)?"No package generated":Path.GetFileName(Path.GetDirectoryName(Project.LastBuildReceipt));
    }
}
