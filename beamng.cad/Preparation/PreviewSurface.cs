using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Media.Media3D;

namespace BeamNG.Cad.Preparation
{
    // Indexed display geometry. Never a physical graph or an ownership contract.
    internal sealed class PreviewSurface
    {
        internal readonly Point3D[] Vertices;
        internal readonly int[] Triangles;
        internal PreviewSurface(Point3D[] vertices,int[] triangles)
        {
            if(triangles.Length%3!=0||triangles.Any(i=>i<0||i>=vertices.Length))throw new InvalidDataException("Invalid indexed preview mesh.");
            if(vertices.Any(p=>!Finite(p.X)||!Finite(p.Y)||!Finite(p.Z)))throw new InvalidDataException("Non-finite preview mesh.");
            var used=triangles.Distinct().OrderBy(i=>i).ToArray();var map=new int[vertices.Length];
            for(int i=0;i<used.Length;i++)map[used[i]]=i;
            Vertices=used.Select(i=>vertices[i]).ToArray();Triangles=triangles.Select(i=>map[i]).ToArray();
        }
        private static bool Finite(double v)=>!double.IsNaN(v)&&!double.IsInfinity(v);
        internal float[] Lines()
        {
            var edges=new SortedSet<long>();for(int i=0;i<Triangles.Length;i+=3)for(int k=0;k<3;k++)
            {int a=Triangles[i+k],b=Triangles[i+(k+1)%3];edges.Add(((long)Math.Min(a,b)<<32)|(uint)Math.Max(a,b));}
            var result=new float[edges.Count*8];int at=0;
            foreach(long key in edges)foreach(int i in new[]{(int)(key>>32),(int)(key&uint.MaxValue)})
            {var p=Vertices[i];result[at++]=(float)p.X;result[at++]=(float)p.Y;result[at++]=(float)p.Z;result[at++]=1;}
            return result;
        }
        internal static PreviewSurface ReadOff(string file,Point3D center,double scale,CancellationToken token)
        {
            using(var reader=new StreamReader(file))
            {
                Func<string[]> line=()=>{while(true){token.ThrowIfCancellationRequested();var s=reader.ReadLine();if(s==null)throw new InvalidDataException("Truncated OFF mesh.");s=s.Split('#')[0].Trim();if(s.Length>0)return s.Split((char[])null,StringSplitOptions.RemoveEmptyEntries);}};
                if(line()[0]!="OFF")throw new InvalidDataException("Expected OFF mesh.");var counts=line();int nv=int.Parse(counts[0]),nf=int.Parse(counts[1]);
                if(nv<1||nv>1000000||nf<1||nf>2000000)throw new InvalidDataException("OFF mesh exceeds preview limits.");
                var vertices=new Point3D[nv];for(int i=0;i<nv;i++){var p=line();vertices[i]=new Point3D((double.Parse(p[0],CultureInfo.InvariantCulture)-center.X)/scale,(double.Parse(p[1],CultureInfo.InvariantCulture)-center.Y)/scale,(double.Parse(p[2],CultureInfo.InvariantCulture)-center.Z)/scale);}
                var triangles=new List<int>();for(int f=0;f<nf;f++){var p=line();int n=int.Parse(p[0]);if(n<3||n>10000||p.Length!=n+1)throw new InvalidDataException("Invalid OFF face.");var face=p.Skip(1).Select(int.Parse).ToArray();for(int k=1;k<n-1;k++)triangles.AddRange(new[]{face[0],face[k],face[k+1]});}
                return new PreviewSurface(vertices,triangles.ToArray());
            }
        }
        internal string ValidateShell(CancellationToken token)
        {
            int nf=Triangles.Length/3;if(nf<4)return "No closed shell survives.";
            var edges=new Dictionary<long,List<Tuple<int,int>>>();var faces=new HashSet<string>();var incident=Enumerable.Range(0,Vertices.Length).Select(i=>new List<int>()).ToArray();
            for(int f=0;f<nf;f++)
            {
                token.ThrowIfCancellationRequested();var ids=new[]{Triangles[3*f],Triangles[3*f+1],Triangles[3*f+2]};var sorted=ids.OrderBy(i=>i).ToArray();
                if(sorted.Distinct().Count()!=3||Vector3D.CrossProduct(Vertices[ids[1]]-Vertices[ids[0]],Vertices[ids[2]]-Vertices[ids[0]]).LengthSquared<1e-24)return "Collapsed triangle.";
                if(!faces.Add(string.Join(",",sorted)))return "Duplicate faces.";
                foreach(int i in ids)incident[i].Add(f);
                for(int k=0;k<3;k++){int a=ids[k],b=ids[(k+1)%3];long key=((long)Math.Min(a,b)<<32)|(uint)Math.Max(a,b);List<Tuple<int,int>> entries;if(!edges.TryGetValue(key,out entries))edges[key]=entries=new List<Tuple<int,int>>();entries.Add(Tuple.Create(f,a<b?1:-1));}
            }
            if(edges.Values.Any(e=>e.Count!=2))return "Open seam or nonmanifold edge.";
            if(edges.Values.Any(e=>e[0].Item2==e[1].Item2))return "Inconsistent face orientation.";
            var adjacency=Enumerable.Range(0,nf).Select(i=>new List<int>()).ToArray();
            foreach(var pair in edges.Values){adjacency[pair[0].Item1].Add(pair[1].Item1);adjacency[pair[1].Item1].Add(pair[0].Item1);}
            var seen=new HashSet<int>();var queue=new Queue<int>();queue.Enqueue(0);seen.Add(0);
            while(queue.Count>0)foreach(int f in adjacency[queue.Dequeue()])if(seen.Add(f))queue.Enqueue(f);
            if(seen.Count!=nf)return "Disconnected shells.";
            if(Vertices.Length-edges.Count+nf!=2)return "Through-holes remain in the shell.";
            // Every vertex link must form one cycle, including pinched-vertex cases.
            for(int v=0;v<incident.Length;v++)
            {
                var link=new Dictionary<int,List<int>>();foreach(int f in incident[v]){var ids=new[]{Triangles[3*f],Triangles[3*f+1],Triangles[3*f+2]}.Where(i=>i!=v).ToArray();foreach(int i in ids)if(!link.ContainsKey(i))link[i]=new List<int>();link[ids[0]].Add(ids[1]);link[ids[1]].Add(ids[0]);}
                if(link.Values.Any(a=>a.Count!=2))return "Pinched shell vertex.";
                var visited=new HashSet<int>();var pending=new Stack<int>();pending.Push(link.Keys.First());while(pending.Count>0){int i=pending.Pop();if(visited.Add(i))foreach(int j in link[i])pending.Push(j);}if(visited.Count!=link.Count)return "Pinched shell vertex.";
            }
            double volume=0;for(int f=0;f<nf;f++){var a=Vertices[Triangles[3*f]];var b=Vertices[Triangles[3*f+1]];var c=Vertices[Triangles[3*f+2]];volume+=Vector3D.DotProduct((Vector3D)a,Vector3D.CrossProduct((Vector3D)b,(Vector3D)c));}
            if(Math.Abs(volume)<1e-10)return "Collapsed enclosed volume.";
            return Intersections(token)?"Self-intersecting shell.":null;
        }
        private bool Intersections(CancellationToken token)
        {
            int count=Triangles.Length/3;var bounds=new Rect3D[count];for(int f=0;f<count;f++){var b=Rect3D.Empty;for(int k=0;k<3;k++)b.Union(Vertices[Triangles[3*f+k]]);bounds[f]=b;}
            var order=Enumerable.Range(0,count).OrderBy(i=>bounds[i].X).ToArray();
            for(int i=0;i<count;i++)
            {
                token.ThrowIfCancellationRequested();int a=order[i];
                for(int j=i+1;j<count&&bounds[order[j]].X<=bounds[a].X+bounds[a].SizeX+1e-9;j++)
                {
                    int b=order[j];if(!bounds[a].IntersectsWith(bounds[b]))continue;
                    var ai=new[]{Triangles[3*a],Triangles[3*a+1],Triangles[3*a+2]};var bi=new[]{Triangles[3*b],Triangles[3*b+1],Triangles[3*b+2]};
                    var shared=ai.Intersect(bi).Select(v=>Vertices[v]).ToArray();var ap=ai.Select(v=>Vertices[v]).ToArray();var bp=bi.Select(v=>Vertices[v]).ToArray();
                    if(Crosses(ap,bp,shared)||Crosses(bp,ap,shared))return true;
                }
            }
            return false;
        }
        private static bool Allowed(Point3D p,Point3D[] shared)
        {
            if(shared.Any(q=>(p-q).LengthSquared<1e-16))return true;
            if(shared.Length==2){var d=shared[1]-shared[0];double t=Vector3D.DotProduct(p-shared[0],d)/d.LengthSquared;if(t>=-1e-8&&t<=1+1e-8&&(p-(shared[0]+d*t)).LengthSquared<1e-16)return true;}return false;
        }
        private static bool InTriangle(Point3D p,Point3D[] t,bool strict)
        {
            var u=t[1]-t[0];var v=t[2]-t[0];var w=p-t[0];double uu=Vector3D.DotProduct(u,u),uv=Vector3D.DotProduct(u,v),vv=Vector3D.DotProduct(v,v),wu=Vector3D.DotProduct(w,u),wv=Vector3D.DotProduct(w,v),den=uu*vv-uv*uv;
            if(Math.Abs(den)<1e-28)return false;double s=(vv*wu-uv*wv)/den,r=(uu*wv-uv*wu)/den,eps=strict?1e-8:-1e-8;return s>eps&&r>eps&&s+r<1-eps;
        }
        private static bool Crosses(Point3D[] a,Point3D[] b,Point3D[] shared)
        {
            var normal=Vector3D.CrossProduct(b[1]-b[0],b[2]-b[0]);normal.Normalize();
            for(int k=0;k<3;k++)
            {
                var p=a[k];var q=a[(k+1)%3];double dp=Vector3D.DotProduct(p-b[0],normal),dq=Vector3D.DotProduct(q-b[0],normal);
                if(Math.Abs(dp)<1e-9&&Math.Abs(dq)<1e-9)
                {
                    if(InTriangle(p,b,true)&&!Allowed(p,shared))return true;
                    // Coplanar edge crossings; endpoint contacts at shared topology are legal.
                    for(int e=0;e<3;e++)
                    {
                        var r=b[e];var s=b[(e+1)%3];var u=q-p;var v=s-r;var cross=Vector3D.CrossProduct(u,v);double den=cross.LengthSquared;if(den<1e-24)continue;
                        double t=Vector3D.DotProduct(Vector3D.CrossProduct(r-p,v),cross)/den,h=Vector3D.DotProduct(Vector3D.CrossProduct(r-p,u),cross)/den;
                        if(t>1e-8&&t<1-1e-8&&h>1e-8&&h<1-1e-8&&!Allowed(p+u*t,shared))return true;
                    }
                }
                else if(dp*dq<=0&&Math.Abs(dp-dq)>1e-12){var hit=p+(q-p)*(dp/(dp-dq));if(InTriangle(hit,b,false)&&!Allowed(hit,shared))return true;}
            }
            return false;
        }
    }
}
