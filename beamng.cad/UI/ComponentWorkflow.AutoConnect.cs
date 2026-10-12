using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Threading.Tasks;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;
using BeamNG.Cad.FramePipeline;

namespace BeamNG.Cad.UI
{
    internal sealed partial class ComponentWorkflow
    {
        [DataContract] private sealed class AutoConnectReport
        {
            [DataMember] public List<AutoConnectRow> Rows=new List<AutoConnectRow>();
        }
        [DataContract] private sealed class AutoConnectRow
        {
            [DataMember] public string Id,ComponentId,Name,Status,Issue,PreviewFile;
            [DataMember] public List<MountAnchor> Anchors;
            [DataMember] public List<MountConnection> Connections;
            [DataMember] public JointDefinition Joint;
            [DataMember] public List<HardpointBinding> Bindings;
            public override string ToString()=>Name+" | "+Status+(string.IsNullOrEmpty(Issue)?"":" | "+Issue);
        }
        private void RefreshVisualMembers()
        {
            var owner=(visualParent.SelectedItem as AnchorItem)?.Id;var current=Selected?.VisualParentMemberId;
            visualMember.DataSource=new[]{new AnchorItem {Id="",Label="Whole physical parent"}}.Concat(project.JointWorkspace.Members.Where(m=>m.ComponentId==owner).Select(m=>new AnchorItem {Id=m.Id,Label=m.Name+" / "+m.Kind})).ToList();
            visualMember.SelectedItem=visualMember.Items.Cast<AnchorItem>().FirstOrDefault(v=>v.Id==current)??visualMember.Items[0];
        }
        private async Task AcknowledgeVisualMass()
        {
            SaveParameters();var component=Required();
            if(component.Representation!="visual_only")throw new InvalidOperationException("Select Visual only first. This means no independent collision or breakaway.");
            await Export(component);var output=NewFolder("visual-mass-review")+".json";await WorkerRun("acknowledge-mass",output,component.Id);
            var data=new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<Dictionary<string,string>>(File.ReadAllText(output));component.MassAcknowledgement=data["Hash"];Save();RefreshLists();
            status.Text=component.Name+": visual only, mass excluded. The label remains visible; changed geometry requires review again.";
        }
        private async Task EnsureCurrentFrame()
        {
            var check=NewFolder("frame-readiness")+".json";await WorkerRun("frame-current",check);
            var result=new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(check));if((bool)result["Current"])return;
            Report("Regenerating frame: "+result["Reason"]);var frame=project.Components.Single(c=>c.Template=="calibrated_frame");var output=NewFolder("automatic-frame");
            await OwnedWorker.RunWithScratch(settings.PythonExecutable,Path.Combine(Path.GetDirectoryName(Worker),"prepare_frame.py"),"--geometry "+OwnedWorker.Quote(Path.Combine(frame.GeometryDirectory,"geometry.json"))+" --materials "+OwnedWorker.Quote(settings.FrameSource)+" --output "+OwnedWorker.Quote(output)+" --blender "+OwnedWorker.Quote(settings.BlenderExecutable)+" --cgal "+OwnedWorker.Quote(settings.CgalPythonExecutable),new Progress<string>(Report),cancel.Token,null,settings.FrameOutput);
            await WorkerRun("mount-plan",Path.Combine(output,"frame-mounts.json"));var generation=await CalibrationBuilder.PrepareAsync(settings,output,new Progress<string>(Report),cancel.Token);
            using(var review=new FixtureReview(Path.Combine(generation,"review.json")))if(review.ShowDialog(this)!=DialogResult.OK)throw new OperationCanceledException("Frame fixtures need review; prepared generation retained.");
            const string material="solidworks-assigned";
            await CalibrationBuilder.CalibrateSelectedAsync(settings,generation,material,new Progress<string>(Report),cancel.Token);
            var receipt=await CalibrationBuilder.PackageProjectAsync(settings,generation,material,project,new Progress<string>(Report),cancel.Token);project.SelectFrameBuild(receipt);project.FrameBuildReceipt=receipt;settings.LastCalibrationGeneration=generation;settings.Save();Save();
        }
        private async Task AutoConnect()
        {
            if(Selected!=null)SaveParameters();
            decimal inset=10,range=50;
            using(var options=new Form {Text="Auto-connect — starting settings",Width=580,Height=250,StartPosition=FormStartPosition.CenterParent})
            {
                var controls=new FlowLayoutPanel {Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown};var corner=Number(0,100,10);var distance=Number(1,1000,50);
                controls.Controls.Add(new Label {AutoSize=true,Text="Corner inset (mm)"});controls.Controls.Add(corner);controls.Controls.Add(new Label {AutoSize=true,Text="Maximum inward support distance (mm)"});controls.Controls.Add(distance);
                var next=new Button {Text="Generate preview",AutoSize=true,DialogResult=DialogResult.OK};controls.Controls.Add(next);options.Controls.Add(controls);
                if(options.ShowDialog(this)!=DialogResult.OK)return;inset=corner.Value;range=distance.Value;
            }
            await ScanJoints();var stamp=model.GetUpdateStamp();
            foreach(var component in project.Components){cancel.Token.ThrowIfCancellationRequested();await Export(component);}
            if(stamp!=model.GetUpdateStamp())throw new InvalidOperationException("CAD changed while exporting. Run Auto-connect again.");
            var output=NewFolder("auto-connect")+".json";var snapshot=output+".input.json";JsonFile.Write(snapshot,project);
            await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,Worker,"auto-connect --project "+OwnedWorker.Quote(snapshot)+" --output "+OwnedWorker.Quote(output)+" --corner-inset "+((double)inset/1000).ToString(System.Globalization.CultureInfo.InvariantCulture)+" --support-distance "+((double)range/1000).ToString(System.Globalization.CultureInfo.InvariantCulture),new Progress<string>(Report),cancel.Token,null,settings.FrameOutput);
            var report=JsonFile.Read<AutoConnectReport>(output);HullPreview overlay=null;var previewRevision=0;
            using(var dialog=new Form {Text="Auto-connect — preview and apply",Width=1080,Height=660,StartPosition=FormStartPosition.CenterParent})
            {
                var search=new TextBox {Dock=DockStyle.Top};var list=new CheckedListBox {Dock=DockStyle.Fill,HorizontalScrollbar=true,CheckOnClick=true};
                var detail=new Label {Dock=DockStyle.Bottom,Height=78,Text="Checked Ready entries create editable connections. Existing manual fasteners remain available in Panel / accessory fasteners. Select a row to highlight its component."};
                var apply=new Button {Text="Apply checked proposals",Dock=DockStyle.Bottom,Height=36};var checkedIds=new HashSet<string>(report.Rows.Where(r=>r.Status=="ready").Select(r=>r.Id));
                Action filter=()=>{list.Items.Clear();foreach(var row in report.Rows.Where(r=>r.ToString().IndexOf(search.Text,StringComparison.OrdinalIgnoreCase)>=0))list.Items.Add(row,checkedIds.Contains(row.Id));};
                search.TextChanged+=(s,e)=>filter();list.ItemCheck+=(s,e)=>{var row=(AutoConnectRow)list.Items[e.Index];if(row.Status!="ready"){e.NewValue=CheckState.Unchecked;return;}if(e.NewValue==CheckState.Checked)checkedIds.Add(row.Id);else checkedIds.Remove(row.Id);};
                list.SelectedIndexChanged+=async(s,e)=>{if(!(list.SelectedItem is AutoConnectRow row))return;var revision=++previewRevision;overlay?.Dispose();overlay=null;
                    var parentIds=new HashSet<string>((row.Anchors??new List<MountAnchor>()).Where(a=>(row.Connections??new List<MountConnection>()).Any(c=>c.AnchorA==a.Id)).Select(a=>a.ComponentId));
                    var parents=string.Join(", ",project.Components.Where(c=>parentIds.Contains(c.Id)).Select(c=>c.Name));
                    detail.Text=row.ToString()+"\r\n"+(row.Connections==null?"Native joint / required point review.":row.Connections.Count+" editable connections. Support: "+parents+". "+(row.Connections.Any(c=>c.Template=="breakable_fastener")?"Independent failure; 6 mm connector; provisional 4000 N per beam.":"Permanent rigid attachment."));
                    var owner=project.Components.FirstOrDefault(c=>c.Id==row.ComponentId);try{if(owner!=null){selection.Show(Assignment(owner));model.GraphicsRedraw2();}if(File.Exists(row.PreviewFile)){var next=await HullPreview.CreateAsync(app,model,row.PreviewFile,AxisMapping.Standard,true,cancel.Token,selection.ValidateDocument,Report);if(revision!=previewRevision||dialog.IsDisposed)next.Dispose();else overlay=next;}}catch(Exception ex){if(!dialog.IsDisposed)detail.Text+="\r\n"+ex.Message;}};
                apply.Click+=(s,e)=>{dialog.DialogResult=DialogResult.OK;dialog.Close();};dialog.Controls.Add(list);dialog.Controls.Add(search);dialog.Controls.Add(detail);dialog.Controls.Add(apply);filter();
                var answer=dialog.ShowDialog(this);previewRevision++;overlay?.Dispose();overlay=null;if(answer!=DialogResult.OK)return;
                if(stamp!=model.GetUpdateStamp())throw new InvalidOperationException("CAD changed during review. Preview again.");
                var rows=report.Rows.Where(r=>r.Status=="ready"&&checkedIds.Contains(r.Id)).ToArray();if(rows.Length==0)return;
                File.Copy(project.FilePath,output+".before.beamng-project.json",false);
                foreach(var row in rows)
                {
                    if(row.Joint!=null){row.Joint.Status="approved";project.JointWorkspace.Joints.RemoveAll(j=>j.Id==row.Joint.Id);project.JointWorkspace.Joints.Add(row.Joint);foreach(var binding in row.Bindings??new List<HardpointBinding>()){var previous=project.JointWorkspace.Bindings.FirstOrDefault(b=>b.Request==binding.Request);if(previous!=null&&previous.GeneratedSource!="joint_inference")continue;project.JointWorkspace.Bindings.RemoveAll(b=>b.Request==binding.Request);project.JointWorkspace.Bindings.Add(binding);}}
                    if(row.Connections==null){foreach(var anchor in row.Anchors??new List<MountAnchor>()){project.Anchors.RemoveAll(a=>a.Id==anchor.Id);project.Anchors.Add(anchor);}continue;}
                    var childAnchors=new HashSet<string>(project.Anchors.Where(a=>a.ComponentId==row.ComponentId).Select(a=>a.Id));var old=project.Connections.Where(c=>childAnchors.Contains(c.AnchorB)&&c.GeneratedSource=="auto_connect"&&!c.UserEdited).ToArray();var removed=new HashSet<string>(old.SelectMany(c=>new[]{c.AnchorA,c.AnchorB}));
                    project.Connections.RemoveAll(c=>old.Contains(c));var used=new HashSet<string>(project.Connections.SelectMany(c=>new[]{c.AnchorA,c.AnchorB}));project.Anchors.RemoveAll(a=>removed.Contains(a.Id)&&!used.Contains(a.Id));
                    project.Anchors.AddRange(row.Anchors);project.Connections.AddRange(row.Connections);
                }
                project.JointWorkspace.Mode="authored";Save();RefreshLists();status.Text="Applied "+rows.Length+" proposals. Manual fastener tools remain available. Undo project snapshot: "+output+".before.beamng-project.json";
            }
        }
    }
}
