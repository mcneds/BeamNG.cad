using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    public sealed class FixtureNodes { public string[] fixed_nodes; public string[] load_nodes; public Dictionary<string,double[]> load_vectors; }
    public sealed class ReviewNode { public string id; public double[] position; }
    public sealed class GenerationReview
    {
        public int version; public string graph_sha256; public bool approved;
        public ReviewNode[] nodes; public string[][] beams;
        public Dictionary<string,FixtureNodes> fixtures; public FixtureNodes cut_fixture;
        public static GenerationReview Load(string path)=>new JavaScriptSerializer().Deserialize<GenerationReview>(File.ReadAllText(path));
        public void Save(string path)=>File.WriteAllText(path,new JavaScriptSerializer().Serialize(this));
    }
    internal sealed class FixtureReview : Form
    {
        private readonly GenerationReview review;
        private readonly string path;
        private readonly ComboBox mode=new ComboBox {Name="FixtureMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=180};
        private readonly DataGridView vectors=new DataGridView {Dock=DockStyle.Bottom,Height=170,AllowUserToAddRows=false,AllowUserToDeleteRows=false,AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill};
        private readonly Label message=new Label {Dock=DockStyle.Bottom,AutoSize=true};
        private readonly GraphView graph;
        private bool loading;
        public FixtureReview(string path)
        {
            this.path=path;review=GenerationReview.Load(path);review.approved=false;
            Text="Review this generation's fixtures and orientation";Width=1000;Height=780;MinimumSize=new Size(760,600);
            graph=new GraphView(review) {Dock=DockStyle.Fill};graph.Picked+=Pick;
            var top=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
            top.Controls.Add(new Label {AutoSize=true,MaximumSize=new Size(900,0),Text="Check that +Z is up and -Y points to the vehicle front. Click nodes to toggle membership; right-drag to orbit. Each load vector is a fraction of the total test force. Supports are blue; loads are red."});
            mode.Items.AddRange(new object[]{"Flex supports","Flex loads","Torsion supports","Torsion loads","Cut loads"});mode.SelectedIndex=0;
            top.Controls.Add(mode);
            var reset=new Button {Text="Reset view",AutoSize=true};reset.Click+=(s,e)=>graph.ResetView();top.Controls.Add(reset);
            var approve=new Button {Name="ApproveFixtures",Text="Approve orientation and fixtures",AutoSize=true};
            approve.Click+=(s,e)=>Approve();
            var bottom=new FlowLayoutPanel {Dock=DockStyle.Bottom,AutoSize=true};bottom.Controls.Add(approve);
            var cancel=new Button {Text="Cancel",AutoSize=true,DialogResult=DialogResult.Cancel};bottom.Controls.Add(cancel);
            vectors.Columns.Add("node","Load node");vectors.Columns[0].ReadOnly=true;
            foreach(var axis in new[]{"X","Y","Z"})vectors.Columns.Add(axis,axis+" fraction");
            vectors.CellEndEdit+=(s,e)=> {if(!loading)ReadVectors();};
            mode.SelectedIndexChanged+=(s,e)=>RefreshView();
            Controls.Add(graph);Controls.Add(vectors);Controls.Add(message);Controls.Add(bottom);Controls.Add(top);
            RefreshView();
        }
        private FixtureNodes Current=>mode.SelectedIndex==4?review.cut_fixture:review.fixtures[mode.SelectedIndex<2?"flex":"torsion"];
        private void Pick(string id)
        {
            var f=Current;bool support=mode.SelectedIndex==0||mode.SelectedIndex==2;
            var set=new HashSet<string>((support?f.fixed_nodes:f.load_nodes)??Array.Empty<string>());
            if(!set.Remove(id))set.Add(id);
            if(support)f.fixed_nodes=set.ToArray();
            else
            {
                f.load_nodes=set.ToArray();f.load_vectors=new Dictionary<string,double[]>();
                for(int i=0;i<f.load_nodes.Length;i++)f.load_vectors[f.load_nodes[i]]=mode.SelectedIndex==4?new[]{0.0,-1.0/f.load_nodes.Length,0.0}:
                    new[]{0.0,0.0,(mode.SelectedIndex==3 && i%2==1?1.0:-1.0)/f.load_nodes.Length};
            }
            RefreshView();
        }
        private void RefreshView()
        {
            loading=true;
            try{vectors.Rows.Clear();foreach(var n in Current.load_nodes??Array.Empty<string>()){var v=Current.load_vectors[n];vectors.Rows.Add(n,v[0],v[1],v[2]);}}
            finally{loading=false;}
            graph.Fixture=Current;graph.Invalidate();message.Text="Editing "+mode.Text+". "+review.nodes.Length+" nodes; "+review.beams.Length+" beams. Changes apply only to this generation.";
        }
        private bool ReadVectors()
        {
            try{
                foreach(DataGridViewRow row in vectors.Rows){var v=new double[3];for(int i=0;i<3;i++){v[i]=Convert.ToDouble(row.Cells[i+1].Value);if(double.IsNaN(v[i])||double.IsInfinity(v[i]))throw new FormatException();}Current.load_vectors[(string)row.Cells[0].Value]=v;}
                graph.Invalidate();return true;
            }catch{message.Text="Enter finite numeric load fractions.";return false;}
        }
        private void Approve()
        {
            vectors.EndEdit();if(!ReadVectors())return;
            try
            {
                foreach(var item in review.fixtures.Concat(new[]{new KeyValuePair<string,FixtureNodes>("cut",review.cut_fixture)}))
                {
                    var f=item.Value;var supports=f.fixed_nodes??Array.Empty<string>();
                    if(f.load_nodes.Length==0 || (item.Key!="cut"&&supports.Length<3) || supports.Intersect(f.load_nodes).Any())
                        throw new InvalidDataException(item.Key+": choose at least three supports and separate loads (cut needs loads only).");
                    var sum=f.load_vectors.Values.Sum(v=>Math.Sqrt(v.Sum(x=>x*x)));
                    if(Math.Abs(sum-1)>1e-8)throw new InvalidDataException(item.Key+": load-vector magnitudes must sum to 1.0");
                }
                review.approved=true;review.Save(path);DialogResult=DialogResult.OK;Close();
            }catch(Exception e){message.Text=e.Message;}
        }
        private sealed class GraphView : Control
        {
            private readonly GenerationReview data;private readonly Dictionary<string,ReviewNode> nodes;
            private readonly double[] center;private readonly double span;
            private double yaw=.6,pitch=.45;private Point drag;private bool orbit;private string hover;
            private Dictionary<string,PointF> screen=new Dictionary<string,PointF>();
            public FixtureNodes Fixture;public event Action<string> Picked;
            public GraphView(GenerationReview data)
            {
                this.data=data;nodes=data.nodes.ToDictionary(n=>n.id);DoubleBuffered=true;BackColor=Color.FromArgb(245,247,250);
                center=Enumerable.Range(0,3).Select(i=>(data.nodes.Max(n=>n.position[i])+data.nodes.Min(n=>n.position[i]))/2).ToArray();
                span=Math.Max(.001,Enumerable.Range(0,3).Max(i=>data.nodes.Max(n=>n.position[i])-data.nodes.Min(n=>n.position[i])));
                MouseDown+=(s,e)=>{if(e.Button==MouseButtons.Right){orbit=true;drag=e.Location;Capture=true;}else if(e.Button==MouseButtons.Left&&hover!=null)Picked?.Invoke(hover);};
                MouseUp+=(s,e)=>{orbit=false;Capture=false;};
                MouseMove+=(s,e)=>{
                    if(orbit){yaw+=(e.X-drag.X)*.01;pitch+=(e.Y-drag.Y)*.01;drag=e.Location;Invalidate();return;}
                    hover=screen.Where(k=>Math.Pow(k.Value.X-e.X,2)+Math.Pow(k.Value.Y-e.Y,2)<100).OrderBy(k=>Math.Pow(k.Value.X-e.X,2)+Math.Pow(k.Value.Y-e.Y,2)).Select(k=>k.Key).FirstOrDefault();Invalidate();
                };
            }
            public void ResetView(){yaw=.6;pitch=.45;Invalidate();}
            private PointF Project(double[] p)
            {
                double x=p[0]-center[0],y=p[1]-center[1],z=p[2]-center[2],scale=Math.Min(Width,Height)*.65/span;
                double a=x*Math.Cos(yaw)-y*Math.Sin(yaw),b=x*Math.Sin(yaw)+y*Math.Cos(yaw);
                return new PointF((float)(Width/2+a*scale),(float)(Height/2-(z*Math.Cos(pitch)-b*Math.Sin(pitch))*scale));
            }
            protected override void OnPaint(PaintEventArgs e)
            {
                base.OnPaint(e);var g=e.Graphics;g.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                screen=nodes.ToDictionary(k=>k.Key,k=>Project(k.Value.position));
                foreach(var edge in data.beams)g.DrawLine(Pens.LightGray,screen[edge[0]],screen[edge[1]]);
                foreach(var node in data.nodes){var p=screen[node.id];bool support=(Fixture?.fixed_nodes??Array.Empty<string>()).Contains(node.id),load=(Fixture?.load_nodes??Array.Empty<string>()).Contains(node.id);
                    g.FillEllipse(support?Brushes.RoyalBlue:load?Brushes.OrangeRed:Brushes.SlateGray,p.X-3,p.Y-3,6,6);
                    if(support||load||hover==node.id)g.DrawString(node.id,Font,Brushes.Black,p.X+5,p.Y+2);
                    if(load){var v=Fixture.load_vectors[node.id];var end=Project(node.position.Select((x,i)=>x+v[i]*span*.25).ToArray());using(var pen=new Pen(Color.OrangeRed,2)){pen.EndCap=System.Drawing.Drawing2D.LineCap.ArrowAnchor;g.DrawLine(pen,p,end);}}
                }
                foreach(var axis in new[]{Tuple.Create("+X left",0,1.0,Color.Red),Tuple.Create("-Y front",1,-1.0,Color.Green),Tuple.Create("+Z up",2,1.0,Color.Blue)}){
                    var tip=(double[])center.Clone();tip[axis.Item2]+=axis.Item3*span*.35;var p=Project(tip);using(var pen=new Pen(axis.Item4,2)){pen.EndCap=System.Drawing.Drawing2D.LineCap.ArrowAnchor;g.DrawLine(pen,Project(center),p);}g.DrawString(axis.Item1,Font,Brushes.Black,p);
                }
            }
        }
    }
}
