using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Media.Media3D;

namespace BeamNG.Cad.Preparation
{
    internal sealed class HullSearch
    {
        internal sealed class Candidate
        {
            internal HullOptions Options;internal PreviewSurface Surface;internal double Error,MinimumIoU;
            internal string Problem,Check="Approximate";internal PreviewHull.Result Preview;
            internal bool Accepted;internal int Nodes=>Surface?.Vertices.Length??0;
            internal int Edges;
            internal void SetQuality(int quality)=>Accepted=Surface!=null&&Problem==null&&Error<=new[]{.15,.08,.04}[quality]&&MinimumIoU>=new[]{.70,.80,.90}[quality];
            internal string Eligibility(int quality)
            {
                if(Problem!=null)return "Optimizer warning: "+Problem+" You can Apply anyway to use these settings; inspect the prepared hull before generation.";
                return string.Format(CultureInfo.InvariantCulture,"{0}: fit {1:P1} (target {2:P1}); worst view {3:P1} (target {4:P1}). {5}",new[]{"Coarser","Balanced","Finer"}[quality],1-Error,1-new[]{.15,.08,.04}[quality],MinimumIoU,new[]{.70,.80,.90}[quality],Accepted?"Ready to Apply.":"Outside optimizer target. You can Apply anyway if this result suits your needs.");
            }
            public override string ToString()=>string.Format(CultureInfo.InvariantCulture,"{0} × {1} × {2} X/Y/Z · {3} vertices · fit {4:P1} · {5}{6}",Options.Width,Options.Length,Options.Height,Nodes,1-Error,Check,Accepted?"":" · "+(Problem??"outside fit tolerance"));
        }
        internal readonly Point3D Center;
        internal readonly double Scale;
        internal readonly Point3D[] Mapped;
        private readonly List<View> views=new List<View>();
        private const int Size=96;
        internal int Evaluations {get;private set;}
        internal double ElapsedSeconds {get;private set;}
        private sealed class View {internal Vector3D U,V;internal bool[] Mask;}
        internal HullSearch(Point3D[] source,string orientation,CancellationToken token)
        {
            var matrix=AxisMapping.Matrix(orientation);Mapped=new Point3D[source.Length];var bounds=Rect3D.Empty;
            for(int i=0;i<source.Length;i++){var p=source[i];Mapped[i]=new Point3D(matrix[0][0]*p.X+matrix[0][1]*p.Y+matrix[0][2]*p.Z,matrix[1][0]*p.X+matrix[1][1]*p.Y+matrix[1][2]*p.Z,matrix[2][0]*p.X+matrix[2][1]*p.Y+matrix[2][2]*p.Z);bounds.Union(Mapped[i]);}
            Center=new Point3D(bounds.X+bounds.SizeX/2,bounds.Y+bounds.SizeY/2,bounds.Z+bounds.SizeZ/2);Scale=Math.Sqrt(bounds.SizeX*bounds.SizeX+bounds.SizeY*bounds.SizeY+bounds.SizeZ*bounds.SizeZ);
            if(Scale<1e-12||double.IsNaN(Scale)||double.IsInfinity(Scale))throw new ArgumentException("No usable CAD extent for hull search.");
            var normalized=Mapped.Select(p=>(Point3D)((p-Center)/Scale)).ToArray();var mesh=new PreviewSurface(normalized,Enumerable.Range(0,normalized.Length).ToArray());
            for(int x=-1;x<=1;x++)for(int y=-1;y<=1;y++)for(int z=-1;z<=1;z++)
            {
                token.ThrowIfCancellationRequested();if(x==0&&y==0&&z==0)continue;
                var direction=new Vector3D(x,y,z);direction.Normalize();var u=Vector3D.CrossProduct(direction,Math.Abs(direction.Z)<.9?new Vector3D(0,0,1):new Vector3D(0,1,0));u.Normalize();var v=Vector3D.CrossProduct(direction,u);
                var view=new View {U=u,V=v};view.Mask=Raster(mesh,view,token,true);FillHoles(view.Mask);views.Add(view);
            }
        }
        internal static HullOptions Copy(HullOptions o)=>new HullOptions {Width=o.Width,Height=o.Height,Length=o.Length,Offset=o.Offset,Weld=o.Weld,ProxyDivisor=o.ProxyDivisor,ProxyOffsetRatio=o.ProxyOffsetRatio,Symmetry=o.Symmetry,SymmetryBisectFlip=o.SymmetryBisectFlip,SymmetryMergeDistance=o.SymmetryMergeDistance,Orientation=o.Orientation,CoordinateConvention=o.CoordinateConvention};
        internal Candidate Score(HullOptions options,PreviewSurface surface,int quality,CancellationToken token)
        {
            var candidate=new Candidate {Options=Copy(options),Surface=surface,Error=1,MinimumIoU=0};candidate.Problem=surface.ValidateShell(token);if(candidate.Problem!=null)return candidate;
            candidate.Edges=surface.Lines().Length/8;
            double total=0,worst=0;foreach(var view in views)
            {
                token.ThrowIfCancellationRequested();var mask=Raster(surface,view,token,true);int union=0,intersection=0;
                for(int i=0;i<mask.Length;i++){if(mask[i]||view.Mask[i])union++;if(mask[i]&&view.Mask[i])intersection++;}
                double error=union==0?1:1-(double)intersection/union;total+=error;worst=Math.Max(worst,error);
            }
            candidate.Error=.75*total/views.Count+.25*worst;candidate.MinimumIoU=1-worst;
            candidate.SetQuality(quality);return candidate;
        }
        private static bool[] Raster(PreviewSurface mesh,View view,CancellationToken token,bool conservative=false)
        {
            var mask=new bool[Size*Size];var x=new double[mesh.Vertices.Length];var y=new double[x.Length];
            for(int i=0;i<x.Length;i++){var p=(Vector3D)mesh.Vertices[i];x[i]=(Vector3D.DotProduct(p,view.U)/1.2+.5)*(Size-1);y[i]=(Vector3D.DotProduct(p,view.V)/1.2+.5)*(Size-1);}
            for(int f=0;f<mesh.Triangles.Length;f+=3)
            {
                if(f%3072==0)token.ThrowIfCancellationRequested();int a=mesh.Triangles[f],b=mesh.Triangles[f+1],c=mesh.Triangles[f+2];
                int x0=Math.Max(0,(int)Math.Floor(Math.Min(x[a],Math.Min(x[b],x[c])))),x1=Math.Min(Size-1,(int)Math.Ceiling(Math.Max(x[a],Math.Max(x[b],x[c]))));
                int y0=Math.Max(0,(int)Math.Floor(Math.Min(y[a],Math.Min(y[b],y[c])))),y1=Math.Min(Size-1,(int)Math.Ceiling(Math.Max(y[a],Math.Max(y[b],y[c]))));
                double area=(x[b]-x[a])*(y[c]-y[a])-(y[b]-y[a])*(x[c]-x[a]);if(Math.Abs(area)<1e-12)continue;
                double es=conservative?.5*(Math.Abs(y[c]-y[a])+Math.Abs(x[c]-x[a]))/Math.Abs(area):1e-8;
                double et=conservative?.5*(Math.Abs(x[b]-x[a])+Math.Abs(y[b]-y[a]))/Math.Abs(area):1e-8;
                double ew=conservative?.5*(Math.Abs(y[b]-y[c])+Math.Abs(x[b]-x[c]))/Math.Abs(area):1e-8;
                for(int iy=y0;iy<=y1;iy++)for(int ix=x0;ix<=x1;ix++)
                {
                    double s=((ix+.5-x[a])*(y[c]-y[a])-(iy+.5-y[a])*(x[c]-x[a]))/area,t=((x[b]-x[a])*(iy+.5-y[a])-(y[b]-y[a])*(ix+.5-x[a]))/area;
                    if(s>=-es&&t>=-et&&s+t<=1+ew)mask[ix+Size*iy]=true;
                }
            }
            return mask;
        }
        private static void FillHoles(bool[] mask)
        {
            var outside=new bool[mask.Length];var queue=new Queue<int>();Action<int> add=i=>{if(!mask[i]&&!outside[i]){outside[i]=true;queue.Enqueue(i);}};
            for(int i=0;i<Size;i++){add(i);add(i+Size*(Size-1));add(Size*i);add(Size*i+Size-1);}
            while(queue.Count>0){int i=queue.Dequeue(),x=i%Size,y=i/Size;if(x>0)add(i-1);if(x<Size-1)add(i+1);if(y>0)add(i-Size);if(y<Size-1)add(i+Size);}
            for(int i=0;i<mask.Length;i++)mask[i]=!outside[i];
        }
        internal async Task<List<Candidate>> RunAsync(HullOptions initial,int quality,Func<HullOptions,CancellationToken,Task<PreviewHull.Result>> evaluate,Func<HullOptions,string> proxyKey,Action<string> progress,CancellationToken token,int limit=150,double seconds=20)
        {
            var clock=Stopwatch.StartNew();var candidates=new List<Candidate>();var visited=new HashSet<string>();var pending=new Queue<HullOptions>();
            using var deadline=new CancellationTokenSource(TimeSpan.FromSeconds(seconds));using var linked=CancellationTokenSource.CreateLinkedTokenSource(token,deadline.Token);
            Action<int,int,int> seed=(x,y,z)=>{var o=Copy(initial);o.Width=x;o.Length=y;o.Height=z;if(o.Symmetry&&x%2==0)o.Width=Math.Min(11,x+1);pending.Enqueue(o);};
            pending.Enqueue(Copy(initial));seed(3,4,5);foreach(int n in new[]{3,5,7,9})seed(n,n,n);
            var welds=new[]{0,.0025*Scale,.005*Scale,.01*Scale,.02*Scale,.04*Scale,.05*Scale,initial.Weld}.Select(v=>Math.Min(1000,v)).Distinct().OrderBy(v=>v).ToArray();
            var alphas=Enumerable.Range(-4,9).Select(k=>Math.Max(.001,Math.Min(1000000,initial.ProxyDivisor*Math.Pow(2,k/2.0)))).Distinct().OrderBy(v=>v).ToArray();
            var expanded=new HashSet<Candidate>();int attempted=0;
            while(attempted<limit&&clock.Elapsed.TotalSeconds<seconds)
            {
                token.ThrowIfCancellationRequested();
                if(pending.Count==0)
                {
                    var best=Rank(candidates).Where(c=>!expanded.Contains(c)).GroupBy(c=>c.Options.Width+":"+c.Options.Length+":"+c.Options.Height+":"+c.Nodes+":"+Math.Round(c.Error,6)+":"+c.Problem).Select(g=>g.First()).Take(4).ToArray();if(best.Length==0)break;
                    foreach(var candidate in best)
                    {
                        expanded.Add(candidate);var o=candidate.Options;
                        for(int axis=0;axis<3;axis++)foreach(int sign in new[]{-1,1}){var next=Copy(o);int step=axis==0&&o.Symmetry?2:1;int n=(axis==0?o.Width:axis==1?o.Length:o.Height)+sign*step;if(n<2||n>12)continue;if(axis==0)next.Width=n;else if(axis==1)next.Length=n;else next.Height=n;pending.Enqueue(next);}
                        foreach(var levels in new[]{alphas,welds}){double value=ReferenceEquals(levels,alphas)?o.ProxyDivisor:o.Weld;foreach(double v in levels.Where(v=>v<value).Reverse().Take(1).Concat(levels.Where(v=>v>value).Take(1))){var next=Copy(o);if(ReferenceEquals(levels,alphas))next.ProxyDivisor=v;else next.Weld=v;pending.Enqueue(next);}}
                    }
                }
                if(pending.Count==0)break;var options=pending.Dequeue();
                string key=options.Width+":"+options.Length+":"+options.Height+":"+proxyKey(options)+":"+options.Weld.ToString("R",CultureInfo.InvariantCulture);
                if(!visited.Add(key))continue;attempted++;progress?.Invoke("Finding sparse hull: "+attempted+" / "+limit+" candidates · "+clock.Elapsed.TotalSeconds.ToString("0")+" s");
                try{var result=await evaluate(options,linked.Token);var candidate=await Task.Run(()=>Score(options,result.Surface,quality,linked.Token),linked.Token);candidate.Preview=result;candidates.Add(candidate);}
                catch(System.IO.InvalidDataException error){candidates.Add(new Candidate {Options=Copy(options),Problem=error.Message,Error=1});}
                catch(OperationCanceledException) when(!token.IsCancellationRequested){break;}
            }
            token.ThrowIfCancellationRequested();Evaluations=attempted;ElapsedSeconds=clock.Elapsed.TotalSeconds;return Shortlist(candidates);
        }
        private static IOrderedEnumerable<Candidate> Rank(IEnumerable<Candidate> candidates)=>candidates.OrderBy(c=>c.Accepted?0:c.Problem==null?1:2).ThenBy(c=>c.Accepted?c.Nodes:0).ThenBy(c=>c.Error).ThenBy(c=>c.Edges);
        internal static List<Candidate> Shortlist(IEnumerable<Candidate> candidates)
        {
            var all=Rank(candidates).Where(c=>c.Surface!=null).GroupBy(c=>c.Nodes+":"+Math.Round(c.Error,6)+":"+Math.Round(c.MinimumIoU,6)+":"+c.Problem).Select(g=>g.First()).ToList();var feasible=all.Where(c=>c.Accepted).ToList();if(feasible.Count==0)return all.Take(3).ToList();
            var frontier=feasible.Where(c=>!feasible.Any(o=>o!=c&&o.Nodes<=c.Nodes&&o.Error<=c.Error&&(o.Nodes<c.Nodes||o.Error<c.Error))).ToList();
            var chosen=new List<Candidate>();Action<Candidate> add=c=>{if(c!=null&&!chosen.Any(o=>o.Nodes==c.Nodes&&Math.Abs(o.Error-c.Error)<1e-8))chosen.Add(c);};
            add(frontier.FirstOrDefault());add(frontier.OrderBy(c=>c.Error).FirstOrDefault());add(frontier.OrderBy(c=>c.Error+.03*c.Nodes/Math.Max(1.0,frontier.Max(o=>o.Nodes))).FirstOrDefault());
            foreach(var candidate in frontier)if(chosen.Count<3)add(candidate);return chosen.OrderBy(c=>c.Nodes).Take(3).ToList();
        }
    }
}
