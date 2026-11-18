using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Media.Media3D;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.Preparation
{
    internal sealed partial class FrameSelection
    {
        // Display-only snapshot. No materials, mates, physical moments, fresh
        // tessellation, file writes or CAD edits are needed for this preview.
        public async Task<Point3D[]> CapturePreviewAsync(FrameAssignment frame, CancellationToken token,
            Action<string> progress)
        {
            Validate(frame);
            var stamp=model.GetUpdateStamp();
            var configuration=Configuration;
            var bodies=SnapshotBodies(frame);
            var points=new List<Point3D>();
            var math=(MathUtility)app.GetMathUtility();
            var elapsed=Stopwatch.StartNew();
            int completed=0;
            foreach(var pair in bodies)
            {
                token.ThrowIfCancellationRequested();Validate(frame);
                var transform=pair.Item1.Transform2;
                Func<double[],double[]> map=p=>{
                    var point=(MathPoint)math.CreatePoint(p);
                    if(transform!=null)point=(MathPoint)point.MultiplyTransform(transform);
                    return (double[])point.ArrayData;
                };
                var origin=map(new double[3]);
                var basis=Enumerable.Range(0,3).Select(i=>{
                    var p=new double[3];p[i]=1;return map(p).Zip(origin,(a,b)=>a-b).ToArray();
                }).ToArray();
                foreach(Face2 face in pair.Item2.GetFaces() as object[]??Array.Empty<object>())
                {
                    token.ThrowIfCancellationRequested();
                    var data=face.GetTessTriangles(true) as float[];
                    if(data==null||data.Length==0||data.Length%9!=0)
                        throw new InvalidOperationException("Display tessellation unavailable for "+pair.Item2.Name+". Resolve/show the selected CAD and refresh the live preview.");
                    // Preserve all triangles up to a hard memory limit. Omitting
                    // arbitrary triangles could silently hide entire thin members.
                    if(points.Count/3+data.Length/9>PreviewGeometry.MaxSourceTriangles)
                        throw new InvalidOperationException("Display geometry exceeds the live preview budget. Reduce CAD display tessellation or preview a smaller selection; full preparation remains available.");
                    var mapped=await Task.Run(()=>{
                        var result=new Point3D[data.Length/3];
                        for(int i=0;i<result.Length;i++)
                        {
                            if(i%1024==0)token.ThrowIfCancellationRequested();
                            double x=data[3*i],y=data[3*i+1],z=data[3*i+2];
                            result[i]=new Point3D(origin[0]+x*basis[0][0]+y*basis[1][0]+z*basis[2][0],
                                origin[1]+x*basis[0][1]+y*basis[1][1]+z*basis[2][1],
                                origin[2]+x*basis[0][2]+y*basis[1][2]+z*basis[2][2]);
                        }
                        return result;
                    },token);
                    points.AddRange(mapped);
                    if(elapsed.ElapsedMilliseconds>=12){await Task.Delay(1,token);elapsed.Restart();}
                }
                progress?.Invoke("Display geometry: "+(++completed)+" / "+bodies.Count+" bodies");
            }
            token.ThrowIfCancellationRequested();Validate(frame);
            if(Configuration!=configuration||model.GetUpdateStamp()!=stamp)
                throw new InvalidOperationException("CAD changed during preview capture. Refresh the live preview.");
            if(points.Count==0)throw new InvalidOperationException("No display triangles in the saved frame selection.");
            return points.ToArray();
        }
    }
}
