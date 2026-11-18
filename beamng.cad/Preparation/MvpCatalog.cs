using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using BeamNG.Cad.FramePipeline;

namespace BeamNG.Cad.Preparation
{
    [DataContract] internal sealed class MvpRole
    {
        [DataMember(Name="id")] public string Id;
        [DataMember(Name="label")] public string Label {get;set;}
        [DataMember(Name="representation")] public string Representation;
        [DataMember(Name="generator")] public string Generator {get;set;}
        [DataMember(Name="required")] public bool Required {get;set;}
        [DataMember(Name="repeatable")] public bool Repeatable {get;set;}
        [DataMember(Name="hardpoints")] public List<string> Hardpoints {get;set;}
    }
    [DataContract] internal sealed class MvpTemplateChoice
    {
        [DataMember] public string Category;
        [DataMember] public string Template;
    }
    [DataContract] internal sealed class MvpTemplateOption
    {
        [DataMember(Name="id")] public string Id {get;set;}
        [DataMember(Name="label")] public string Label {get;set;}
        [DataMember(Name="roles")] public List<string> Roles {get;set;}
        [DataMember(Name="hardpoints")] public Dictionary<string,List<string>> Hardpoints {get;set;}
        [DataMember(Name="joint_requests")] public List<JointRequest> JointRequests {get;set;}
    }
    [DataContract] internal sealed class JointRequest
    {
        [DataMember(Name="id")] public string Id;
        [DataMember(Name="label")] public string Label {get;set;}
        [DataMember(Name="role")] public string Role;
        [DataMember(Name="marker")] public string Marker;
        public override string ToString()=>Label;
    }
    [DataContract] internal sealed class MvpTemplateSet
    {
        [DataMember(Name="id")] public string Id {get;set;}
        [DataMember(Name="label")] public string Label {get;set;}
        [DataMember(Name="default")] public string Default {get;set;}
        [DataMember(Name="options")] public List<MvpTemplateOption> Options {get;set;}
    }
    [DataContract] internal sealed class MvpCatalog
    {
        [DataMember(Name="mvp_roles")] public List<MvpRole> Roles {get;set;}
        [DataMember(Name="mvp_base_roles")] public List<string> BaseRoles {get;set;}
        [DataMember(Name="mvp_template_sets")] public List<MvpTemplateSet> TemplateSets {get;set;}
        public static MvpCatalog Load()
        {
            var path=Path.Combine(Path.GetDirectoryName(typeof(MvpCatalog).Assembly.Location),"FramePipeline","template_catalog.json");
            using(var stream=File.OpenRead(path))
                return (MvpCatalog)new DataContractJsonSerializer(typeof(MvpCatalog),new DataContractJsonSerializerSettings {UseSimpleDictionaryFormat=true}).ReadObject(stream);
        }
        public MvpTemplateOption Selected(VehicleProject project,MvpTemplateSet set)
        {
            var id=project.MvpTemplates.FirstOrDefault(c=>c.Category==set.Id)?.Template??set.Default;
            return set.Options.Single(o=>o.Id==id);
        }
        public List<MvpRole> ActiveRoles(VehicleProject project)
        {
            var ids=new HashSet<string>(BaseRoles.Concat(TemplateSets.SelectMany(s=>Selected(project,s).Roles)));
            var hardpoints=TemplateSets.Select(s=>Selected(project,s)).Where(o=>o.Hardpoints!=null).SelectMany(o=>o.Hardpoints).ToDictionary(p=>p.Key,p=>p.Value);
            return Roles.Where(r=>ids.Contains(r.Id)||project.Driveline!=null&&Driveline.IsDriveRole(r.Id)).Select(r=>new MvpRole {Id=r.Id,Label=r.Label,Representation=r.Representation,Generator=r.Generator,
                Required=r.Required&&!(project.Driveline!=null&&Driveline.IsDriveRole(r.Id)),Repeatable=r.Repeatable||project.Driveline!=null&&Driveline.IsDriveRole(r.Id),Hardpoints=project.Driveline!=null&&Driveline.IsDriveRole(r.Id)?new List<string>():hardpoints.TryGetValue(r.Id,out var points)?points:r.Hardpoints}).ToList();
        }
        public List<JointRequest> JointRequests(VehicleProject project)
        {
            var result=TemplateSets.SelectMany(s=>Selected(project,s).JointRequests??new List<JointRequest>()).ToList();
            foreach(var c in project.Components.Where(c=>project.Driveline==null&&((c.MvpRole??"").EndsWith("_halfshaft")||c.MvpRole=="front_propshaft"||c.MvpRole=="cvt_output_shaft")))
                foreach(var end in new[]{c.MvpRole.EndsWith("_halfshaft")?"inner_joint":"input_joint",c.MvpRole.EndsWith("_halfshaft")?"outer_joint":"output_joint"})
                    result.Add(new JointRequest {Id=c.Id+"."+end,Role=c.MvpRole,Label=c.Name+" "+end.Replace('_',' ')});
            return result;
        }
        public string Checklist(VehicleProject project)
        {
            var lines=new List<string> {string.Join(" | ",TemplateSets.Select(s=>s.Label+": "+Selected(project,s).Label)),"Tags retain CAD ownership; they do not certify geometry, joints or vehicle behavior. Optional roles may be absent.","Use Refresh tagged CAD to export a reusable inventory and current mounting references.",""};
            var active=ActiveRoles(project);
            foreach(var role in active)
            {
                var assigned=project.Components.Where(c=>c.MvpRole==role.Id || (role.Id=="frame" && c.Template=="calibrated_frame")).ToList();
                var state=assigned.Count==0?(role.Required?"MISSING":"OPTIONAL"):assigned.Count>1&&!role.Repeatable?"DUPLICATE":
                    assigned.All(c=>ComponentAssignments.State(project,c,false)=="saved")?"CAD SAVED":"CAD NEEDED";
                lines.Add(state+" | "+role.Label+" | "+string.Join(", ",assigned.Select(c=>c.Name))+" | "+role.Generator);
                if(role.Hardpoints.Count>0)lines.Add("    Required hardpoints: "+string.Join(", ",role.Hardpoints));
                if(project.Driveline==null && assigned.Count>1 && (role.Id=="front_propshaft" || role.Id=="cvt_output_shaft"))
                    lines.Add("    Review ordered shaft_chains in the template: one CAD group per section, joint centres, plunge and carrier supports. List order does not define the chain.");
            }
            if(project.Driveline!=null)lines.AddRange(project.Driveline.ReferenceIssues(project).Select(s=>"DRIVELINE: "+s));
            var driveOwners=new HashSet<string>(project.Driveline?.Endpoints.Select(e=>e.Component)??Enumerable.Empty<string>());
            if(project.Driveline!=null)driveOwners.UnionWith(project.Driveline.Shafts.Select(s=>s.Component));
            var untagged=project.Components.Where(c=>string.IsNullOrEmpty(c.MvpRole)&&c.Template!="calibrated_frame"&&!driveOwners.Contains(c.Id)).ToList();
            if(untagged.Count>0)lines.Add("UNTAGGED: "+string.Join(", ",untagged.Select(c=>c.Name)));
            foreach(var c in project.Components.Where(c=>!string.IsNullOrEmpty(c.MvpRole)&&!active.Any(r=>r.Id==c.MvpRole)))lines.Add("OUTSIDE CURRENT SETUP: "+c.Name+" ["+c.MvpRole+"] - selection retained");
            return string.Join(System.Environment.NewLine,lines);
        }
        public void AddMissingGroups(VehicleProject project)
        {
            foreach(var role in ActiveRoles(project).Where(r=>r.Required))
                if(!project.Components.Any(c=>c.MvpRole==role.Id))
                    project.Components.Add(new ComponentDefinition {Name=role.Label,MvpRole=role.Id,Template=role.Representation=="calibrated_frame"?"calibrated_frame":role.Representation=="panel"?"panel":"auto"});
        }
    }
}
