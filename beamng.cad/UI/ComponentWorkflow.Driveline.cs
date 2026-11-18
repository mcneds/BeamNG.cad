using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed partial class ComponentWorkflow
    {
        private readonly DrivelinePanel drivelinePanel=new DrivelinePanel();
        private void LoadReviewedDefinition(string path)
        {
            var json=new System.Web.Script.Serialization.JavaScriptSerializer {MaxJsonLength=int.MaxValue};
            var root=json.DeserializeObject(File.ReadAllText(path)) as System.Collections.Generic.Dictionary<string,object>;
            if(root==null)throw new InvalidOperationException("Choose a reviewed vehicle definition object.");
            var graph=root.TryGetValue("driveline",out var value)&&value!=null?Driveline.FromJson(json.Serialize(value)):null;
            project.TemplateDefinitionPath=path;if(graph!=null)project.Driveline=graph;
        }
        private void InitializeDriveline(TabControl tabs)
        {
            var page=new TabPage("Driveline");page.Controls.Add(drivelinePanel);tabs.TabPages.Insert(3,page);
            drivelinePanel.ApplyRequested+=value=>{project.Driveline=value;if(string.IsNullOrWhiteSpace(project.TemplateDefinitionPath))project.JointWorkspace.Mode="authored";Save();RefreshLists();};
            drivelinePanel.PresetRequested+=()=>Run(async()=>
            {
                Save();var path=NewFolder("driveline-preset")+".json";await WorkerRun("driveline-preset",path);
                drivelinePanel.Adopt(Driveline.Read(path));status.Text="Layout converted to an editable draft. Review the routes and capture any missing attachment or reaction datums. Existing files remain unchanged until Apply.";
            });
            drivelinePanel.CheckRequested+=()=>Run(async()=>
            {
                ResolveAnchors();Save();var path=NewFolder("driveline-check")+".json";try { await WorkerRun("driveline-check",path); }
                catch(Exception error) { drivelinePanel.SelectGraphIssue(error.Message); throw; }
                log.AppendText(File.ReadAllText(path)+Environment.NewLine);status.Text="Driveline references and torque connectivity passed. Physical generation and native motion acceptance remain required.";
            });
            drivelinePanel.CaptureRequested+=(id,axis)=>Run(()=>
            {
                var endpoint=project.Driveline.Endpoints.Single(e=>e.Id==id);
                var owner=project.Components.Single(c=>c.Id==endpoint.Component);
                var captured=new MountAnchors(app,model).Capture(owner,endpoint.Name+(axis?" axis point":" centre"));
                if(!string.IsNullOrEmpty(endpoint.Member))
                {
                    var member=project.JointWorkspace.Members.Single(m=>m.Id==endpoint.Member&&m.ComponentId==owner.Id);
                    using(var hash=System.Security.Cryptography.SHA256.Create())
                        foreach(var body in captured.BodyReferences.Where(b=>b!=null))
                        {
                            var bodyId="body_"+BitConverter.ToString(hash.ComputeHash(System.Text.Encoding.UTF8.GetBytes(captured.ComponentReference+"|"+body))).Replace("-","").ToLowerInvariant().Substring(0,24);
                            if(!member.BodyIds.Contains(bodyId))throw new InvalidOperationException("Select geometry belonging to this endpoint's moving member, or an explicit assembly datum.");
                        }
                }
                var previous=axis?endpoint.AxisAnchor:endpoint.Anchor;
                if(!string.IsNullOrEmpty(previous)&&!project.JointWorkspace.Bindings.Any(b=>b.AnchorId==previous)&&!project.Connections.Any(c=>c.AnchorA==previous||c.AnchorB==previous)&&!project.Driveline.Endpoints.Any(e=>e.Id!=id&&(e.Anchor==previous||e.AxisAnchor==previous)))
                    project.Anchors.RemoveAll(a=>a.Id==previous);
                project.Anchors.Add(captured);if(axis)endpoint.AxisAnchor=captured.Id;else{endpoint.Anchor=captured.Id;endpoint.Joint=null;}
                Save();RefreshLists();status.Text=endpoint.Name+": CAD "+(axis?"axis point":"centre")+" saved.";return Task.CompletedTask;
            });
            drivelinePanel.BindRequested+=id=>Run(()=>
            {
                var endpoint=project.Driveline.Endpoints.Single(e=>e.Id==id);
                var joints=project.JointWorkspace.Joints.Where(j=>j.Status=="approved"&&string.IsNullOrEmpty(j.Issue)&&j.Center?.Length==3&&(j.Parent==endpoint.Component||j.Child==endpoint.Component)&&(string.IsNullOrEmpty(endpoint.Member)||j.ParentMember==endpoint.Member||j.ChildMember==endpoint.Member)).ToList();
                if(joints.Count==0)throw new InvalidOperationException("Review a native joint on this owner first, or capture the centre and a separate axis point.");
                using(var picker=new Form {Text="Bind driveline endpoint",Width=650,Height=350,StartPosition=FormStartPosition.CenterParent})
                {
                    var list=new ListBox {Dock=DockStyle.Fill,DisplayMember="Label",DataSource=joints};var button=new Button {Text="Bind joint centre and axis",Dock=DockStyle.Bottom,DialogResult=DialogResult.OK};picker.Controls.Add(list);picker.Controls.Add(button);
                    if(picker.ShowDialog(this)!=DialogResult.OK)return Task.CompletedTask;
                    endpoint.Joint=((JointDefinition)list.SelectedItem).Id;
                }
                Save();RefreshLists();return Task.CompletedTask;
            });
            drivelinePanel.HighlightRequested+=id=>Run(()=>
            {
                var endpoint=project.Driveline.Endpoints.Single(e=>e.Id==id);
                var component=project.Components.Single(c=>c.Id==endpoint.Component);selection.Show(Assignment(component));model.ViewZoomToSelection();
                status.Text="Showing endpoint owner: "+component.Name;return Task.CompletedTask;
            });
        }
    }
}
