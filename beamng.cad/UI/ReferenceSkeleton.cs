using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed class SkeletonMarker
    {
        public string id {get;set;} public string source {get;set;} public string note {get;set;}
        public double[][] positions {get;set;}
    }
    internal sealed class SkeletonPart
    {
        public double[][] vertices {get;set;}
        public int[][] edges {get;set;}
        public SkeletonMarker[] markers {get;set;}
    }
    internal sealed class SkeletonData
    {
        public string label {get;set;} public string units {get;set;}
        public Dictionary<string,string> templates {get;set;}
        public Dictionary<string,SkeletonPart> roles {get;set;}
    }

    // An illustration of the tested templates, deliberately without a project
    // writer or CAD connection. Browsing cannot apply example coordinates.
    internal sealed class ReferenceSkeleton : UserControl
    {
        private readonly TreeView requests=new TreeView {Name="ReferenceRequests",Dock=DockStyle.Fill,HideSelection=false,ShowNodeToolTips=true};
        private readonly Label detail=new Label {Name="ReferenceDetail",Dock=DockStyle.Fill,Padding=new Padding(8),AutoEllipsis=true};
        private readonly SkeletonView view=new SkeletonView {Name="ReferenceViewport",Dock=DockStyle.Fill};
        private readonly Label heading=new Label {Name="ReferenceHeading",Dock=DockStyle.Top,Height=58,Padding=new Padding(8)};
        private readonly Dictionary<string,SkeletonData> examples=new Dictionary<string,SkeletonData>();
        private readonly Dictionary<string,TreeNode> roleNodes=new Dictionary<string,TreeNode>();
        private SkeletonData data;
        private TableLayoutPanel layout;
        private sealed class Request {public MvpRole Role;public SkeletonMarker Marker;}

        public ReferenceSkeleton()
        {
            Name="ReferenceSkeleton";Dock=DockStyle.Fill;
            layout=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=2,RowCount=1};
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,280));layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            var right=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=1,RowCount=3};
            right.RowStyles.Add(new RowStyle(SizeType.AutoSize));right.RowStyles.Add(new RowStyle(SizeType.Percent,100));right.RowStyles.Add(new RowStyle(SizeType.Absolute,125));
            var toolbar=new FlowLayoutPanel {Dock=DockStyle.Fill,AutoSize=true,Padding=new Padding(5)};
            var angle=new ComboBox {Name="ReferenceViewAngle",DropDownStyle=ComboBoxStyle.DropDownList,Width=190};
            angle.Items.AddRange(new object[]{"Front three-quarter","Top (forward up)","Front (looking rearward)","Right side","Rear (looking forward)"});angle.SelectedIndex=0;
            angle.SelectedIndexChanged+=(s,e)=>view.SetAngle(angle.SelectedIndex);toolbar.Controls.Add(angle);
            var focus=new CheckBox {Name="ReferenceFocus",Text="Focus part",AutoSize=true};focus.CheckedChanged+=(s,e)=>view.FocusPart(focus.Checked);toolbar.Controls.Add(focus);
            var reset=new Button {Text="Reset view",AutoSize=true};reset.Click+=(s,e)=>{focus.Checked=false;angle.SelectedIndex=0;view.SetAngle(0);};toolbar.Controls.Add(reset);
            toolbar.Controls.Add(new Label {AutoSize=true,Text="Right-drag: orbit  |  Wheel: zoom",Margin=new Padding(5,7,0,0)});
            right.Controls.Add(toolbar,0,0);right.Controls.Add(view,0,1);right.Controls.Add(detail,0,2);
            layout.Controls.Add(requests,0,0);layout.Controls.Add(right,1,0);Controls.Add(layout);Controls.Add(heading);
            requests.AfterSelect+=(s,e)=>ShowRequest(e.Node.Tag as Request);
            view.MarkerPicked+=marker=>{var root=requests.SelectedNode;while(root?.Parent!=null)root=root.Parent;
                var node=root?.Nodes.Cast<TreeNode>().FirstOrDefault(n=>(n.Tag as Request)?.Marker==marker);if(node!=null)requests.SelectedNode=node;};
        }

        public void Configure(MvpCatalog catalog,VehicleProject project)
        {
            var previous=(requests.SelectedNode?.Tag as Request)?.Role.Id;
            var selection=catalog.TemplateSets.ToDictionary(s=>s.Id,s=>catalog.Selected(project,s).Id);
            data=null;
            try
            {
                if(examples.Count==0)
                    foreach(var path in Directory.GetFiles(Path.Combine(Path.GetDirectoryName(typeof(ReferenceSkeleton).Assembly.Location),"FramePipeline","reference"),"*.json").OrderBy(p=>p))
                    {
                        examples[Path.GetFileNameWithoutExtension(path)]=new JavaScriptSerializer {MaxJsonLength=8*1024*1024}.Deserialize<SkeletonData>(File.ReadAllText(path));
                    }
                data=examples.Values.FirstOrDefault(d=>selection.All(p=>d.templates.TryGetValue(p.Key,out var value)&&value==p.Value));
                heading.Text=data==null?"No tested reference for this complete configuration. Choose a supported layout on Vehicle setup / MVP. Requested roles remain listed below.":
                    "SYNTHETIC REFERENCE — "+data.label+"\r\nBlue: selected CAD mesh. Orange: requested point or axis. Example coordinates are never applied to your vehicle.";
            }
            catch(Exception e) when(e is IOException || e is ArgumentException || e is InvalidOperationException)
            {heading.Text="Reference assets unavailable: "+e.Message;}
            view.SetData(data);roleNodes.Clear();requests.BeginUpdate();requests.Nodes.Clear();
            foreach(var role in catalog.ActiveRoles(project))
            {
                var root=new TreeNode(role.Label+(role.Required?"":" (optional)")) {Name=role.Id,Tag=new Request {Role=role}};
                SkeletonPart part=null;data?.roles.TryGetValue(role.Id,out part);
                foreach(var key in role.Hardpoints)
                {
                    var marker=part?.markers.FirstOrDefault(m=>m.id==key)??new SkeletonMarker {id=key,positions=Array.Empty<double[]>(),note="Not located in this reference."};
                    root.Nodes.Add(new TreeNode(key.Replace('_',' ')+(marker.positions.Length==0?" — not located":"")) {Name=key,Tag=new Request {Role=role,Marker=marker},ToolTipText=marker.note});
                }
                requests.Nodes.Add(root);roleNodes[role.Id]=root;
            }
            requests.EndUpdate();SelectRole(previous??"frame");
        }
        public void SelectRole(string id)
        {
            if(id!=null&&roleNodes.TryGetValue(id,out var node)){requests.SelectedNode=node;node.Expand();node.EnsureVisible();}
            else if(requests.Nodes.Count>0)requests.SelectedNode=requests.Nodes[0];
        }
        public void CompactGuide()
        {requests.Visible=false;layout.ColumnStyles[0].Width=0;}
        public void SelectMarker(string role,string marker)
        {
            SelectRole(role);
            if(role!=null&&roleNodes.TryGetValue(role,out var root))
            {var node=root.Nodes.Cast<TreeNode>().FirstOrDefault(n=>n.Name==marker);if(node!=null)requests.SelectedNode=node;}
        }
        private void ShowRequest(Request request)
        {
            if(request==null)return;
            view.Select(request.Role.Id,request.Role.Label,request.Marker);
            var marker=request.Marker;SkeletonPart part=null;data?.roles.TryGetValue(request.Role.Id,out part);
            if(data==null){detail.Text="No matching tested example. This guide does not infer hardpoints for unsupported layouts.";return;}
            if(marker==null)
            {
                detail.Text=request.Role.Label+"\r\nLeft/right are vehicle sides while seated facing forward (FL = front left; RL = rear left).\r\n"+(part?.vertices.Length>0?"Selected physical mesh highlighted. Choose a requested point below this part to see its location.":"No separate mesh exists for this optional group in the tested vehicle.")+"\r\n"+data.units+". Hardpoint markers are attachment definitions, not the full generated node graph.";
                return;
            }
            var coordinates=string.Join("; ",marker.positions.Select((p,i)=>(marker.positions.Length>1?(i+1)+": ":"")+string.Join(", ",p.Select(v=>v.ToString("0.0000",CultureInfo.InvariantCulture)))));
            detail.Text=request.Role.Label+" / "+marker.id.Replace('_',' ')+"\r\n"+(marker.positions.Length==0?marker.note:
                "Example XYZ (m): "+coordinates+"\r\n"+marker.note+"  Source: "+marker.source)+"\r\nUse corresponding geometry on your CAD. This view does not assign or move points.";
        }

        private sealed class SkeletonView : Control
        {
            private SkeletonData data;private string selected,label;private SkeletonMarker marker;
            private double[] center={0,0,0};private double span=3,yaw=.6,pitch=.55,zoom=1;
            private bool focusing,orbit;private Point drag;
            private readonly List<Tuple<PointF,SkeletonMarker>> hit=new List<Tuple<PointF,SkeletonMarker>>();
            public event Action<SkeletonMarker> MarkerPicked;
            public SkeletonView()
            {
                DoubleBuffered=true;ResizeRedraw=true;BackColor=Color.FromArgb(245,247,250);
                MouseDown+=(s,e)=>{Focus();if(e.Button==MouseButtons.Right){orbit=true;drag=e.Location;Capture=true;}
                    else if(e.Button==MouseButtons.Left){var nearest=hit.OrderBy(h=>Distance(h.Item1,e.Location)).FirstOrDefault();if(nearest!=null&&Distance(nearest.Item1,e.Location)<144)MarkerPicked?.Invoke(nearest.Item2);}};
                MouseUp+=(s,e)=>{orbit=false;Capture=false;};MouseCaptureChanged+=(s,e)=>{if(!Capture)orbit=false;};
                MouseMove+=(s,e)=>{if(orbit){yaw+=(e.X-drag.X)*.01;pitch=Math.Max(-1.55,Math.Min(1.57,pitch+(e.Y-drag.Y)*.01));drag=e.Location;Invalidate();}};
                MouseWheel+=(s,e)=>{zoom=Math.Max(.3,Math.Min(8,zoom*Math.Pow(1.15,e.Delta/120.0)));Invalidate();};
            }
            private static double Distance(PointF a,Point b)=>Math.Pow(a.X-b.X,2)+Math.Pow(a.Y-b.Y,2);
            public void SetData(SkeletonData value){data=value;Bounds();Invalidate();}
            public void Select(string id,string title,SkeletonMarker point){selected=id;label=title;marker=point;Bounds();Invalidate();}
            public void FocusPart(bool value){focusing=value;zoom=1;Bounds();Invalidate();}
            public void SetAngle(int index){yaw=index==0?.6:index==1||index==4?Math.PI:index==3?Math.PI/2:0;pitch=index==1?Math.PI/2:index==0?.55:0;zoom=1;Invalidate();}
            private new void Bounds()
            {
                SkeletonPart part=null;data?.roles.TryGetValue(selected??"",out part);
                var points=(focusing&&part?.vertices.Length>0?part.vertices:data?.roles.Values.SelectMany(p=>p.vertices).ToArray())??Array.Empty<double[]>();
                if(points.Length==0)return;
                center=Enumerable.Range(0,3).Select(i=>(points.Max(p=>p[i])+points.Min(p=>p[i]))/2).ToArray();
                span=Math.Max(.2,Enumerable.Range(0,3).Max(i=>points.Max(p=>p[i])-points.Min(p=>p[i])));
            }
            private PointF Project(double[] p)
            {
                var x=p[0]-center[0];var y=p[1]-center[1];var z=p[2]-center[2];var scale=Math.Min(Width,Height)*.72*zoom/span;
                return new PointF((float)(Width*.5+(x*Math.Cos(yaw)-y*Math.Sin(yaw))*scale),
                    (float)(Height*.52-(z*Math.Cos(pitch)+(x*Math.Sin(yaw)+y*Math.Cos(yaw))*Math.Sin(pitch))*scale));
            }
            protected override void OnPaint(PaintEventArgs e)
            {
                base.OnPaint(e);hit.Clear();var g=e.Graphics;g.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                if(data==null){g.DrawString("Choose a supported vehicle configuration to see its tested reference.",Font,Brushes.DimGray,new RectangleF(20,30,Math.Max(10,Width-40),90));return;}
                using(var muted=new Pen(Color.FromArgb(195,204,214),1))using(var blue=new Pen(Color.FromArgb(15,97,180),2))
                {
                    foreach(var pair in data.roles.OrderBy(p=>p.Key==selected?1:0))
                    {
                        var points=pair.Value.vertices.Select(Project).ToArray();
                        foreach(var edge in pair.Value.edges)g.DrawLine(pair.Key==selected?blue:muted,points[edge[0]],points[edge[1]]);
                    }
                }
                SkeletonPart part;data.roles.TryGetValue(selected??"",out part);
                foreach(var m in part?.markers??Array.Empty<SkeletonMarker>())
                {
                    var active=marker==null||marker==m;
                    var screen=m.positions.Select(Project).ToArray();
                    if(screen.Length==2&&m.id.EndsWith("axis"))using(var pen=new Pen(active?Color.DarkOrange:Color.Tan,3))
                    {pen.EndCap=System.Drawing.Drawing2D.LineCap.ArrowAnchor;g.DrawLine(pen,screen[0],screen[1]);}
                    for(var i=0;i<screen.Length;i++)
                    {
                        var p=screen[i];hit.Add(Tuple.Create(p,m));var radius=active?5:3;
                        g.FillEllipse(active?Brushes.DarkOrange:Brushes.Tan,p.X-radius,p.Y-radius,radius*2,radius*2);
                        g.DrawEllipse(Pens.White,p.X-radius,p.Y-radius,radius*2,radius*2);
                        // Only the requested hardpoint is text-labelled; the part
                        // overview uses dots so nearby suspension labels don't pile up.
                        if(marker==m)DrawLabel(g,m.id.Replace('_',' ')+(screen.Length>1?" "+(i+1):""),p.X+9,p.Y-20-i%2*18);
                    }
                }
                DrawLabel(g,label??"",12,12);
                if(marker?.positions.Length==0)DrawLabel(g,"No declared location for this request",12,38);
                // Compact orientation triad anchored to the view, independent of
                // world origin or zoom; +X is the vehicle's left, front is -Y.
                var origin=new PointF(65,Height-60);
                foreach(var axis in new[]{Tuple.Create("Left +X",1.0,0.0,0.0,Color.Firebrick),Tuple.Create("Front -Y",0.0,-1.0,0.0,Color.ForestGreen),Tuple.Create("Up +Z",0.0,0.0,1.0,Color.RoyalBlue)})
                {
                    var tip=new PointF(origin.X+(float)((axis.Item2*Math.Cos(yaw)-axis.Item3*Math.Sin(yaw))*35),origin.Y-(float)((axis.Item4*Math.Cos(pitch)+(axis.Item2*Math.Sin(yaw)+axis.Item3*Math.Cos(yaw))*Math.Sin(pitch))*35));
                    using(var pen=new Pen(axis.Item5,2))g.DrawLine(pen,origin,tip);g.DrawString(axis.Item1,Font,Brushes.DimGray,tip);
                }
            }
            private void DrawLabel(Graphics g,string text,float x,float y)
            {
                var size=g.MeasureString(text,Font);x=Math.Max(3,Math.Min(Width-size.Width-6,x));y=Math.Max(3,Math.Min(Height-size.Height-6,y));
                g.FillRectangle(Brushes.White,x-2,y-2,size.Width+4,size.Height+4);g.DrawString(text,Font,Brushes.Black,x,y);
            }
        }
    }
}
