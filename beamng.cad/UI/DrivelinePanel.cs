using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed partial class DrivelinePanel : UserControl
    {
        private VehicleProject project;
        private Driveline draft;
        private readonly TabControl tabs=new TabControl {Dock=DockStyle.Fill};
        private readonly Dictionary<string,ListBox> lists=new Dictionary<string,ListBox>();
        private readonly Label state=new Label {AutoSize=true,Padding=new Padding(5)};
        private readonly TextBox detail=new TextBox {Multiline=true,ReadOnly=true,Dock=DockStyle.Bottom,Height=95,ScrollBars=ScrollBars.Vertical};
        private readonly Topology topology=new Topology();
        private bool dirty;
        internal event Action<Driveline> ApplyRequested;
        internal event Action PresetRequested,CheckRequested;
        internal event Action<string,bool> CaptureRequested;
        internal event Action<string> BindRequested,HighlightRequested;
        internal Driveline Draft=>draft;
        internal bool HasChanges=>dirty;
        internal DriveEndpoint SelectedEndpoint=>Current?.SelectedItem as DriveEndpoint;
        private ListBox Current=>tabs.SelectedTab!=null&&lists.TryGetValue(tabs.SelectedTab.Name,out var value)?value:null;

        internal DrivelinePanel()
        {
            Name="DrivelineWorkspace";Dock=DockStyle.Fill;
            var toolbar=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true,WrapContents=true};
            Add(toolbar,"New empty graph",()=>{draft=new Driveline {Version=2};Changed();});
            Add(toolbar,"Convert current layout",()=>PresetRequested?.Invoke());
            Add(toolbar,"Import reviewed graph",()=>{using(var dialog=new OpenFileDialog {Filter="Graph or reviewed definition (*.json)|*.json"})if(dialog.ShowDialog(this)==DialogResult.OK){var json=new System.Web.Script.Serialization.JavaScriptSerializer();var root=json.DeserializeObject(System.IO.File.ReadAllText(dialog.FileName)) as Dictionary<string,object>;if(root==null)throw new InvalidOperationException("Expected a graph or reviewed definition object.");Adopt(Driveline.FromJson(json.Serialize(root.ContainsKey("driveline")?root["driveline"]:root)));}});
            CreateRoutesTab();
            foreach(var title in new[]{"Devices","Endpoints","Shafts","Connections"})
            {
                var page=new TabPage(title=="Shafts"?"Detailed shafts":title) {Name=title};
                var list=new ListBox {Name="Driveline"+title,Dock=DockStyle.Fill,IntegralHeight=false,HorizontalScrollbar=true};
                lists[title]=list;page.Controls.Add(list);tabs.TabPages.Add(page);
                var actions=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
                Add(actions,"Add",()=>Edit(true));Add(actions,"Edit",()=>Edit(false));Add(actions,"Remove",Remove);
                if(title=="Devices"){Add(actions,"Device ports",EditPorts);Add(actions,"Device settings",EditSettings);}
                if(title=="Endpoints"){
                    Add(actions,"Capture centre",()=>Capture(false));Add(actions,"Capture axis point",()=>Capture(true));
                    Add(actions,"Bind reviewed joint",()=>{var endpoint=SelectedEndpoint;if(endpoint!=null&&ResolveChanges())BindRequested?.Invoke(endpoint.Id);});
                    Add(actions,"Show CAD",()=>{var endpoint=SelectedEndpoint;if(endpoint!=null&&ResolveChanges())HighlightRequested?.Invoke(endpoint.Id);});
                }
                page.Controls.Add(actions);
                list.SelectedIndexChanged+=(s,e)=>Describe(list.SelectedItem);list.DoubleClick+=(s,e)=>Edit(false);
            }
            var diagram=new TabPage("Topology");diagram.Controls.Add(topology);tabs.TabPages.Add(diagram);
            var footer=new FlowLayoutPanel {Dock=DockStyle.Bottom,AutoSize=true,WrapContents=true};
            footer.Controls.Add(state);Add(footer,"Apply driveline changes",Apply);Add(footer,"Discard",()=>Configure(project,true));
            Add(footer,"Check graph",()=>{if(ResolveChanges())CheckRequested?.Invoke();});
            detail.Visible=false;
            var detailsToggle=new CheckBox {Text="Details",AutoSize=true,Appearance=Appearance.Button};
            detailsToggle.CheckedChanged+=(s,e)=>detail.Visible=detailsToggle.Checked;
            footer.Controls.Add(detailsToggle);
            tabs.SelectedIndexChanged+=(s,e)=>Describe(Current?.SelectedItem);
            Controls.Add(tabs);Controls.Add(detail);Controls.Add(footer);Controls.Add(toolbar);
            Configure(null,true);
        }
        private static void Add(Control root,string text,Action action){var b=new Button {Text=text,AutoSize=true};b.Click+=(s,e)=>{try{action();}catch(Exception error){MessageBox.Show(root,error.Message,"Driveline",MessageBoxButtons.OK,MessageBoxIcon.Information);}};root.Controls.Add(b);}
        internal void Configure(VehicleProject value,bool force=false)
        {
            if(dirty&&!force&&ReferenceEquals(project,value))return;
            project=value;draft=value?.Driveline?.Copy();dirty=false;RefreshLists();
        }
        internal void Adopt(Driveline value){draft=value;draft.Normalize();Changed();}
        private void Changed(){dirty=true;RefreshLists();}
        private void RefreshLists()
        {
            var values=new Dictionary<string,IEnumerable>{{"Routes",draft==null?null:Routes(draft)},{"Devices",draft?.Devices},{"Endpoints",draft?.Endpoints},{"Shafts",draft?.Shafts.Where(v=>v.Representation!="ideal")},{"Connections",draft?.Connections}};
            foreach(var pair in lists)
            {
                var selected=pair.Value.SelectedItem;pair.Value.BeginUpdate();pair.Value.Items.Clear();
                if(values[pair.Key]!=null)foreach(var item in values[pair.Key])pair.Value.Items.Add(item);
                if(selected!=null&&pair.Value.Items.Contains(selected))pair.Value.SelectedItem=selected;
                else if(pair.Value.Items.Count>0)pair.Value.SelectedIndex=0;
                pair.Value.EndUpdate();
            }
            state.Text=draft==null?"Current layout uses the earlier definition":dirty?"Driveline changes pending":"Driveline saved; check graph before generation";
            Describe(Current?.SelectedItem);
            topology.Graph=draft;topology.Invalidate();
        }
        internal bool ResolveChanges()
        {
            if(!dirty)return true;
            var answer=MessageBox.Show(this,"Apply driveline changes before continuing? No discards this graph's pending edits.","Pending driveline changes",MessageBoxButtons.YesNoCancel,MessageBoxIcon.Question);
            if(answer==DialogResult.Cancel)return false;
            if(answer==DialogResult.No){Configure(project,true);return true;}
            Apply();return !dirty;
        }
        private void Apply(){if(draft==null||!dirty)return;draft.Normalize();ApplyRequested?.Invoke(draft.Copy());dirty=false;Configure(project,true);}
        private void Capture(bool axis){var e=SelectedEndpoint;if(e!=null&&ResolveChanges())CaptureRequested?.Invoke(e.Id,axis);}
        private void Describe(object item)
        {
            string Owner(string id)=>project?.Components.FirstOrDefault(c=>c.Id==id)?.Name??"Choose CAD owner";
            string End(string id)=>draft?.Endpoints.FirstOrDefault(e=>e.Id==id)?.Name??"Choose endpoint";
            if(item is Route row)detail.Text=row.ToString();
            else if(item is DriveEndpoint e)detail.Text=e.Name+" | "+Owner(e.Component)+"\r\n"+(!string.IsNullOrEmpty(e.Joint)?"Reviewed joint bound":!string.IsNullOrEmpty(e.Anchor)?"Centre captured; "+(!string.IsNullOrEmpty(e.AxisAnchor)?"axis point captured":EndpointPrompt(e)):e.Position!=null?"Reviewed coordinates imported; capture CAD references for live repair checks":EndpointPrompt(e))+"\r\n"+e.Id;
            else if(item is DriveShaft shaft)detail.Text=shaft.Name+" | "+Owner(shaft.Component)+"\r\n"+End(shaft.A)+" → "+End(shaft.B)+"\r\nEach section owns its CAD mass and appearance."+(shaft.LegacyPlunge>0?" Original half plunge: "+shaft.LegacyPlunge.ToString("G6",CultureInfo.InvariantCulture)+" m; retain this using an explicit sliding interface.":"");
            else if(item is DriveConnection link)detail.Text=link.Name+" | "+link.Kind+"\r\n"+End(link.A)+" → "+End(link.B)+"\r\nSlider half travel: "+link.Travel.ToString("G6",CultureInfo.InvariantCulture)+" m. Internal/direct links route torque only.";
            else if(item is DriveDevice d)detail.Text=d.Name+" | "+d.Type+" | "+Owner(d.Component)+"\r\n"+string.Join("; ",d.Ports.Select(p=>p.Name+": "+End(p.Endpoint)))+"\r\nUse Device settings to specify gearing and operating values.";
            else detail.Clear();
        }
        private string EndpointPrompt(DriveEndpoint endpoint)
        {
            draft.DatumRequirements().TryGetValue(endpoint.Id,out var required);
            if(required==2)return "Capture the centre and a point on the positive axis.";
            if(required==1)return "Capture the attachment centre.";
            return draft.Devices.Any(d=>d.Type=="wheel" && d.Ports.Any(p=>p.Endpoint==endpoint.Id))
                ?"Uses the suspension hub datum.":"Torque routing uses this port directly.";
        }
        private sealed class Choice {public string Id {get;set;}public string Name {get;set;}public override string ToString()=>Name;}
        private sealed class Fields : Form
        {
            private readonly TableLayoutPanel table=new TableLayoutPanel {Dock=DockStyle.Fill,AutoScroll=true,ColumnCount=2,Padding=new Padding(10)};
            internal Fields(string title){Text=title;Width=560;Height=390;StartPosition=FormStartPosition.CenterParent;table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,130));table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));Controls.Add(table);var save=new Button {Text="Save",Dock=DockStyle.Bottom,DialogResult=DialogResult.OK};Controls.Add(save);AcceptButton=save;}
            private void Add(string label,Control control){var row=table.RowCount++;table.RowStyles.Add(new RowStyle(SizeType.AutoSize));table.Controls.Add(new Label {Text=label,AutoSize=true,Padding=new Padding(0,6,0,0)},0,row);control.Dock=DockStyle.Top;table.Controls.Add(control,1,row);}
            internal void ShowField(Control control,bool visible){ control.Visible=visible;table.GetControlFromPosition(0,table.GetRow(control)).Visible=visible; }
            internal TextBox TextField(string label,string value){var box=new TextBox {Text=value};Add(label,box);return box;}
            internal ComboBox Pick(string label,IEnumerable<Choice> choices,string selected){var box=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList};box.Items.AddRange(choices.Cast<object>().ToArray());box.SelectedItem=box.Items.Cast<Choice>().FirstOrDefault(c=>c.Id==selected);Add(label,box);return box;}
        }
        private static string Id(ComboBox box)=>(box.SelectedItem as Choice)?.Id;
        private IEnumerable<Choice> Owners()=>new[]{new Choice {Id=null,Name="Choose physical CAD owner"}}.Concat((project?.Components??new List<ComponentDefinition>()).Select(c=>new Choice {Id=c.Id,Name=c.Name}));
        private IEnumerable<Choice> Ends()=>new[]{new Choice {Id=null,Name="Choose endpoint"}}.Concat(draft.Endpoints.Select(e=>new Choice {Id=e.Id,Name=e.Name}));
        private static IEnumerable<Choice> Options(params string[] values)=>values.Select(s=>new Choice {Id=s,Name=s});
        private void Edit(bool add)
        {
            if(draft==null||Current==null)throw new InvalidOperationException("Create an empty graph or convert the current layout first.");
            var kind=tabs.SelectedTab.Name;var item=add?null:Current.SelectedItem;
            if(!add&&item==null)return;
            using(var form=new Fields((add?"Add ":"Edit ")+kind))
            {
                var name=form.TextField("Name",item?.GetType().GetProperty("Name")?.GetValue(item)?.ToString()??"New "+kind.TrimEnd('s'));
                if(kind=="Devices")
                {
                    var d=item as DriveDevice??new DriveDevice();var type=form.Pick("Behavior",Options(Driveline.DeviceTypes),d.Type);var owner=form.Pick("Housing / wheel",Owners(),d.Component);var wheel=form.Pick("Wheel hub",Options("FL","FR","RL","RR"),d.Wheel);
                    if(form.ShowDialog(this)!=DialogResult.OK)return;
                    var selected=Id(type);if(selected==null||Id(owner)==null)throw new InvalidOperationException("Choose behavior and a physical owner.");
                    if(!add&&d.Ports.Count>0&&(d.Type!=selected||d.Component!=Id(owner)))throw new InvalidOperationException("Remove this device's ports before changing its behavior or owner. Existing connections are preserved for explicit repair.");
                    d.Name=name.Text.Trim();d.Type=selected;d.Component=Id(owner);d.Wheel=d.Type=="wheel"?Id(wheel):null;
                    if(add)
                    {
                        draft.Devices.Add(d);
                        foreach(var dir in new[]{"input","output"})for(var i=1;i<=(dir=="input"?(d.Type=="engine"?0:1):(d.Type=="wheel"?0:d.Type=="splitter"||d.Type=="differential"?2:1));i++)
                        {var e=new DriveEndpoint {Name=d.Name+" "+dir+" "+i,Component=d.Component};draft.Endpoints.Add(e);d.Ports.Add(new DrivePort {Name=dir+" "+i,Direction=dir,Index=i,Endpoint=e.Id});}
                    }
                }
                else if(kind=="Endpoints"||kind=="Shafts")
                {
                    var endpoint=item as DriveEndpoint;var shaft=item as DriveShaft;
                    var owner=form.Pick("CAD group",Owners(),endpoint?.Component??shaft?.Component);
                    var member=form.Pick("Moving member",new[]{new Choice {Id=null,Name="Whole group"}}.Concat(project.JointWorkspace.Members.Select(m=>new Choice {Id=m.Id,Name=m.Name})),endpoint?.Member??shaft?.Member);
                    ComboBox a=null,b=null;if(kind=="Shafts"&&!add){a=form.Pick("End A",Ends(),shaft.A);b=form.Pick("End B",Ends(),shaft.B);}
                    if(form.ShowDialog(this)!=DialogResult.OK)return;
                    if(Id(owner)==null)throw new InvalidOperationException("Choose the physical CAD owner.");
                    if(Id(member)!=null&&!project.JointWorkspace.Members.Any(m=>m.Id==Id(member)&&m.ComponentId==Id(owner)))throw new InvalidOperationException("Moving member must belong to the selected group.");
                    if(kind=="Endpoints")
                    {
                        endpoint=endpoint??new DriveEndpoint();if(endpoint.Component!=Id(owner)||endpoint.Member!=Id(member)){endpoint.Anchor=endpoint.AxisAnchor=endpoint.Joint=null;endpoint.Position=endpoint.Axis=null;}
                        endpoint.Name=name.Text.Trim();endpoint.Component=Id(owner);endpoint.Member=Id(member);if(add)draft.Endpoints.Add(endpoint);
                    }
                    else
                    {
                        shaft=shaft??new DriveShaft {Representation="detailed"};shaft.Name=name.Text.Trim();shaft.Component=Id(owner);shaft.Member=Id(member);
                        if(add){var ea=new DriveEndpoint {Name=shaft.Name+" end A",Component=shaft.Component,Member=shaft.Member};var eb=new DriveEndpoint {Name=shaft.Name+" end B",Component=shaft.Component,Member=shaft.Member};draft.Endpoints.Add(ea);draft.Endpoints.Add(eb);shaft.A=ea.Id;shaft.B=eb.Id;draft.Shafts.Add(shaft);}
                        else{shaft.A=Id(a);shaft.B=Id(b);}
                    }
                }
                else
                {
                    var link=item as DriveConnection??new DriveConnection();var a=form.Pick("Endpoint A",Ends(),link.A);var b=form.Pick("Endpoint B",Ends(),link.B);var type=form.Pick("Connection",Options("spherical","slider","bearing","internal","direct"),link.Kind);var travel=form.TextField("Half travel (m)",link.Travel.ToString("R",CultureInfo.InvariantCulture));
                    form.ShowField(travel,Id(type)=="slider");type.SelectedIndexChanged+=(s,e)=>form.ShowField(travel,Id(type)=="slider");
                    if(form.ShowDialog(this)!=DialogResult.OK)return;
                    if(!double.TryParse(Id(type)=="slider"?travel.Text:"0",NumberStyles.Float,CultureInfo.InvariantCulture,out var length)||double.IsNaN(length)||double.IsInfinity(length))throw new InvalidOperationException("Enter finite half travel in metres.");
                    link.Name=name.Text.Trim();link.A=Id(a);link.B=Id(b);link.Kind=Id(type);link.Travel=length;if(add)draft.Connections.Add(link);
                }
                Changed();
            }
        }
        private void Remove()
        {
            var item=Current?.SelectedItem;if(item==null)return;
            if(item is DriveDevice d)draft.Devices.Remove(d);
            if(item is DriveEndpoint e)draft.Endpoints.Remove(e);
            if(item is DriveShaft s)draft.Shafts.Remove(s);
            if(item is DriveConnection c)draft.Connections.Remove(c);
            Changed(); // Keep references to removed records visible as repair errors.
        }
        private void EditPorts()
        {
            if(!(Current?.SelectedItem is DriveDevice device))throw new InvalidOperationException("Select a device first.");
            using(var form=new Form {Text=device.Name+" ports",Width=750,Height=380,StartPosition=FormStartPosition.CenterParent})
            {
                var ports=device.Ports.Select(p=>new DrivePort {Id=p.Id,Name=p.Name,Direction=p.Direction,Index=p.Index,Endpoint=p.Endpoint}).ToList();
                var choices=Ends().Where(e=>e.Id!=null).Concat(ports.Where(p=>!string.IsNullOrEmpty(p.Endpoint)&&!draft.Endpoints.Any(e=>e.Id==p.Endpoint)).Select(p=>p.Endpoint).Distinct().Select(id=>new Choice {Id=id,Name="Missing endpoint: "+id})).ToList();
                var grid=new DataGridView {Dock=DockStyle.Fill,AutoGenerateColumns=false,AllowUserToAddRows=true,DataSource=new System.ComponentModel.BindingList<DrivePort>(ports)};
                grid.DataError+=(s,e)=>{e.ThrowException=false;};
                grid.Columns.Add(new DataGridViewTextBoxColumn {HeaderText="Name",DataPropertyName="Name"});
                grid.Columns.Add(new DataGridViewComboBoxColumn {HeaderText="Direction",DataPropertyName="Direction",DataSource=new[]{"input","output"}});
                grid.Columns.Add(new DataGridViewTextBoxColumn {HeaderText="Port index",DataPropertyName="Index"});
                grid.Columns.Add(new DataGridViewComboBoxColumn {HeaderText="CAD endpoint",DataPropertyName="Endpoint",DataSource=choices,DisplayMember="Name",ValueMember="Id",Width=250});
                var save=new Button {Text="Save ports",Dock=DockStyle.Bottom,DialogResult=DialogResult.OK};form.Controls.Add(grid);form.Controls.Add(save);
                if(form.ShowDialog(this)!=DialogResult.OK)return;if(!grid.EndEdit())throw new InvalidOperationException("Fix invalid port values before saving.");device.Ports=ports;Changed();
            }
        }
        private void EditSettings()
        {
            if(!(Current?.SelectedItem is DriveDevice device))throw new InvalidOperationException("Select a device first.");
            using(var form=new Fields(device.Name+" settings"))
            {
                var keys=device.Type=="cvt"?new[]{"minGearRatio","maxGearRatio","dynamicFriction","parkLockTorque"}:device.Type=="clutch"?new[]{"engageRPMStart","engageRPMEnd","lockTorque"}:device.Type=="engine"?new[]{"inertia","friction","dynamicFriction"}:device.Type=="splitter"?new[]{"lockTorque","primaryOutputID"}:device.Type=="wheel"?new string[0]:device.Type=="differential"?new[]{"gearRatio"}:new[]{"gearRatio","direction"};
                var inputs=keys.ToDictionary(k=>k,k=>form.TextField(k,device.Parameters.TryGetValue(k,out var v)?v.ToString("R",CultureInfo.InvariantCulture):""));
                if(form.ShowDialog(this)!=DialogResult.OK)return;
                var next=new Dictionary<string,double>(device.Parameters);
                foreach(var pair in inputs){if(string.IsNullOrWhiteSpace(pair.Value.Text)){next.Remove(pair.Key);continue;}if(!double.TryParse(pair.Value.Text,NumberStyles.Float,CultureInfo.InvariantCulture,out var value)||double.IsNaN(value)||double.IsInfinity(value))throw new InvalidOperationException(pair.Key+": enter a finite value.");next[pair.Key]=value;}
                device.Parameters=next;Changed();
            }
        }
        private sealed class Topology : Panel
        {
            internal Driveline Graph;
            internal Topology(){Dock=DockStyle.Fill;AutoScroll=true;DoubleBuffered=true;AccessibleName="Driveline endpoint topology schematic";}
            protected override void OnPaint(PaintEventArgs e)
            {
                base.OnPaint(e);if(Graph==null)return;
                var endpoints=Graph.Endpoints.OrderBy(p=>p.Id).ToList();AutoScrollMinSize=new Size(750,Math.Max(150,endpoints.Count*34+40));
                e.Graphics.TranslateTransform(AutoScrollPosition.X,AutoScrollPosition.Y);
                e.Graphics.DrawString("Topology schematic — positions are not CAD coordinates",Font,SystemBrushes.ControlText,8,8);
                var map=endpoints.Select((p,i)=>new {p.Id,Point=new PointF(250,45+i*34)}).ToDictionary(p=>p.Id,p=>p.Point);
                foreach(var link in Graph.Connections){if(map.TryGetValue(link.A??"",out var a)&&map.TryGetValue(link.B??"",out var b)){e.Graphics.DrawLine(Pens.SteelBlue,a,new PointF(420,a.Y));e.Graphics.DrawLine(Pens.SteelBlue,420,a.Y,420,b.Y);e.Graphics.DrawLine(Pens.SteelBlue,new PointF(420,b.Y),b);}}
                foreach(var shaft in Graph.Shafts){if(map.TryGetValue(shaft.A??"",out var a)&&map.TryGetValue(shaft.B??"",out var b)){e.Graphics.DrawLine(Pens.DarkOrange,a,new PointF(380,a.Y));e.Graphics.DrawLine(Pens.DarkOrange,380,a.Y,380,b.Y);e.Graphics.DrawLine(Pens.DarkOrange,new PointF(380,b.Y),b);}}
                foreach(var p in endpoints){var point=map[p.Id];e.Graphics.FillEllipse(SystemBrushes.ControlText,point.X-3,point.Y-3,6,6);e.Graphics.DrawString(p.Name,Font,SystemBrushes.ControlText,8,point.Y-8);var d=Graph.Devices.FirstOrDefault(v=>v.Ports.Any(port=>port.Endpoint==p.Id));if(d!=null)e.Graphics.DrawString(d.Name+" / "+d.Type,Font,SystemBrushes.ControlText,450,point.Y-8);}
            }
        }
    }
}
