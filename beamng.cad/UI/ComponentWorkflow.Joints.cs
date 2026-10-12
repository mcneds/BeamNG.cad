using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.UI
{
    internal sealed partial class ComponentWorkflow
    {
        private void PrepareNativeMate()
        {
            var receipt=CompanionAssemblyLink.Read(CompanionReceipt(false));
            if(!ComponentAssignments.SameDocument(receipt.Project,project.FilePath))throw new InvalidOperationException("Open the current companion to author native mates.");
            var manager=(SelectionMgr)model.SelectionManager;var selected=new List<object>();var instances=new Dictionary<string,Component2>();
            for(var i=1;i<=manager.GetSelectedObjectCount2(-1);i++)
            {
                selected.Add(manager.GetSelectedObject6(i,-1));var component=manager.GetSelectedObjectsComponent4(i,-1) as Component2;
                if(component!=null)instances[component.Name2]=component;
            }
            if(instances.Count<2)throw new InvalidOperationException("Select mate geometry on two companion members first.");
            foreach(var instance in instances.Values)
            {
                var reference=Convert.ToBase64String((byte[])model.Extension.GetPersistReference3(instance));
                var owners=project.Components.Where(c=>c.Selections.Any(s=>s.ComponentReference==reference)).ToArray();
                if(owners.Length!=1)throw new InvalidOperationException("Mate selection must belong to exactly one tagged companion group.");
                if(owners[0].Template=="calibrated_frame"||owners[0].MvpRole=="frame")continue;
                if(instance.IsFixed())
                {
                    model.ClearSelection2(true);instance.Select4(false,null,false);((AssemblyDoc)model).UnfixComponent();
                    var member=project.JointWorkspace.Members.FirstOrDefault(m=>m.ComponentReference==reference);if(member!=null)member.PlacementFixed=false;
                }
            }
            model.ClearSelection2(true);foreach(var item in selected)manager.AddSelectionListObject(item,manager.CreateSelectData());
            Save();if(!app.RunCommand(90,""))throw new InvalidOperationException("SolidWorks could not open Mate. Use Assembly > Mate with the selected companion geometry.");
        }
        private async Task ScanJoints()
        {
            await FramePipeline.JointReview.Refresh(app,model,project,settings,new Progress<string>(Report),cancel.Token);
            RefreshLists();status.Text="Scanned "+project.JointWorkspace.Mates.Count+" native mates. Review the proposed motion and bind actual hardpoints; failure settings remain separate.";
        }
        private ComponentDefinition RequestOwner(JointRequest request)
        {
            var exact=project.Components.FirstOrDefault(c=>request.Id.StartsWith(c.Id+".",StringComparison.Ordinal));
            if(exact!=null)return exact;
            var choices=project.Components.Where(c=>c.MvpRole==request.Role).ToArray();
            if(choices.Length==1)return choices[0];
            if(Selected!=null&&choices.Contains(Selected))return Selected;
            throw new InvalidOperationException("Select the physical CAD group for "+request.Label+" first.");
        }
        private void CaptureJointPoint(JointRequest request)
        {
            var owner=RequestOwner(request);var anchor=new MountAnchors(app,model).Capture(owner,request.Label);
            var previous=project.JointWorkspace.Bindings.FirstOrDefault(b=>b.Request==request.Id);
            if(previous?.AnchorId!=null)
            {
                anchor.Id=previous.AnchorId;project.Anchors.RemoveAll(a=>a.Id==anchor.Id);
            }
            project.Anchors.Add(anchor);project.JointWorkspace.Bindings.RemoveAll(b=>b.Request==request.Id);
            project.JointWorkspace.Bindings.Add(new HardpointBinding {Request=request.Id,ComponentId=owner.Id,AnchorId=anchor.Id});
            project.JointWorkspace.Mode="authored";Save();RefreshLists();status.Text=request.Label+": CAD reference saved.";
        }
        private void BindJointCenter(JointRequest request)
        {
            var owner=RequestOwner(request);var choices=project.JointWorkspace.Joints.Where(j=>j.Status=="approved"&&j.Center?.Length==3&&(j.Parent==owner.Id||j.Child==owner.Id)).ToList();
            if(choices.Count==0)throw new InvalidOperationException("Scan and approve a joint on "+owner.Name+", or capture its actual CAD point.");
            var previous=project.JointWorkspace.Bindings.FirstOrDefault(b=>b.Request==request.Id);
            var captured=project.Anchors.FirstOrDefault(a=>a.Id==previous?.AnchorId&&a.Status=="resolved"&&a.ComponentId==owner.Id);
            using(var picker=new Form {Text="Choose reviewed joint for "+request.Label,Width=680,Height=350,StartPosition=FormStartPosition.CenterParent})
            {
                var items=new ListBox {Dock=DockStyle.Fill,DisplayMember="Label",DataSource=choices};
                var keepPoint=new CheckBox {Text="Keep the captured CAD point on this joint (for distinct hinge pivots / bearing endpoints)",Dock=DockStyle.Bottom,Height=44,Enabled=captured!=null,Checked=captured!=null};
                var apply=new Button {Text="Bind selected joint",Dock=DockStyle.Bottom,DialogResult=DialogResult.OK};picker.Controls.Add(items);picker.Controls.Add(keepPoint);picker.Controls.Add(apply);
                if(picker.ShowDialog(this)!=DialogResult.OK)return;
                var selected=(JointDefinition)items.SelectedItem;
                project.JointWorkspace.Bindings.RemoveAll(b=>b.Request==request.Id);
                project.JointWorkspace.Bindings.Add(new HardpointBinding {Request=request.Id,ComponentId=owner.Id,JointId=selected.Id,
                    AnchorId=keepPoint.Checked?captured.Id:null,Point=keepPoint.Checked?"anchor":"center"});
                project.JointWorkspace.Mode="authored";Save();RefreshLists();
            }
        }
        private void ApproveJoint(string id)
        {
            var joint=project.JointWorkspace.Joints.Single(j=>j.Id==id);
            if(!new[]{"spherical","revolute","prismatic","cylindrical","rigid"}.Contains(joint.Kind)||!string.IsNullOrEmpty(joint.Issue))
                throw new InvalidOperationException("Resolve the unsupported/conflicting mate arrangement before approval: "+joint.Issue);
            if(joint.Source=="mates"&&(project.JointWorkspace.ScanStamp!=model.GetUpdateStamp()||project.JointWorkspace.ScanConfiguration!=model.ConfigurationManager.ActiveConfiguration.Name))
                throw new InvalidOperationException("CAD changed since the scan. Scan native mates again before approving.");
            joint.Status="approved";Save();RefreshLists();
        }
        private void HighlightJoint(string id)
        {
            var binding=project.JointWorkspace.Bindings.FirstOrDefault(b=>b.Request==id);
            var joint=project.JointWorkspace.Joints.FirstOrDefault(j=>j.Id==id||j.Id==binding?.JointId);
            var owner=id.StartsWith("panel:")?id.Substring(6):binding?.ComponentId??joint?.Child;
            var component=project.Components.FirstOrDefault(c=>c.Id==owner);
            if(component==null)throw new InvalidOperationException("Bind this request to actual CAD before highlighting it.");
            var anchor=project.Anchors.FirstOrDefault(a=>a.Id==binding?.AnchorId);
            var references=anchor?.References??project.JointWorkspace.Mates.Where(m=>joint?.MateIds.Contains(m.Id)==true)
                .SelectMany(m=>m.Entities).Select(e=>e.Reference).Where(r=>!string.IsNullOrEmpty(r)).Distinct().ToList();
            if(references.Count>0)
            {
                var geometry=new List<object>();
                foreach(var reference in references)
                {
                    int state;var entity=model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out state);
                    if(entity==null||state!=0)throw new InvalidOperationException("This joint reference no longer resolves. Scan mates or recapture the CAD point.");
                    geometry.Add(entity);
                }
                model.ClearSelection2(true);var manager=(SelectionMgr)model.SelectionManager;
                foreach(var entity in geometry)manager.AddSelectionListObject(entity,manager.CreateSelectData());
                model.ViewZoomToSelection();model.GraphicsRedraw2();
                var point=anchor?.Position??joint?.Center;
                status.Text="Selected the saved joint geometry"+(point==null?".":"; centre in BeamNG metres: "+string.Join(", ",point.Select(p=>p.ToString("F4",System.Globalization.CultureInfo.InvariantCulture))));
                return;
            }
            selection.Show(Assignment(component));model.ViewZoomToSelection();model.GraphicsRedraw2();
        }
        private Task EditMovingMembers()
        {
            var component=Required();
            var editor=new MovingMembersPanel(app,model,project,component);
            editor.Saved+=()=>{Save();RefreshLists();};
            editor.AppearanceRefreshRequested+=()=>RunMovingOperation(editor,()=>RefreshCompanionAppearances(component));
            editor.SplitRequested+=()=>RunMovingOperation(editor,async()=>
            {
                Save();var result=await new AssociationAssembly(app,model).SplitMembers(project,CompanionReceipt(false),component.Id,
                    (value,message)=>{progress.Style=ProgressBarStyle.Continuous;progress.Value=value;status.Text=message;editor.OperationFeedback(message);},cancel.Token);
                ShowCompanion(result,"Moving members created in a new companion revision. Rebind affected mates and inspect their motion.");
                editor.Close();
            });
            editor.Show(this);return Task.CompletedTask;
        }
        private void RunMovingOperation(MovingMembersPanel dialog,Func<Task> action)
        {
            Run(async()=>
            {
                dialog.Enabled=false;dialog.OperationFeedback("Working…");
                try
                {
                    selection.ValidateDocument();await action();
                    dialog.OperationFeedback(status.Text);
                }
                catch(OperationCanceledException){dialog.OperationFeedback("Cancelled. Saved classifications retained.");throw;}
                catch(Exception error){dialog.OperationFailed(error);throw;}
                finally {if(!dialog.IsDisposed)dialog.Enabled=true;}
            },false);
        }
        private async Task VerifyAttachments()
        {
            var receipt=VehicleProject.Load(project.FilePath).LastBuildReceipt;FramePipeline.ModPackage.ArchivePath(receipt);
            var manifest=Path.Combine(Path.GetDirectoryName(receipt),"manifest.json");
            if(!File.Exists(manifest))throw new InvalidOperationException("Generate a package with the reviewed fasteners first.");
            var arguments="verify --mounts-only --manifest "+FramePipeline.OwnedWorker.Quote(manifest)+" --project "+FramePipeline.OwnedWorker.Quote(project.FilePath)
                +" --game "+FramePipeline.OwnedWorker.Quote(settings.GameDirectory)+" --profile "+FramePipeline.OwnedWorker.Quote(settings.HarnessProfile)
                +(settings.SaveBuildReports=="true"?" --save-report":"");
            await FramePipeline.OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Worker,arguments,new Progress<string>(Report),cancel.Token,null,settings.FrameOutput);
            status.Text="Packaged attachment tests passed. Review first-fastener and detached-panel captures. This checks generated behavior; real fastener strength still needs hardware calibration.";
        }
    }
}
