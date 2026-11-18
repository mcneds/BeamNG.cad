using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Media.Media3D;

namespace BeamNG.Cad.Preparation
{
    // Rendering data only. Never consumed by preparation, calibration or packaging.
    internal static class PreviewGeometry
    {
        internal const int MaxSourceTriangles=200000;
        internal sealed class Scene
        {
            public MeshGeometry3D Source,Overlay;
            public Point3D Center;
            public double Scale;
            public string Summary;
            internal PreviewSurface Surface;
        }
        private static bool Finite(double v)=>!double.IsNaN(v)&&!double.IsInfinity(v);
        private static void Check(Point3D p)
        {
            if(!Finite(p.X)||!Finite(p.Y)||!Finite(p.Z))throw new InvalidDataException("Non-finite preview coordinate.");
        }
        private static Point3D Map(Point3D p,double[][] m)=>new Point3D(
            m[0][0]*p.X+m[0][1]*p.Y+m[0][2]*p.Z,
            m[1][0]*p.X+m[1][1]*p.Y+m[1][2]*p.Z,
            m[2][0]*p.X+m[2][1]*p.Y+m[2][2]*p.Z);
        private static Point3D Normalize(Point3D p,Point3D center,double scale)=>new Point3D(
            (p.X-center.X)/scale,(p.Y-center.Y)/scale,(p.Z-center.Z)/scale);
        private static void Triangle(MeshGeometry3D mesh,Point3D a,Point3D b,Point3D c)
        {
            int start=mesh.Positions.Count;
            mesh.Positions.Add(a);mesh.Positions.Add(b);mesh.Positions.Add(c);
            mesh.TriangleIndices.Add(start);mesh.TriangleIndices.Add(start+1);mesh.TriangleIndices.Add(start+2);
        }
        private static MeshGeometry3D SourceMesh(Point3D[] points,Point3D center,double scale,CancellationToken token)
        {
            var mesh=new MeshGeometry3D();
            for(int i=0;i<points.Length;i+=3)
            {
                if(i%3072==0)token.ThrowIfCancellationRequested();
                Triangle(mesh,Normalize(points[i],center,scale),Normalize(points[i+1],center,scale),Normalize(points[i+2],center,scale));
            }
            mesh.Freeze();return mesh;
        }
        private sealed class CpuCache
        {
            internal PreviewHull Hull;internal uint[] Seeds;internal MeshGeometry3D Source;
            internal readonly Dictionary<string,uint[]> Volumes=new Dictionary<string,uint[]>();
        }
        private static readonly System.Runtime.CompilerServices.ConditionalWeakTable<Point3D[],Dictionary<string,CpuCache>> cpuCache=new System.Runtime.CompilerServices.ConditionalWeakTable<Point3D[],Dictionary<string,CpuCache>>();
        public static Scene Proxy(Point3D[] source,HullOptions options,CancellationToken token)
        {
            var entries=cpuCache.GetOrCreateValue(source);
            lock(entries){CpuCache cache;if(!entries.TryGetValue(options.Orientation,out cache))entries[options.Orientation]=cache=new CpuCache();return ProxyCore(source,options,token,cache);}
        }
        private static Scene ProxyCore(Point3D[] source,HullOptions options,CancellationToken token,CpuCache cache)
        {
            options.Validate();token.ThrowIfCancellationRequested();
            if(source.Length==0||source.Length%3!=0||source.Length/3>MaxSourceTriangles)
                throw new InvalidDataException("Invalid or oversized preview triangle snapshot.");
            var matrix=AxisMapping.Matrix(options.Orientation);
            var points=new Point3D[source.Length];
            var bounds=Rect3D.Empty;
            for(int i=0;i<source.Length;i++)
            {
                if(i%1024==0)token.ThrowIfCancellationRequested();
                Check(source[i]);points[i]=Map(source[i],matrix);bounds.Union(points[i]);
            }
            double diagonal=Math.Sqrt(bounds.SizeX*bounds.SizeX+bounds.SizeY*bounds.SizeY+bounds.SizeZ*bounds.SizeZ);
            if(!Finite(diagonal)||diagonal<1e-12)throw new InvalidDataException("Preview geometry has no usable extent.");
            var center=new Point3D(bounds.X+bounds.SizeX/2,bounds.Y+bounds.SizeY/2,bounds.Z+bounds.SizeZ/2);
            var scale=diagonal;
            var packed=new float[points.Length*4];
            for(int i=0;i<points.Length;i++){var p=Normalize(points[i],center,scale);packed[4*i]=(float)p.X;packed[4*i+1]=(float)p.Y;packed[4*i+2]=(float)p.Z;}
            const int n=64;double cell=Math.Max(bounds.SizeX,Math.Max(bounds.SizeY,bounds.SizeZ))/scale/38,low=-n*cell/2;
            // Conservative triangle boxes in O(triangles + volume), independent of
            // triangle size. The GPU path uses the tighter triangle/box SAT test.
            var volume=cache.Seeds;
            if(volume==null)
            {
            int stride=n+1;var delta=new int[stride*stride*stride];
            for(int t=0;t<points.Length;t+=3)
            {
                if(t%3072==0)token.ThrowIfCancellationRequested();var first=new int[3];var last=new int[3];
                for(int axis=0;axis<3;axis++)
                {
                    double a=packed[4*t+axis],b=packed[4*(t+1)+axis],c=packed[4*(t+2)+axis];
                    first[axis]=Math.Max(0,Math.Min(n-1,(int)Math.Floor((Math.Min(a,Math.Min(b,c))-low)/cell)));
                    last[axis]=Math.Max(0,Math.Min(n-1,(int)Math.Floor((Math.Max(a,Math.Max(b,c))-low)/cell)))+1;
                }
                for(int mask=0;mask<8;mask++)delta[((mask&1)==0?first[0]:last[0])+stride*(((mask&2)==0?first[1]:last[1])+stride*((mask&4)==0?first[2]:last[2]))]+=((mask&1)+((mask>>1)&1)+((mask>>2)&1))%2==0?1:-1;
            }
            volume=new uint[n*n*n];
            for(int z=0;z<n;z++)for(int y=0;y<n;y++)for(int x=0;x<n;x++)
            {
                int i=x+stride*(y+stride*z);
                if(x>0)delta[i]+=delta[i-1];if(y>0)delta[i]+=delta[i-stride];if(z>0)delta[i]+=delta[i-stride*stride];
                if(x>0&&y>0)delta[i]-=delta[i-1-stride];if(x>0&&z>0)delta[i]-=delta[i-1-stride*stride];if(y>0&&z>0)delta[i]-=delta[i-stride-stride*stride];
                if(x>0&&y>0&&z>0)delta[i]+=delta[i-1-stride-stride*stride];volume[x+n*(y+n*z)]=delta[i]>0?1u:0u;
            }
            cache.Seeds=volume;
            }
            int closing=(int)Math.Min(6,Math.Ceiling(1/options.ProxyDivisor/2/cell));
            int offset=(int)Math.Min(6,Math.Ceiling(1/options.ProxyDivisor/options.ProxyOffsetRatio/cell));
            var key=closing+":"+offset;uint[] closed;
            if(cache.Volumes.TryGetValue(key,out closed))volume=closed;
            else
            {
            foreach(bool erosion in new[]{false,true})for(int axis=0;axis<3;axis++)volume=Morph(volume,n,closing,axis,erosion,token);
            for(int axis=0;axis<3;axis++)volume=Morph(volume,n,offset,axis,false,token);
            if(cache.Volumes.Count<49)cache.Volumes[key]=volume;
            }
            if(cache.Hull==null)cache.Hull=new PreviewHull(packed,token);
            var result=cache.Hull.Evaluate(volume,n,low,cell,scale,options,token);
            var overlay=new MeshGeometry3D();for(int i=0;i<result.Lines.Length;i+=8)
                Segment(overlay,new Point3D(result.Lines[i],result.Lines[i+1],result.Lines[i+2]),new Point3D(result.Lines[i+4],result.Lines[i+5],result.Lines[i+6]));
            overlay.Freeze();return new Scene {Source=cache.Source??(cache.Source=SourceMesh(points,center,scale,token)),Overlay=overlay,Center=center,Scale=scale,Surface=result.Surface,
                Summary=string.Format(CultureInfo.InvariantCulture,"CPU estimate: grid {0} ? {1} ? {2} (X/Y/Z), {3} projected/welded vertices, {4} edges. Conservative proxy boxes; alpha morphology capped at 6 cells. Blender/CGAL result may differ.",options.Width,options.Length,options.Height,result.Points.Length,result.Lines.Length/8)};
        }
        private static uint[] Morph(uint[] input,int n,int radius,int axis,bool erosion,CancellationToken token)
        {
            var output=new uint[input.Length];int stride=axis==0?1:axis==1?n:n*n;
            for(int i=0;i<input.Length;i++)
            {
                if(i%1024==0)token.ThrowIfCancellationRequested();int p=(i/stride)%n;uint value=erosion?1u:0u;
                for(int k=-radius;k<=radius;k++){uint sample=p+k<0||p+k>=n?0u:input[i+k*stride];value=erosion?Math.Min(value,sample):Math.Max(value,sample);}
                output[i]=value;
            }
            return output;
        }
        public static Scene Exact(string path,Scene context,CancellationToken token)
        {
            // Stream OFF, validate before allocation, and batch segments into one
            // GPU mesh. No SolidWorks curves, modeler calls or temporary bodies.
            using(var reader=new StreamReader(path))
            {
                Func<string[]> line=()=>{
                    while(true){token.ThrowIfCancellationRequested();var value=reader.ReadLine();if(value==null)throw new InvalidDataException("Truncated OFF preview.");
                        value=value.Split('#')[0].Trim();if(value.Length>0)return value.Split((char[])null,StringSplitOptions.RemoveEmptyEntries);}
                };
                if(line()[0]!="OFF")throw new InvalidDataException("Expected OFF hull.");
                var counts=line();int count=int.Parse(counts[0]),faces=int.Parse(counts[1]);
                if(count<1||count>1000000||faces<0||faces>2000000)throw new InvalidDataException("Hull exceeds preview limits.");
                var points=new Point3D[count];var bounds=Rect3D.Empty;
                for(int i=0;i<count;i++)
                {
                    var p=line();points[i]=new Point3D(double.Parse(p[0],CultureInfo.InvariantCulture),double.Parse(p[1],CultureInfo.InvariantCulture),double.Parse(p[2],CultureInfo.InvariantCulture));
                    Check(points[i]);bounds.Union(points[i]);
                }
                var center=context?.Center??new Point3D(bounds.X+bounds.SizeX/2,bounds.Y+bounds.SizeY/2,bounds.Z+bounds.SizeZ/2);
                double scale=context?.Scale??Math.Max(1e-9,Math.Sqrt(bounds.SizeX*bounds.SizeX+bounds.SizeY*bounds.SizeY+bounds.SizeZ*bounds.SizeZ));
                var edges=new HashSet<long>();var mesh=new MeshGeometry3D();
                for(int f=0;f<faces;f++)
                {
                    var values=line();int n=int.Parse(values[0]);if(n<2||n>10000||values.Length!=n+1)throw new InvalidDataException("Invalid OFF face.");
                    var indices=values.Skip(1).Select(int.Parse).ToArray();
                    if(indices.Any(i=>i<0||i>=count))throw new InvalidDataException("Invalid OFF vertex index.");
                    for(int i=0;i<n;i++)
                    {
                        int a=indices[i],b=indices[(i+1)%n];if(a==b)continue;
                        long key=((long)Math.Min(a,b)<<32)|(uint)Math.Max(a,b);if(!edges.Add(key))continue;
                        if(edges.Count>100000)throw new InvalidDataException("Prepared graph exceeds the viewport's 100,000-edge budget. Prepared data is retained; inspect it externally or reduce grid resolution.");
                        Segment(mesh,Normalize(points[a],center,scale),Normalize(points[b],center,scale));
                    }
                }
                if(edges.Count==0)throw new InvalidDataException("Prepared hull has no edges.");
                mesh.Freeze();return new Scene {Source=context?.Source,Overlay=mesh,Center=center,Scale=scale,
                    Summary="Prepared hull: "+count.ToString("N0")+" vertices, "+edges.Count.ToString("N0")+" unique surface edges. Actual OFF result; these are not final braced beam counts."};
            }
        }
        internal static Scene Candidate(HullSearch reference,PreviewSurface surface,CancellationToken token)
        {
            var mesh=new MeshGeometry3D();var lines=surface.Lines();for(int i=0;i<lines.Length;i+=8){token.ThrowIfCancellationRequested();Segment(mesh,new Point3D(lines[i],lines[i+1],lines[i+2]),new Point3D(lines[i+4],lines[i+5],lines[i+6]));}mesh.Freeze();
            return new Scene {Source=SourceMesh(reference.Mapped,reference.Center,reference.Scale,token),Overlay=mesh,Surface=surface,Center=reference.Center,Scale=reference.Scale,Summary="Candidate—not applied"};
        }
        private static void Segment(MeshGeometry3D mesh,Point3D a,Point3D b)
        {
            var direction=b-a;if(direction.LengthSquared<1e-20)return;
            var u=Vector3D.CrossProduct(direction,new Vector3D(0,0,1));
            if(u.LengthSquared<1e-20)u=Vector3D.CrossProduct(direction,new Vector3D(0,1,0));
            u.Normalize();u*=0.0007;
            var v=Vector3D.CrossProduct(direction,u);v.Normalize();v*=0.0007;
            Triangle(mesh,a-u,b-u,b+u);Triangle(mesh,a-u,b+u,a+u);
            Triangle(mesh,a-v,b-v,b+v);Triangle(mesh,a-v,b+v,a+v);
        }
    }
}
