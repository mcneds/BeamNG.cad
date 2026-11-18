using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Windows.Media.Media3D;

namespace BeamNG.Cad.Preparation
{
    // Display-only continuation of an approximate pruning volume. This follows the
    // production stage order, but does not claim Blender/CGAL topology equivalence.
    internal sealed class PreviewHull
    {
        private readonly Point3D[] source;
        private readonly int[] triangles;
        private readonly Node root;
        private readonly CancellationToken constructionToken;
        private sealed class Node {internal Rect3D Bounds;internal Node A,B;internal int Start,Count;}
        internal sealed class Result {internal float[] Lines;internal Point3D[] Points;internal int Faces;internal PreviewSurface Surface;internal uint[] PruningVolume;}
        internal PreviewHull(float[] packed,CancellationToken token)
        {
            constructionToken=token;
            source=Enumerable.Range(0,packed.Length/4).Select(i=>new Point3D(packed[4*i],packed[4*i+1],packed[4*i+2])).ToArray();
            triangles=Enumerable.Range(0,source.Length/3).Where(t=>Vector3D.CrossProduct(source[3*t+1]-source[3*t],source[3*t+2]-source[3*t]).LengthSquared>1e-26).ToArray();
            if(triangles.Length==0)throw new System.IO.InvalidDataException("No usable triangles in the preview snapshot.");
            root=Build(0,triangles.Length);
        }
        private Node Build(int start,int count)
        {
            constructionToken.ThrowIfCancellationRequested();var bounds=Rect3D.Empty;
            for(int i=start;i<start+count;i++)for(int k=0;k<3;k++)bounds.Union(source[3*triangles[i]+k]);
            var node=new Node {Bounds=bounds,Start=start,Count=count};if(count<=8)return node;
            int axis=bounds.SizeX>=bounds.SizeY&&bounds.SizeX>=bounds.SizeZ?0:bounds.SizeY>=bounds.SizeZ?1:2;
            Array.Sort(triangles,start,count,Comparer<int>.Create((a,b)=>Center(a,axis).CompareTo(Center(b,axis))));
            int half=count/2;node.A=Build(start,half);node.B=Build(start+half,count-half);return node;
        }
        private double Center(int t,int axis)=>(At(source[3*t],axis)+At(source[3*t+1],axis)+At(source[3*t+2],axis))/3;
        private static double At(Point3D p,int axis)=>axis==0?p.X:axis==1?p.Y:p.Z;
        private static double Distance(Rect3D b,Point3D p)
        {
            double x=Math.Max(0,Math.Max(b.X-p.X,p.X-b.X-b.SizeX)),y=Math.Max(0,Math.Max(b.Y-p.Y,p.Y-b.Y-b.SizeY)),z=Math.Max(0,Math.Max(b.Z-p.Z,p.Z-b.Z-b.SizeZ));return x*x+y*y+z*z;
        }
        private static Point3D Closest(Point3D p,Point3D a,Point3D b,Point3D c)
        {
            var ab=b-a;var ac=c-a;var ap=p-a;double d1=Vector3D.DotProduct(ab,ap),d2=Vector3D.DotProduct(ac,ap);
            if(d1<=0&&d2<=0)return a;
            var bp=p-b;double d3=Vector3D.DotProduct(ab,bp),d4=Vector3D.DotProduct(ac,bp);if(d3>=0&&d4<=d3)return b;
            double vc=d1*d4-d3*d2;if(vc<=0&&d1>=0&&d3<=0)return a+ab*(d1/(d1-d3));
            var cp=p-c;double d5=Vector3D.DotProduct(ab,cp),d6=Vector3D.DotProduct(ac,cp);if(d6>=0&&d5<=d6)return c;
            double vb=d5*d2-d1*d6;if(vb<=0&&d2>=0&&d6<=0)return a+ac*(d2/(d2-d6));
            double va=d3*d6-d5*d4;if(va<=0&&(d4-d3)>=0&&(d5-d6)>=0)return b+(c-b)*((d4-d3)/((d4-d3)+(d5-d6)));
            double sum=va+vb+vc;if(Math.Abs(sum)<1e-28)return a;
            return a+ab*(vb/sum)+ac*(vc/sum);
        }
        private void Nearest(Node node,Point3D p,ref double best,ref Point3D hit,ref Vector3D normal)
        {
            if(Distance(node.Bounds,p)>best)return;
            if(node.A!=null)
            {
                var first=node.A;var second=node.B;if(Distance(first.Bounds,p)>Distance(second.Bounds,p)){first=node.B;second=node.A;}
                Nearest(first,p,ref best,ref hit,ref normal);Nearest(second,p,ref best,ref hit,ref normal);return;
            }
            for(int i=node.Start;i<node.Start+node.Count;i++)
            {
                int t=3*triangles[i];var a=source[t];var b=source[t+1];var c=source[t+2];var q=Closest(p,a,b,c);double d=(q-p).LengthSquared;
                if(d<best){best=d;hit=q;normal=Vector3D.CrossProduct(b-a,c-a);}
            }
        }
        internal Result Evaluate(uint[] volume,int n,double low,double cell,double scale,HullOptions options,CancellationToken token)
        {
            options.Validate();token.ThrowIfCancellationRequested();
            var min=new[]{n,n,n};var max=new[]{0,0,0};bool any=false;
            for(int z=0;z<n;z++)for(int y=0;y<n;y++)for(int x=0;x<n;x++)if(volume[x+n*(y+n*z)]!=0)
            {any=true;min[0]=Math.Min(min[0],x);min[1]=Math.Min(min[1],y);min[2]=Math.Min(min[2],z);max[0]=Math.Max(max[0],x+1);max[1]=Math.Max(max[1],y+1);max[2]=Math.Max(max[2],z+1);}
            if(!any)throw new System.IO.InvalidDataException("Approximate pruning volume is empty. Adjust alpha or inspect the prepared hull.");
            var lo=min.Select(v=>low+v*cell).ToArray();var hi=max.Select(v=>low+v*cell).ToArray();
            if(options.Symmetry){double extent=Math.Max(Math.Abs(lo[0]),Math.Abs(hi[0]));lo[0]=-extent;hi[0]=extent;}
            var dims=new[]{options.Width-1,options.Length-1,options.Height-1};
            var step=Enumerable.Range(0,3).Select(i=>(hi[i]-lo[i])/dims[i]).ToArray();
            int nx=dims[0],ny=dims[1],nz=dims[2];var retained=new bool[nx*ny*nz];
            // Conservatively map occupied proxy voxels onto the requested lattice.
            // Exterior flood fill follows the generator's pruning rule.
            for(int z=0;z<n;z++)for(int y=0;y<n;y++)for(int x=0;x<n;x++)
            {
                if(volume[x+n*(y+n*z)]==0)continue;var p=new[]{x,y,z};var first=new int[3];var last=new int[3];
                for(int a=0;a<3;a++){first[a]=Math.Max(0,Math.Min(dims[a]-1,(int)Math.Floor((low+p[a]*cell-lo[a])/step[a]-1e-6)));last[a]=Math.Max(0,Math.Min(dims[a]-1,(int)Math.Floor((low+(p[a]+1)*cell-lo[a])/step[a]+1e-6)));}
                for(int k=first[2];k<=last[2];k++)for(int j=first[1];j<=last[1];j++)for(int i=first[0];i<=last[0];i++)retained[i+nx*(j+ny*k)]=true;
            }
            var outside=new bool[retained.Length];var queue=new Queue<int>();
            Action<int> enqueue=i=>{if(!retained[i]&&!outside[i]){outside[i]=true;queue.Enqueue(i);}};
            for(int z=0;z<nz;z++)for(int y=0;y<ny;y++)for(int x=0;x<nx;x++)if(x==0||y==0||z==0||x==nx-1||y==ny-1||z==nz-1)enqueue(x+nx*(y+ny*z));
            while(queue.Count>0)
            {
                token.ThrowIfCancellationRequested();int i=queue.Dequeue(),x=i%nx,y=(i/nx)%ny,z=i/(nx*ny);
                if(x>0)enqueue(i-1);if(x<nx-1)enqueue(i+1);if(y>0)enqueue(i-nx);if(y<ny-1)enqueue(i+nx);if(z>0)enqueue(i-nx*ny);if(z<nz-1)enqueue(i+nx*ny);
            }
            for(int i=0;i<retained.Length;i++)retained[i]=!outside[i];
            var points=new List<Point3D>();var quads=new List<int[]>();var lattice=new Dictionary<int,int>();
            Func<int,int,int,int> vertex=(x,y,z)=>{
                int key=x+(nx+1)*(y+(ny+1)*z),index;if(lattice.TryGetValue(key,out index))return index;
                token.ThrowIfCancellationRequested();var p=new Point3D(lo[0]+x*step[0],lo[1]+y*step[1],lo[2]+z*step[2]);var q=p;var normal=new Vector3D();double best=double.MaxValue;
                Nearest(root,p,ref best,ref q,ref normal);var direction=p-q;if(direction.LengthSquared<1e-24)direction=normal;
                if(direction.LengthSquared>1e-24){direction.Normalize();q+=direction*(options.Offset/scale);}
                index=points.Count;points.Add(q);lattice.Add(key,index);return index;
            };
            for(int z=0;z<nz;z++)for(int y=0;y<ny;y++)for(int x=0;x<nx;x++)
            {
                if(!retained[x+nx*(y+ny*z)])continue;var p=new[]{x,y,z};
                for(int axis=0;axis<3;axis++)for(int side=0;side<2;side++)
                {
                    var neighbor=(int[])p.Clone();neighbor[axis]+=side==0?-1:1;
                    if(neighbor[axis]>=0&&neighbor[axis]<dims[axis]&&retained[neighbor[0]+nx*(neighbor[1]+ny*neighbor[2])])continue;
                    var face=new int[4];for(int k=0;k<4;k++){var v=(int[])p.Clone();v[axis]+=side;v[(axis+1)%3]+=k==1||k==2?1:0;v[(axis+2)%3]+=k>=2?1:0;face[k]=vertex(v[0],v[1],v[2]);}if(side==0)Array.Reverse(face);quads.Add(face);
                }
            }
            if(options.Symmetry)
            {
                // Bisect projected polygons first, then mirror the selected half.
                var clipped=new List<int[]>();double sign=options.SymmetryBisectFlip?-1:1;
                foreach(var face in quads)
                {
                    token.ThrowIfCancellationRequested();var polygon=new List<int>();
                    for(int k=0;k<face.Length;k++)
                    {
                        int ai=face[k],bi=face[(k+1)%face.Length];var a=points[ai];var b=points[bi];bool ia=sign*a.X>=0,ib=sign*b.X>=0;
                        if(ia)polygon.Add(ai);
                        if(ia!=ib){double t=-a.X/(b.X-a.X);var q=a+(b-a)*t;q.X=0;polygon.Add(points.Count);points.Add(q);}
                    }
                    if(polygon.Count<3)continue;clipped.Add(polygon.ToArray());var mirrored=new int[polygon.Count];
                    for(int k=0;k<polygon.Count;k++){var p=points[polygon[k]];p.X=-p.X;mirrored[polygon.Count-1-k]=points.Count;points.Add(p);}clipped.Add(mirrored);
                }
                quads=clipped;
                double seam=options.SymmetryMergeDistance/scale;
                for(int i=0;i<points.Count;i++)if(Math.Abs(points[i].X)<=seam){var p=points[i];p.X=0;points[i]=p;}
            }
            // Deterministic representative merge; Blender's centroid/weld choices can differ.
            double weld=Math.Max(1e-9,options.Weld/scale);var merged=new List<Point3D>();var map=new int[points.Count];var buckets=new Dictionary<Tuple<long,long,long>,List<int>>();
            for(int i=0;i<points.Count;i++)
            {
                token.ThrowIfCancellationRequested();var p=points[i];long x=(long)Math.Floor(p.X/weld),y=(long)Math.Floor(p.Y/weld),z=(long)Math.Floor(p.Z/weld);int found=-1;
                for(int a=-1;a<=1;a++)for(int b=-1;b<=1;b++)for(int c=-1;c<=1;c++)
                {List<int> entries;if(!buckets.TryGetValue(Tuple.Create(x+a,y+b,z+c),out entries))continue;foreach(int candidate in entries)if((merged[candidate]-p).LengthSquared<=weld*weld&&(found<0||candidate<found))found=candidate;}
                if(found<0){found=merged.Count;merged.Add(p);var key=Tuple.Create(x,y,z);List<int> entries;if(!buckets.TryGetValue(key,out entries))buckets[key]=entries=new List<int>();entries.Add(found);}map[i]=found;
            }
            var edges=new HashSet<long>();int faces=0;var indices=new List<int>();var unique=new HashSet<string>();
            Action<int,int> edge=(a,b)=>{if(a!=b)edges.Add(((long)Math.Min(a,b)<<32)|(uint)Math.Max(a,b));};
            foreach(var polygon in quads)
            {
                var face=polygon.Select(i=>map[i]).ToList();for(int k=face.Count-1;k>=0;k--)if(face[k]==face[(k+1)%face.Count])face.RemoveAt(k);
                if(face.Distinct().Count()<3)continue;
                for(int k=1;k<face.Count-1;k++){int a=face[0],b=face[k],c=face[k+1];if(Vector3D.CrossProduct(merged[b]-merged[a],merged[c]-merged[a]).LengthSquared<1e-24)continue;var key=new[]{a,b,c};Array.Sort(key);if(!unique.Add(string.Join(",",key)))continue;edge(a,b);edge(b,c);edge(c,a);indices.AddRange(new[]{a,b,c});faces++;}
            }
            var lines=new float[edges.Count*8];int at=0;foreach(long key in edges.OrderBy(k=>k))foreach(int index in new[]{(int)(key>>32),(int)(key&uint.MaxValue)})
            {var p=merged[index];lines[at++]=(float)p.X;lines[at++]=(float)p.Y;lines[at++]=(float)p.Z;lines[at++]=1;}
            return new Result {Lines=lines,Points=edges.SelectMany(k=>new[]{(int)(k>>32),(int)(k&uint.MaxValue)}).Distinct().Select(i=>merged[i]).ToArray(),Faces=faces,Surface=new PreviewSurface(merged.ToArray(),indices.ToArray())};
        }
    }
}
