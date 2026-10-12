using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SolidWorks.Interop.sldworks;
namespace BeamNG.Cad.Preparation
{
    // Cached polyline bodies per assigned hull. All COM operations stay on the
    // SolidWorks UI thread; only immutable mesh parsing runs in the background.
    internal sealed class HullPreview : IDisposable
    {
        private readonly List<Body2> bodies = new List<Body2>();
        private readonly ModelDoc2 model;
        private readonly object displayHost;
        private readonly MathTransform toHost;
        private bool disposed;
        private bool requestedVisible;
        private Task visibilityTask;
        public bool Visible { get; private set; }
        private HullPreview(ISldWorks app, ModelDoc2 model)
        {
            this.model = model;
            displayHost = model;
            if (model.GetType() == 2)
            {
                var root = (Component2)model.ConfigurationManager.ActiveConfiguration.GetRootComponent3(true);
                var component = FindHost(root);
                if (component == null) throw new InvalidOperationException("Hull preview needs a visible, resolved part component.");
                displayHost = component;
                if (component.Transform2 != null) toHost = (MathTransform)component.Transform2.Inverse();
            }
        }
        private static Component2 FindHost(Component2 parent)
        {
            foreach (Component2 child in (object[])parent.GetChildren() ?? Array.Empty<object>())
            {
                if (child.IsSuppressed() || child.IsHidden(false)) continue;
                if (((ModelDoc2)child.GetModelDoc2())?.GetType() == 1) return child;
                var nested = FindHost(child);
                if (nested != null) return nested;
            }
            return null;
        }
        // Retained for automation callers. The interactive workflow uses CreateAsync.
        public HullPreview(ISldWorks app, ModelDoc2 model, string file, string orientation)
            : this(app, model, file, orientation, true) { }
        public HullPreview(ISldWorks app, ModelDoc2 model, string file, string orientation, bool visible)
            : this(app, model)
        {
            try { foreach(var path in Paths(Read(file, orientation))) AddPath((Modeler)app.GetModeler(), path); if(visible) SetVisible(true); }
            catch { Dispose(); throw; }
        }
        public static async Task<HullPreview> CreateAsync(ISldWorks app, ModelDoc2 model, string file,
            string orientation, bool visible, CancellationToken token, Action validate, Action<string> log)
        {
            var clock = Stopwatch.StartNew();
            var paths = await Task.Run(() => Paths(Read(file, orientation)), token);
            token.ThrowIfCancellationRequested(); validate();
            var preview = new HullPreview(app, model);
            try
            {
                var modeler = (Modeler)app.GetModeler();
                var completedPaths=0;
                foreach (var path in paths)
                {
                    token.ThrowIfCancellationRequested(); validate();
                    preview.AddPath(modeler, path);
                    log?.Invoke("CAD_PROGRESS {\"phase\":\"Hull preview\",\"completed\":"+(++completedPaths)+",\"total\":"+paths.Length+"}");
                    await Task.Delay(1, token);
                }
                token.ThrowIfCancellationRequested(); validate();
                if(visible) await preview.SetVisibleAsync(true);
                token.ThrowIfCancellationRequested();validate();
                log?.Invoke("Preview creation: " + clock.ElapsedMilliseconds + " ms, " + paths.Sum(p=>p.Length-1) + " edges, " + preview.bodies.Count + " display paths.");
                return preview;
            }
            catch { preview.Dispose(); throw; }
        }
        private static double[][][] Read(string file, string orientation)
        {
            var lines = File.ReadAllLines(file).Select(l => l.Split('#')[0].Trim()).Where(l => l.Length > 0).ToArray();
            if (lines.Length < 2 || lines[0] != "OFF") throw new InvalidDataException("Invalid hull preview format.");
            var counts = Split(lines[1]).Select(int.Parse).ToArray();
            var matrix = AxisMapping.Matrix(orientation);
            var vertices = lines.Skip(2).Take(counts[0]).Select(l => Split(l).Select(v => double.Parse(v, CultureInfo.InvariantCulture)).ToArray())
                .Select(p => Enumerable.Range(0,3).Select(i => matrix[0][i]*p[0]+matrix[1][i]*p[1]+matrix[2][i]*p[2]).ToArray()).ToArray();
            var seen = new HashSet<Tuple<int,int>>();
            var edges = new List<double[][]>();
            foreach (var line in lines.Skip(2+counts[0]).Take(counts[1]))
            {
                var face = Split(line).Select(int.Parse).ToArray();
                for (var i=1; i<=face[0]; i++)
                {
                    var a=face[i]; var b=face[i==face[0]?1:i+1];
                    if (!seen.Add(Tuple.Create(Math.Min(a,b),Math.Max(a,b)))) continue;
                    var p=vertices[a]; var q=vertices[b];
                    if (p.Zip(q,(x,y)=>(x-y)*(x-y)).Sum() > 1e-20) edges.Add(new[]{p,q});
                }
            }
            if (edges.Count == 0) throw new InvalidDataException("Hull has no displayable edges.");
            return edges.ToArray();
        }
        // CreateWireBody(array) drops branch curves on this SolidWorks version.
        // Partition into simple polylines: every original edge appears exactly once,
        // without connecting separate islands or retracing/self-touching vertices.
        private static double[][][] Paths(double[][][] edges)
        {
            var adjacent=new Dictionary<double[],List<int>>();
            for(var i=0;i<edges.Length;i++) foreach(var point in edges[i])
            {
                if(!adjacent.TryGetValue(point,out var indices))adjacent[point]=indices=new List<int>();
                indices.Add(i);
            }
            var used=new bool[edges.Length];
            var paths=new List<double[][]>();
            for(var start=0;start<edges.Length;start++)
            {
                if(used[start])continue;
                var path=new List<double[]> {edges[start][0]};
                var visited=new HashSet<double[]> {path[0]};
                while(true)
                {
                    var end=path[path.Count-1];
                    var offset=adjacent[end].FindIndex(i=>!used[i] && !visited.Contains(ReferenceEquals(edges[i][0],end)?edges[i][1]:edges[i][0]));
                    if(offset<0)break;
                    var next=adjacent[end][offset];
                    var edge=edges[next];var vertex=ReferenceEquals(edge[0],end)?edge[1]:edge[0];
                    if(visited.Contains(vertex))break;
                    used[next]=true;visited.Add(vertex);path.Add(vertex);
                }
                paths.Add(path.ToArray());
            }
            return paths.ToArray();
        }
        private void AddPath(Modeler modeler, double[][] path)
        {
            // An order-two B-spline is exactly a polyline, not a smoothed hull.
            var props=new double[2]; Buffer.BlockCopy(new[]{3,2,path.Length,0},0,props,0,16);
            var knots=Enumerable.Range(0,path.Length+2).Select(i=>(double)Math.Max(0,Math.Min(path.Length-1,i-1))).ToArray();
            var curve=(Curve)modeler.CreateBsplineCurve(props,knots,path.SelectMany(p=>p).ToArray());
            var wire=curve==null?null:(Body2)curve.CreateWireBody();
            if(wire==null || wire.GetEdgeCount()!=path.Length-1)
            {
                // The native modeler merges collinear spans or rejects a path
                // where geometric edges cross. Subdivide only those paths,
                // preserving every segment and keeping ordinary hulls batched.
                if(path.Length<=2)throw new InvalidOperationException("SolidWorks could not create a hull display segment.");
                var middle=path.Length/2;
                AddPath(modeler,path.Take(middle+1).ToArray());
                AddPath(modeler,path.Skip(middle).ToArray());
                return;
            }
            bodies.Add(wire);
            if(toHost!=null && !wire.ApplyTransform(toHost))throw new InvalidOperationException("Could not position the hull preview.");
        }
        private static string[] Split(string s) => s.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
        public Task SetVisibleAsync(bool visible)
        {
            if(disposed)throw new ObjectDisposedException(nameof(HullPreview));
            requestedVisible=visible;
            if(visibilityTask==null || visibilityTask.IsCompleted)visibilityTask=ApplyVisibilityAsync();
            return visibilityTask;
        }
        private async Task ApplyVisibilityAsync()
        {
            var view=(ModelView)model.ActiveView;var enabled=view.EnableGraphicsUpdate;
            try
            {
                view.EnableGraphicsUpdate=false;
                bool target;
                do
                {
                    target=requestedVisible;
                    var batch=Stopwatch.StartNew();
                    foreach(var body in bodies.ToArray())
                    {
                        if(disposed)return;
                        if(target)
                        {
                            var result=body.Display3(displayHost,0x00A5FF,0);
                            if(result!=0)throw new InvalidOperationException("SolidWorks could not display the hull (status "+result+").");
                        }
                        else body.Hide(displayHost);
                        if(batch.ElapsedMilliseconds>=12)
                        {
                            view.EnableGraphicsUpdate=enabled;
                            await Task.Delay(1);
                            if(disposed)return;
                            view.EnableGraphicsUpdate=false;batch.Restart();
                        }
                    }
                    if(disposed)return;
                    Visible=target;
                }while(target!=requestedVisible);
            }
            catch
            {
                foreach(var body in bodies)try{body.Hide(displayHost);}catch{}
                Visible=false;throw;
            }
            finally {try{view.EnableGraphicsUpdate=enabled;model.GraphicsRedraw2();}catch{} }
        }
        public void SetVisible(bool visible)
        {
            if (disposed) throw new ObjectDisposedException(nameof(HullPreview));
            if (Visible == visible) return;
            var view=(ModelView)model.ActiveView;
            var graphicsEnabled=view.EnableGraphicsUpdate;
            try
            {
                view.EnableGraphicsUpdate=false;
                foreach(var body in bodies)
                if (visible)
                {
                    var result=body.Display3(displayHost,0x00A5FF,0);
                    if (result != 0) throw new InvalidOperationException("SolidWorks could not display the hull (status " + result + ").");
                }
                else body.Hide(displayHost);
                Visible=visible;
            }
            catch { foreach(var body in bodies) try { body.Hide(displayHost); } catch { } Visible=false; throw; }
            finally { view.EnableGraphicsUpdate=graphicsEnabled; model.GraphicsRedraw2(); }
        }
        public async Task DisposeAsync()
        {
            if(disposed)return;
            try { await SetVisibleAsync(false); }
            finally { disposed=true;Visible=false;bodies.Clear(); }
        }
        public void Dispose()
        {
            if (disposed) return;
            try { if(Visible || (visibilityTask!=null && !visibilityTask.IsCompleted)){foreach(var body in bodies)body.Hide(displayHost);model.GraphicsRedraw2();} } catch { }
            disposed=true; Visible=false; bodies.Clear();
        }
    }
}
