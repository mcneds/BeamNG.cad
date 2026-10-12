using System;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.Preparation
{
    internal sealed class MountAnchors
    {
        private readonly ISldWorks app;
        private readonly ModelDoc2 model;
        public MountAnchors(ISldWorks app,ModelDoc2 model){this.app=app;this.model=model;}
        private string Reference(object item)
        {
            var bytes=model.Extension.GetPersistReference3(item) as byte[];
            if(bytes==null||bytes.Length==0)throw new InvalidOperationException("This geometry cannot supply a persistent mounting reference.");
            return Convert.ToBase64String(bytes);
        }
        private object Resolve(string reference)
        {
            int status;var item=model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out status);
            if(item==null||status!=0)throw new InvalidOperationException("Mount reference is missing or suppressed. Pick replacement geometry.");
            return item;
        }
        private static double[] Point(object item)
        {
            if(item is Vertex vertex)return ((double[])vertex.GetPoint()).Take(3).ToArray();
            if(item is Edge edge)
            {
                var curve=(Curve)edge.GetCurve();
                if(!curve.IsCircle())throw new InvalidOperationException("Choose a circular edge to use its center.");
                return ((double[])curve.CircleParams).Take(3).ToArray();
            }
            if(item is Feature feature)item=feature.GetSpecificFeature2();
            if(item is RefPoint point)return ((double[])((MathPoint)point.GetRefPoint()).ArrayData).Take(3).ToArray();
            if(item is SketchPoint sketchPoint)
            {
                if(!sketchPoint.GetSketch().Is3D())throw new InvalidOperationException("Use a 3D sketch point; 2D sketch coordinates require a sketch-plane transform.");
                return new[]{sketchPoint.X,sketchPoint.Y,sketchPoint.Z};
            }
            throw new InvalidOperationException("Select a vertex, reference point, 3D sketch point or circular edge; select two for a midpoint.");
        }
        private static bool Datum(object item)
        {
            if(item is Feature feature)item=feature.GetSpecificFeature2();
            return item is RefPoint||item is SketchPoint;
        }
        private static Body2 Body(object item)
        {
            if(item is Edge edge)return edge.GetBody();
            if(item is Vertex vertex)return ((object[])vertex.GetEdges()).Cast<Edge>().First().GetBody();
            return null; // Datum points are intentionally component-level references.
        }
        private string BodyReference(Component2 component,object item)
        {
            var body=Body(item);if(body==null)return null;
            // Edge.GetBody can return the part-context body even for an
            // assembly-context vertex. GetBodies3 supplies instance bodies
            // matching FrameSelection's persistent body identities.
            object info;var bodies=(object[])component.GetBodies3(-1,out info);
            var instance=(bodies??new object[0]).Cast<Body2>().SingleOrDefault(b=>b.Name==body.Name);
            if(instance==null)throw new InvalidOperationException("Mount body is unavailable in this component instance.");
            return Reference(instance);
        }
        public MountAnchor Capture(ComponentDefinition owner,string name)
        {
            var manager=(SelectionMgr)model.SelectionManager;var count=manager.GetSelectedObjectCount2(-1);
            if(count<1||count>2)throw new InvalidOperationException("Select one mounting point, or two points on the same CAD component for a midpoint.");
            var anchor=new MountAnchor {Name=name,ComponentId=owner.Id,Kind=count==2?"midpoint":"point"};
            for(var index=1;index<=count;index++)
            {
                var selected=manager.GetSelectedObject6(index,-1);Point(selected);
                var component=manager.GetSelectedObjectsComponent4(index,-1) as Component2;
                var space=component==null?"assembly":"component";
                if(component==null&&!Datum(selected))throw new InvalidOperationException("Choose component geometry or an assembly reference / 3D sketch point.");
                if(component==null&&owner.Selections.Count==0)throw new InvalidOperationException("Assign physical CAD to this group before giving it an assembly mounting point.");
                var reference=component==null?null:Reference(component);
                if(index>1 && (anchor.ComponentReference!=reference||anchor.CoordinateSpace!=space))throw new InvalidOperationException("Midpoint references must belong to the same CAD component or both be assembly datums.");
                anchor.CoordinateSpace=space;
                anchor.ComponentReference=reference;anchor.References.Add(Reference(selected));
                var bodyReference=component==null?null:BodyReference(component,selected);
                anchor.BodyReferences.Add(bodyReference);
                if(bodyReference!=null)
                {
                    string id;using(var hash=SHA256.Create())id="body_"+BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(reference+"|"+bodyReference))).Replace("-","").ToLowerInvariant().Substring(0,24);
                    if(!owner.BodyIds.Contains(id))throw new InvalidOperationException("Selected mounting geometry belongs to a body outside this component's assignment.");
                }
                if(component!=null&&owner.Selections.All(s=>s.ComponentReference!=reference && s.Reference!=reference))
                {
                    if(string.IsNullOrEmpty(owner.GeometryDirectory))throw new InvalidOperationException("Export the component geometry before choosing this nested mounting point.");
                    var geometry=JsonFile.Read<GeometryPackage>(System.IO.Path.Combine(owner.GeometryDirectory,"geometry.json"));
                    if(!geometry.Meshes.Any(m=>m.ComponentReference==reference))throw new InvalidOperationException("Selected mounting geometry belongs to a different component.");
                }
            }
            Update(anchor);return anchor;
        }
        public void Update(MountAnchor anchor)
        {
            // Generated sites are validated against exported geometry hashes by
            // the worker. They do not pretend to be native selected vertices.
            if(anchor.GeneratedSource=="auto_connect"||anchor.GeneratedSource=="joint_inference")
            {
                if(anchor.LocalPosition==null||anchor.LocalPosition.Length!=3)throw new InvalidOperationException("Generated point is missing its source position. Preview again.");
                var adjusted=anchor.LocalPosition.Zip(anchor.Offset,(a,b)=>a+b).ToArray();
                if(adjusted.Any(v=>double.IsNaN(v)||double.IsInfinity(v)))throw new InvalidOperationException("Mount offsets must be finite.");
                anchor.Position=AxisMapping.Matrix(AxisMapping.Standard).Select(row=>row.Zip(adjusted,(a,b)=>a*b).Sum()).ToArray();return;
            }
            try
            {
                var root=anchor.CoordinateSpace=="assembly";
                var component=root?null:Resolve(anchor.ComponentReference) as Component2;
                if(!root&&(component==null||component.IsSuppressed()))throw new InvalidOperationException("Mount component is unavailable.");
                if(anchor.References.Count<1||anchor.References.Count>2)throw new InvalidOperationException("Invalid mounting point references.");
                var entities=anchor.References.Select(Resolve).ToArray();
                if(root&&entities.Any(e=>!Datum(e)))throw new InvalidOperationException("Assembly mounts require datum points.");
                if(anchor.BodyReferences!=null && anchor.BodyReferences.Count==entities.Length)
                    for(var i=0;i<entities.Length;i++)
                        if(anchor.BodyReferences[i]!=null)
                        {
                            var current=BodyReference(component,entities[i]);
                            if(current==null||app.IsSame(Resolve(current),Resolve(anchor.BodyReferences[i]))!=(int)SolidWorks.Interop.swconst.swObjectEquality.swObjectSame)
                                throw new InvalidOperationException("Mount geometry now belongs to another body. Repair its reference.");
                            // Persistent reference bytes can change after a native
                            // rename/save even when they resolve to the same body.
                            anchor.BodyReferences[i]=current;
                        }
                var points=entities.Select(Point).ToArray();
                var center=Enumerable.Range(0,3).Select(i=>points.Average(p=>p[i])).ToArray();
                anchor.LocalPosition=center;
                var adjusted=center.Zip(anchor.Offset,(a,b)=>a+b).ToArray();
                if(adjusted.Any(v=>double.IsNaN(v)||double.IsInfinity(v)))throw new InvalidOperationException("Mount offsets must be finite.");
                var math=(MathUtility)app.GetMathUtility();var point=(MathPoint)math.CreatePoint(adjusted);
                if(component?.Transform2!=null)point=(MathPoint)point.MultiplyTransform(component.Transform2);
                var cad=(double[])point.ArrayData;var mapping=AxisMapping.Matrix(AxisMapping.Standard);
                anchor.Position=mapping.Select(row=>row.Zip(cad,(a,b)=>a*b).Sum()).ToArray();anchor.Status="resolved";
            }
            catch{anchor.Status="needs_repair";throw;}
        }
    }
}
