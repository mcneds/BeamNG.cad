using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    // Guidance from saved contracts only. The compiler still validates geometry,
    // current CAD references, materials and the mounting definition at generation.
    internal sealed class VehicleReadiness
    {
        public string Title,Detail,ActionText,Stage,ComponentId;
        public bool CanGenerateFrame;
        public bool OpenAppearances;
        public readonly List<string> MissingCad=new List<string>();
        public int MissingHardpoints;

        public static VehicleReadiness Evaluate(VehicleProject project,MvpCatalog catalog,string configuration)
        {
            if(project==null)return new VehicleReadiness {Title="Choose a vehicle project",Detail="Open saved work or start a new project from your assembly.",Stage="Project",ActionText="Choose project"};
            var workspace=project.JointWorkspace;
            if(!string.IsNullOrWhiteSpace(project.PhysicsTemplateReceipt)&&workspace.Mode!="authored")
                return new VehicleReadiness {Title="Using imported physics",Detail="Assign your appearances in Components. Physical regeneration is a separate operation.",Stage="Components",ActionText="Assign appearances",CanGenerateFrame=true,OpenAppearances=true};
            var vehicle=workspace.Mode=="authored"||project.Driveline!=null||!string.IsNullOrWhiteSpace(project.TemplateDefinitionPath)||project.Components.Any(c=>!string.IsNullOrWhiteSpace(c.MvpRole)&&c.MvpRole!="frame");
            if(!vehicle)return FramePreflight(); // Preserve the calibrated frame-only route.

            var result=new VehicleReadiness();
            foreach(var role in catalog.ActiveRoles(project).Where(r=>r.Required))
            {
                var owners=project.Components.Where(c=>c.MvpRole==role.Id||(role.Id=="frame"&&c.Template=="calibrated_frame")).ToList();
                if(owners.Count==0)
                {
                    result.MissingCad.Add(role.Label+" (group missing)");
                    if(result.Stage==null)result.Stage="Project";
                }
                else
                {
                    var needsCad=owners.FirstOrDefault(c=>ComponentAssignments.State(project,c,false)!="saved"||(!string.IsNullOrEmpty(configuration)&&c.Configuration!=configuration));
                    var duplicate=owners.Count>1&&!role.Repeatable;
                    if(needsCad==null&&!duplicate)continue;
                    result.MissingCad.Add(role.Label);
                    if(result.Stage==null)
                    {
                        result.Stage="Components";
                        result.ComponentId=(needsCad??owners[0]).Id;
                        if(duplicate)result.Detail="Resolve the duplicate "+role.Label+" groups so this role has one owner.";
                        else if(role.Id=="frame")result.Detail="Choose Use saved frame to link the frame selection saved in Frame.";
                    }
                }
            }
            if(result.MissingCad.Count>0)
            {
                result.Title="Assign required component bodies ("+result.MissingCad.Count+")";
                result.Detail=(result.Detail??("Start with "+result.MissingCad[0]+". Assign separate CAD groups to bodies that move independently."))+" Then bind the actual joints and hardpoints before frame generation.";
                result.ActionText=result.Stage=="Project"?"Add required groups":"Assign required bodies";
                return result;
            }
            if(workspace.Mode=="authored")
            {
                string firstHardpoint=null;
                foreach(var request in catalog.JointRequests(project))
                {
                    var bindings=workspace.Bindings.Where(b=>b.Request==request.Id).ToList();
                    var owner=project.Components.FirstOrDefault(c=>request.Id.StartsWith(c.Id+".",StringComparison.Ordinal));
                    var roleOwners=project.Components.Where(c=>c.MvpRole==request.Role).Take(2).ToArray();
                    if(owner==null&&roleOwners.Length==1)owner=roleOwners[0];
                    if(bindings.Count==1&&owner!=null&&bindings[0].ComponentId==owner.Id&&BindingReviewed(project,bindings[0]))continue;
                    result.MissingHardpoints++;
                    if(firstHardpoint==null)firstHardpoint=request.Label;
                }
                var pending=workspace.Joints.Count(j=>(j.Status!="approved"&&j.Status!="positioning_only")||!string.IsNullOrEmpty(j.Issue));
                if(result.MissingHardpoints>0||pending>0)
                {
                    result.Title="Review actual joints and hardpoints";
                    result.Detail=result.MissingHardpoints+" required hardpoints need binding or repair. "+pending+" joints need review.";
                    if(firstHardpoint!=null)result.Detail+=" Start with "+firstHardpoint+".";
                    result.Stage="Joints";result.ActionText="Complete joints and hardpoints";return result;
                }
            }
            else if(string.IsNullOrWhiteSpace(project.TemplateDefinitionPath)||!File.Exists(project.TemplateDefinitionPath))
                return new VehicleReadiness {Title="Supply the actual mounting definition",Detail="Load your reviewed template JSON in Project tools, or switch to authored CAD joints in Joints.",Stage="Project",ActionText="Open mounting definition setup"};
            if(project.Driveline!=null)
            {
                var issues=project.Driveline.ReferenceIssues(project).ToList();
                if(issues.Count>0)return new VehicleReadiness {Title="Complete driveline endpoints",Detail=issues[0],Stage="Driveline",ActionText="Review driveline graph"};
            }
            return FramePreflight();
        }
        private static bool BindingReviewed(VehicleProject project,HardpointBinding binding)
        {
            if(binding.Status!="resolved")return false;
            if(!string.IsNullOrEmpty(binding.JointId))
            {
                var joint=project.JointWorkspace.Joints.FirstOrDefault(j=>j.Id==binding.JointId);
                if(joint==null||joint.Status!="approved"||!string.IsNullOrEmpty(joint.Issue)||(joint.Parent!=binding.ComponentId&&joint.Child!=binding.ComponentId))return false;
                if(binding.Point!="anchor")return true;
            }
            var anchor=project.Anchors.FirstOrDefault(a=>a.Id==binding.AnchorId);
            return anchor!=null&&anchor.Status=="resolved"&&anchor.ComponentId==binding.ComponentId;
        }
        private static VehicleReadiness FramePreflight()=>new VehicleReadiness {
            Title="Review the frame and run generation preflight",Detail="Saved setup is ready for the next checks. Generation still validates current CAD, materials and mounting geometry; preview alone is not calibration.",
            Stage="Frame",ActionText="Review frame / calibration",CanGenerateFrame=true};
    }
}
