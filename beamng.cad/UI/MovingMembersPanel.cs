using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.UI
{
    internal sealed class MovingMembersPanel : Form
    {
        private readonly DataGridView grid=new DataGridView {Name="MovingBodyRows",Dock=DockStyle.Fill,AllowUserToAddRows=false,AllowUserToDeleteRows=false,AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill,SelectionMode=DataGridViewSelectionMode.FullRowSelect,MultiSelect=true};
        private readonly VehicleProject project;
        private readonly ComponentDefinition component;
        private readonly Label operationFeedback=new Label {Name="MovingOperationFeedback",AutoSize=true,MaximumSize=new System.Drawing.Size(680,0)};
        private readonly List<Tuple<string,SelectionReference>> bodies=new List<Tuple<string,SelectionReference>>();
        public event Action Saved,SplitRequested,AppearanceRefreshRequested;
        private static string Ref(ModelDoc2 doc,object value)=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(value));
        public MovingMembersPanel(ISldWorks app,ModelDoc2 model,VehicleProject project,ComponentDefinition component)
        {
            this.project=project;this.component=component;Text=component.Name+" - moving members";Width=740;Height=580;
            var help=new Label {Dock=DockStyle.Top,Height=80,Padding=new Padding(8),Text="Click a body row to highlight it in the assembly; Ctrl/Shift selects several. Give every body a moving-piece name. Use housing / shaft / spring for coilovers and housing / rack for steering. Saved classifications are reused. Splitting creates a new companion revision."};
            grid.Columns.Add(new DataGridViewTextBoxColumn {Name="Body",ReadOnly=true,HeaderText="CAD body",SortMode=DataGridViewColumnSortMode.NotSortable});
            var kinds=CoiloverAppearance.Supported(component)?new[]{"housing","shaft","spring"}:
                component.MvpRole=="steering_rack"?new[]{"housing","rack"}:new[]{"rigid","housing","shaft","slider","rotor","spring"};
            var choices=new[]{""}.Concat(kinds).Concat(project.JointWorkspace.Members.Where(m=>m.ComponentId==component.Id).Select(m=>m.Kind)).Where(k=>k!=null).Distinct().ToArray();
            var memberColumn=new DataGridViewComboBoxColumn {Name="Member",HeaderText="Moving piece",SortMode=DataGridViewColumnSortMode.NotSortable,FlatStyle=FlatStyle.Flat,
                DisplayStyle=DataGridViewComboBoxDisplayStyle.DropDownButton};
            memberColumn.Items.AddRange(choices);memberColumn.DefaultCellStyle.NullValue="Choose moving piece";grid.Columns.Add(memberColumn);
            grid.EditMode=DataGridViewEditMode.EditOnEnter;
            grid.CurrentCellDirtyStateChanged+=(s,e)=>{if(grid.IsCurrentCellDirty)grid.CommitEdit(DataGridViewDataErrorContexts.Commit);};
            var selector=new FrameSelection(app,model,true);
            foreach(var pair in selector.SnapshotBodies(new FrameAssignment {Configuration=component.Configuration,Selections=component.Selections}))
            {
                var selection=new SelectionReference {Kind="body",Name=pair.Item1.Name2+" / "+pair.Item2.Name,Reference=Ref(model,pair.Item2),ComponentReference=Ref(model,pair.Item1)};
                var id=selector.BodyIds(new FrameAssignment {Configuration=component.Configuration,Selections=new List<SelectionReference>{selection}}).Single();
                var member=project.JointWorkspace.Members.FirstOrDefault(m=>m.ComponentId==component.Id&&(m.BodyIds??new List<string>()).Contains(id))?.Kind;
                if(member==null)member=component.AppearanceCoilover?.Pieces?.FirstOrDefault(p=>p.BodyIds?.Contains(id)==true)?.Kind;
                bodies.Add(Tuple.Create(id,selection));grid.Rows.Add(selection.Name,member??"");
            }
            var feedback=new Label {Name="MovingBodyFeedback",AutoSize=true,MaximumSize=new System.Drawing.Size(680,0)};
            Action<bool> show=zoom=>{
                var rows=grid.SelectedRows.Cast<DataGridViewRow>().ToArray();
                if(rows.Length==0&&grid.CurrentRow!=null)rows=new[]{grid.CurrentRow};
                if(rows.Length==0)return;
                selector.Show(new FrameAssignment {Configuration=component.Configuration,Selections=rows.Select(r=>bodies[r.Index].Item2).ToList()});
                if(zoom)model.ViewZoomToSelection();model.GraphicsRedraw2();feedback.Text=rows.Length+" bodies highlighted in CAD.";
            };
            // SelectionChanged fires repeatedly during Ctrl/Shift selection and
            // validation. Coalesce it into one CAD call after the event finishes.
            var highlightPending=false;
            grid.SelectionChanged+=(s,e)=>{
                if(highlightPending||!IsHandleCreated||IsDisposed)return;
                highlightPending=true;BeginInvoke(new Action(()=>{
                    highlightPending=false;if(IsDisposed||Disposing)return;
                    try{show(false);}catch(Exception error){feedback.Text="Could not highlight: "+error.Message;}
                }));
            };
            grid.CellValueChanged+=(s,e)=>{if(e.RowIndex>=0)grid.Rows[e.RowIndex].Cells[1].Style.BackColor=System.Drawing.Color.Empty;};
            var buttons=new FlowLayoutPanel {Dock=DockStyle.Bottom,AutoSize=true};
            var assignKind=new ComboBox {Name="MovingPieceChoice",DropDownStyle=ComboBoxStyle.DropDownList,Width=130};assignKind.Items.AddRange(choices.Where(k=>k.Length>0).ToArray());assignKind.SelectedIndex=0;
            var assign=new Button {Text="Assign to selected bodies",AutoSize=true};assign.Click+=(s,e)=>Try(()=>{
                grid.EndEdit();foreach(var row in grid.SelectedRows.Cast<DataGridViewRow>())row.Cells[1].Value=assignKind.SelectedItem;
            });
            buttons.Controls.Add(assignKind);buttons.Controls.Add(assign);buttons.SetFlowBreak(assign,true);
            var save=new Button {Text="Save classifications",AutoSize=true};save.Click+=(s,e)=>Try(()=>Save());
            var split=new Button {Text="Create moving companion revision",AutoSize=true};split.Click+=(s,e)=>Try(()=>{
                grid.EndEdit();var missing=grid.Rows.Cast<DataGridViewRow>().Where(r=>string.IsNullOrWhiteSpace(Convert.ToString(r.Cells[1].Value))).ToArray();
                if(missing.Length>0){grid.ClearSelection();foreach(var row in missing){row.Selected=true;row.Cells[1].Style.BackColor=System.Drawing.Color.MistyRose;}
                    throw new InvalidOperationException(missing.Length+" bodies have no moving-piece assignment. The selected rows identify them. Choose their piece from the dropdown before splitting.");}
                Save();SplitRequested?.Invoke();});
            var zoomButton=new Button {Text="Zoom to selected bodies",AutoSize=true};zoomButton.Click+=(s,e)=>Try(()=>show(true));
            var refresh=new Button {Name="RefreshMovingAppearances",Text="Refresh colours from original CAD",AutoSize=true};
            refresh.Click+=(s,e)=>AppearanceRefreshRequested?.Invoke();
            new ToolTip().SetToolTip(refresh,"Restore original finishes without splitting again or replacing parts. Keeps folders and mates. Save companion CAD first.");
            buttons.Controls.Add(save);buttons.Controls.Add(zoomButton);buttons.Controls.Add(split);buttons.SetFlowBreak(split,true);buttons.Controls.Add(refresh);buttons.SetFlowBreak(refresh,true);buttons.Controls.Add(operationFeedback);buttons.SetFlowBreak(operationFeedback,true);buttons.Controls.Add(feedback);Controls.Add(grid);Controls.Add(help);Controls.Add(buttons);
        }
        public void OperationFeedback(string message,bool failed=false)
        {
            if(IsDisposed)return;
            operationFeedback.ForeColor=failed?System.Drawing.Color.DarkRed:System.Drawing.SystemColors.ControlText;
            operationFeedback.Text=message;
        }
        public void OperationFailed(Exception error)
        {
            if(IsDisposed)return;
            OperationFeedback("Failed: "+error.Message,true);
            MessageBox.Show(this,error.Message,"Moving members — action failed",MessageBoxButtons.OK,MessageBoxIcon.Warning);
        }
        private void Try(Action action){try{action();}catch(Exception error){MessageBox.Show(this,error.Message,"Moving members",MessageBoxButtons.OK,MessageBoxIcon.Information);}}
        private void Save()
        {
            grid.EndEdit();var result=new List<MovingMember>();
            foreach(var values in bodies.Select((b,i)=>new{Body=b,Kind=Convert.ToString(grid.Rows[i].Cells[1].Value).Trim().ToLowerInvariant()}).GroupBy(v=>v.Kind))
            {
                if(values.Key.Length==0)continue;
                var old=project.JointWorkspace.Members.FirstOrDefault(m=>m.ComponentId==component.Id&&m.Kind==values.Key);
                result.Add(new MovingMember {Id=old?.Id??Guid.NewGuid().ToString("N"),ComponentId=component.Id,Kind=values.Key,Name=component.Name+" / "+values.Key,
                    BodyIds=values.Select(v=>v.Body.Item1).ToList(),Selections=values.Select(v=>v.Body.Item2).ToList(),Part=old?.Part,ComponentReference=old?.ComponentReference,GeometryDirectory=old?.GeometryDirectory,PlacementFixed=old?.PlacementFixed??true});
            }
            var previous=project.JointWorkspace.Members.Where(m=>m.ComponentId==component.Id).ToArray();
            if(previous.Length!=result.Count||previous.Any(m=>!result.Any(r=>r.Id==m.Id&&r.BodyIds.OrderBy(v=>v).SequenceEqual(m.BodyIds.OrderBy(v=>v)))))
                project.JointWorkspace.Invalidate(new[]{component.Id},"Moving member ownership changed; split/update and rescan native mates.");
            project.JointWorkspace.Members.RemoveAll(m=>m.ComponentId==component.Id);project.JointWorkspace.Members.AddRange(result);Saved?.Invoke();
        }
    }
}
