using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed class JointWorkspacePanel : UserControl
    {
        private sealed class Entry
        {
            public string Id,Label,Role,Component;
            public JointRequest Request;
            public JointDefinition Joint;
            public override string ToString()=>Label;
        }
        private readonly TextBox search=new TextBox {Name="JointSearch",Dock=DockStyle.Top};
        private readonly ListBox list=new ListBox {Name="JointRequests",Dock=DockStyle.Fill,HorizontalScrollbar=true};
        private readonly Label summary=new Label {Name="JointReadiness",Dock=DockStyle.Top,Height=45};
        private readonly Label detail=new Label {Name="JointDetail",Dock=DockStyle.Top,Height=90,Padding=new Padding(6)};
        private readonly ComboBox mode=new ComboBox {Name="JointDefinitionMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=240};
        private readonly TabControl inspector=new TabControl {Name="JointInspector",Dock=DockStyle.Fill};
        private readonly FlowLayoutPanel actions=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
        private readonly List<Entry> entries=new List<Entry>();
        private readonly ReferenceSkeleton reference;
        private VehicleProject project;
        private bool refreshing;
        private Button captureAction,bindAction,approveAction,positionAction,highlightAction;
        private readonly ToolTip requirements=new ToolTip();
        public event Action ScanRequested,NativeMateRequested,ValidateRequested,MembersRequested,ParametersRequested,AutoConnectRequested;
        public event Action<string> ModeChanged,ApproveRequested,PositioningRequested,HighlightRequested,OwnerSelected;
        public event Action<JointRequest> CaptureRequested,BindJointRequested;
        public JointRequest SelectedRequest=>(list.SelectedItem as Entry)?.Request;
        public JointDefinition SelectedJoint=>(list.SelectedItem as Entry)?.Joint;
        public JointWorkspacePanel(ReferenceSkeleton reference,TabPage points,TabPage fasteners)
        {
            this.reference=reference;reference.CompactGuide();Name="JointWorkspace";Dock=DockStyle.Fill;
            var split=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=2};
            split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,32));split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,68));
            var left=new Panel {Dock=DockStyle.Fill,Padding=new Padding(6)};
            left.Controls.Add(list);left.Controls.Add(search);left.Controls.Add(summary);
            var right=new Panel {Dock=DockStyle.Fill};right.Controls.Add(inspector);right.Controls.Add(actions);right.Controls.Add(detail);
            split.Controls.Add(left,0,0);split.Controls.Add(right,1,0);Controls.Add(split);
            split.Resize+=(s,e)=>ResponsiveLayout.Split(split,left,right,split.ClientSize.Width<760,160);
            var guide=new TabPage("Connection guide");guide.Controls.Add(reference);inspector.TabPages.Add(guide);
            points.Text="CAD reference points";fasteners.Text="Panel / accessory fasteners";inspector.TabPages.Add(points);inspector.TabPages.Add(fasteners);
            mode.Items.AddRange(new object[]{"Authored CAD joints","Reviewed template definition"});
            var toolbar=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};toolbar.Controls.Add(mode);
            Add(toolbar,"Scan native mates",()=>ScanRequested?.Invoke());Add(toolbar,"Native Mate command",()=>NativeMateRequested?.Invoke());
            Add(toolbar,"Moving members",()=>MembersRequested?.Invoke());Add(toolbar,"Check definition",()=>ValidateRequested?.Invoke());Controls.Add(toolbar);
            Add(toolbar,"Physical parameters",()=>ParametersRequested?.Invoke());
            Add(toolbar,"Auto-connect…",()=>AutoConnectRequested?.Invoke());
            captureAction=ActionButton("Capture selected CAD point",()=>{if(SelectedRequest!=null)CaptureRequested?.Invoke(SelectedRequest);});
            bindAction=ActionButton("Bind reviewed joint",()=>{if(SelectedRequest!=null)BindJointRequested?.Invoke(SelectedRequest);});
            approveAction=ActionButton("Approve joint",()=>{if(SelectedJoint!=null)ApproveRequested?.Invoke(SelectedJoint.Id);});
            positionAction=ActionButton("Positioning only",()=>{if(SelectedJoint!=null)PositioningRequested?.Invoke(SelectedJoint.Id);});
            highlightAction=ActionButton("Highlight CAD",()=>{var e=list.SelectedItem as Entry;if(e!=null)HighlightRequested?.Invoke(e.Id);});
            search.TextChanged+=(s,e)=>Filter();list.SelectedIndexChanged+=(s,e)=>Selected();
            mode.SelectedIndexChanged+=(s,e)=>{if(!refreshing)ModeChanged?.Invoke(mode.SelectedIndex==0?"authored":"legacy");};
        }
        private static void Add(Control parent,string title,Action action)
        {var button=new Button {Text=title,AutoSize=true};button.Click+=(s,e)=>action();parent.Controls.Add(button);}
        private Button ActionButton(string title,Action action)
        {var button=new Button {Text=title,AutoSize=true,AccessibleName=title};button.Click+=(s,e)=>action();actions.Controls.Add(button);return button;}
        public void Configure(MvpCatalog catalog,VehicleProject value)
        {
            project=value;refreshing=true;mode.SelectedIndex=value.JointWorkspace.Mode=="authored"?0:1;refreshing=false;
            var previous=(list.SelectedItem as Entry)?.Id;entries.Clear();var ready=0;var requests=catalog.JointRequests(value);
            foreach(var r in requests)
            {
                var binding=value.JointWorkspace.Bindings.SingleOrDefault(b=>b.Request==r.Id);
                var state=binding==null?"needs CAD":binding.Status;
                if(binding?.AnchorId!=null)state=value.Anchors.FirstOrDefault(a=>a.Id==binding.AnchorId)?.Status??"needs repair";
                if(binding?.JointId!=null)state=value.JointWorkspace.Joints.SingleOrDefault(j=>j.Id==binding.JointId)?.Status??"needs repair";
                if(state=="approved"||state=="resolved")ready++;
                entries.Add(new Entry {Id=r.Id,Role=r.Role,Request=r,Label=r.Label+" | "+state,Component=binding?.ComponentId});
            }
            foreach(var joint in value.JointWorkspace.Joints)entries.Add(new Entry {Id=joint.Id,Joint=joint,Label=joint.Label,Component=joint.Child});
            foreach(var c in value.Components.Where(c=>c.Template=="panel"||c.MvpRole=="accessory"||c.Template=="bulk"))
            {
                var anchors=new HashSet<string>(value.Anchors.Where(a=>a.ComponentId==c.Id).Select(a=>a.Id));
                var mounts=value.Connections.Where(m=>anchors.Contains(m.AnchorB)).ToArray();
                entries.Add(new Entry {Id="panel:"+c.Id,Role=c.MvpRole,Component=c.Id,
                    Label=c.Name+" | "+mounts.Length+" fasteners"+(mounts.Any(m=>!string.IsNullOrEmpty(m.ReleaseSet))?" | linked release":" | independent")});
            }
            summary.Text=ready+" / "+requests.Count+" hardpoints bound\r\n"+value.JointWorkspace.Joints.Count(j=>j.Status=="review"||j.Status=="needs_repair")+" joints need review";
            Filter(previous);
        }
        private void Filter(string selected=null)
        {
            selected=selected??(list.SelectedItem as Entry)?.Id;var terms=search.Text.Trim().Split(new[]{' '},StringSplitOptions.RemoveEmptyEntries);
            list.BeginUpdate();list.Items.Clear();
            foreach(var e in entries.Where(e=>terms.All(t=>(e.Label+" "+e.Role+" "+e.Id).IndexOf(t,StringComparison.OrdinalIgnoreCase)>=0)))list.Items.Add(e);
            list.SelectedItem=list.Items.Cast<Entry>().FirstOrDefault(e=>e.Id==selected)??list.Items.Cast<Entry>().FirstOrDefault();list.EndUpdate();
        }
        private void Selected()
        {
            var entry=list.SelectedItem as Entry;
            if(entry==null){detail.Text="No matching joint or hardpoint request.";foreach(Button b in actions.Controls)b.Enabled=false;return;}
            if(entry.Role!=null)reference.SelectMarker(entry.Role,entry.Request?.Marker);
            if(entry.Component!=null)OwnerSelected?.Invoke(entry.Component);
            if(entry.Id.StartsWith("panel:"))
            {
                inspector.SelectedIndex=2;
                detail.Text=entry.Label+"\r\nCapture a parent and panel mounting point at each fastener. Mounts fail separately unless you explicitly assign the same release-set name. The panel mesh stays with its own nodes.";
            }
            else if(entry.Joint!=null)
            {
                var j=entry.Joint;detail.Text=j.Label+"\r\n"+(j.Issue??("Centre (BeamNG m): "+string.Join(", ",(j.Center??Array.Empty<double>()).Select(p=>p.ToString("G5")))))+"\r\nReview native mates before approving. Motion does not establish attachment strength.";
            }
            else
            {
                inspector.SelectedIndex=0;detail.Text=entry.Label+"\r\nCapture its CAD point, then bind the reviewed joint to retain distinct hinge pivots. A joint centre can also be used directly. Example coordinates in the guide are never assigned.";
            }
            captureAction.Enabled=entry.Request!=null;
            var owners=project.Components.Where(c=>entry.Request!=null&&(entry.Request.Id.StartsWith(c.Id+".",StringComparison.Ordinal)||c.MvpRole==entry.Request.Role)).ToArray();
            bindAction.Enabled=entry.Request!=null&&project.JointWorkspace.Joints.Any(j=>j.Status=="approved"&&j.Center?.Length==3&&owners.Any(c=>j.Parent==c.Id||j.Child==c.Id));
            approveAction.Enabled=entry.Joint!=null&&string.IsNullOrEmpty(entry.Joint.Issue);
            positionAction.Enabled=entry.Joint!=null;
            highlightAction.Enabled=true;
            requirements.SetToolTip(bindAction,bindAction.Enabled?"Bind an approved joint to this requested hardpoint.":"Select a hardpoint request and scan/approve a joint belonging to its component first.");
            if(entry.Request!=null&&!bindAction.Enabled)detail.Text+="\r\nTo bind: scan and approve a joint on this request's component first.";
        }
        protected override void Dispose(bool disposing){if(disposing)requirements.Dispose();base.Dispose(disposing);}
    }
}
