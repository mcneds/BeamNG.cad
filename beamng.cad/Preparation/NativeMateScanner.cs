using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    // Snapshot extraction stays on SolidWorks' STA. Analysis receives managed data.
    internal sealed class NativeMateScanner
    {
        private readonly ISldWorks app;
        private readonly ModelDoc2 model;
        private readonly VehicleProject project;
        private readonly Dictionary<string,Component2> tracedOwners=new Dictionary<string,Component2>();
        public NativeMateScanner(ISldWorks app,ModelDoc2 model,VehicleProject project){this.app=app;this.model=model;this.project=project;}
        private static string Reference(ModelDoc2 doc,object entity)
        {
            if(entity==null)return null;
            var bytes=doc.Extension.GetPersistReference3(entity) as byte[];
            return bytes?.Length>0?Convert.ToBase64String(bytes):null;
        }
        private static string Hash(string value)
        {using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value))).Replace("-","").ToLowerInvariant();}
        private static string GeometryKind(object value)
        {
            // ReferenceType2 is a selection-type enum, not swMateEntityTypes_e.
            // Inspect the actual geometry; casting the enum mislabels a vertex
            // as a plane and both plane/cylinder faces as a line.
            if(value is Feature feature)value=feature.GetSpecificFeature2();
            if(value is Vertex||value is RefPoint||value is SketchPoint)return "point";
            if(value is RefAxis)return "line";
            if(value is RefPlane)return "plane";
            if(value is Face2 face)
            {
                var surface=(Surface)face.GetSurface();
                if(surface.IsPlane())return "plane";
                if(surface.IsCylinder())return "cylinder";
                if(surface.IsSphere())return "sphere";
                if(surface.IsCone())return "cone";
            }
            if(value is Edge edge)
            {
                var curve=(Curve)edge.GetCurve();
                if(curve.IsCircle())return "circle";
                if(curve.IsLine())return "line";
            }
            return "unsupported";
        }
        private Component2 TraceOwner(object geometry)
        {
            var initial=Reference(model,geometry);if(initial!=null&&tracedOwners.TryGetValue(initial,out var cached))return cached;
            var queue=new Queue<object>();queue.Enqueue(geometry);var seen=new HashSet<string>();var found=new Dictionary<string,Component2>();
            var groundedSketch=false;var unownedComponent=false;
            for(var count=0;queue.Count>0&&count<256;count++)
            {
                var item=queue.Dequeue();if(item==null)continue;var key=Reference(model,item);if(key!=null&&!seen.Add(key))continue;
                var featureItem=item as Feature;
                // MateGroup is a solver dependency, not geometric ownership.
                // Walking it visits every mate and creates false ambiguity.
                if(featureItem?.GetTypeName2()=="MateGroup")continue;
                var specific=featureItem?.GetSpecificFeature2();
                var native=item as Entity;var owner=item as Component2??specific as Component2??native?.GetComponent() as Component2;
                if(owner!=null&&project.Components.Any(c=>c.Selections.Any(s=>s.ComponentReference==Reference(model,owner)))){found[Reference(model,owner)]=owner;continue;}
                if(owner!=null){unownedComponent=true;continue;}
                object[] relations=null;
                Sketch sketch=specific as Sketch;
                if(item is SketchPoint point){relations=point.GetRelations() as object[];sketch=point.GetSketch();}
                else if(item is SketchSegment segment){relations=segment.GetRelations() as object[];sketch=segment.GetSketch();}
                if(relations!=null)foreach(SketchRelation relation in relations)
                    foreach(var entity in (relation.GetDefinitionEntities2() as object[]??Array.Empty<object>()).Concat(relation.GetEntities() as object[]??Array.Empty<object>()))queue.Enqueue(entity);
                if(sketch!=null)
                {
                    groundedSketch|=sketch.GetConstrainedStatus()==(int)swConstrainedStatus_e.swFullyConstrained;
                    if(sketch is Feature sketchFeature)queue.Enqueue(sketchFeature);
                }
                if(item is Feature feature)
                {
                    var data=feature.GetDefinition();object[] selections=null;
                    if(data is RefPointFeatureData pointData)selections=pointData.Selections as object[];
                    else if(data is RefPlaneFeatureData planeData)selections=planeData.Selections as object[];
                    else if(data is RefAxisFeatureData axisData){object kinds;selections=axisData.GetSelections(out kinds) as object[];}
                    foreach(var selected in selections??Array.Empty<object>())queue.Enqueue(selected);
                    foreach(var parent in feature.GetParents() as object[]??Array.Empty<object>())queue.Enqueue(parent);
                    // AccessSelections enters rollback/edit state even for a
                    // getter. Never use it during inference in a user's document.
                }
            }
            // A truncated dependency graph is ambiguous even if one owner was found.
            Component2 result=null;
            if(queue.Count==0&&!unownedComponent&&found.Count==1)result=found.Values.Single();
            else if(queue.Count==0&&!unownedComponent&&found.Count==0&&groundedSketch)
            {
                // Fully constrained assembly helper sketches describe assembly
                // ground. Only a unique fixed physical frame can represent it.
                var frames=project.Components.Where(c=>c.MvpRole=="frame").ToArray();
                if(frames.Length==1)
                {
                    var instances=(((AssemblyDoc)model).GetComponents(false) as object[]??Array.Empty<object>()).Cast<Component2>();
                    var hosts=instances.Where(c=>c.IsFixed()&&frames[0].Selections.Any(s=>s.ComponentReference==Reference(model,c))).ToArray();
                    if(hosts.Length==1)result=hosts[0];
                }
            }
            if(initial!=null)tracedOwners[initial]=result;return result;
        }
        private double[] Map(double[] input,MathTransform transform,bool vector)
        {
            var xyz=input.Take(3).ToArray();var math=(MathUtility)app.GetMathUtility();
            if(transform!=null)
                xyz=vector?(double[])((MathVector)((MathVector)math.CreateVector(xyz)).MultiplyTransform(transform)).ArrayData:
                    (double[])((MathPoint)((MathPoint)math.CreatePoint(xyz)).MultiplyTransform(transform)).ArrayData;
            return AxisMapping.Matrix(AxisMapping.Standard).Select(row=>row.Zip(xyz,(a,b)=>a*b).Sum()).ToArray();
        }
        private double[][] AxisSites(object geometry,Component2 component,MathTransform placement,double[] point,double[] axis)
        {
            if(geometry is Feature feature)geometry=feature.GetSpecificFeature2();
            if(!(geometry is RefAxis reference))return null;
            var ends=reference.GetRefAxisParams() as double[];if(ends==null||ends.Length!=6||axis==null)return null;
            var norm=axis.Sum(x=>x*x);if(norm<1e-12)return null;
            foreach(var transform in new[]{placement,component?.Transform2})
            {
                var sites=new[]{Map(ends.Take(3).ToArray(),transform,false),Map(ends.Skip(3).ToArray(),transform,false)};
                if(sites.All(p=>{var delta=p.Zip(point,(a,b)=>a-b).ToArray();var t=delta.Zip(axis,(a,b)=>a*b).Sum()/norm;return Math.Sqrt(delta.Zip(axis,(a,b)=>(a-t*b)*(a-t*b)).Sum())<1e-5;}))return sites;
            }
            return null; // Never use coordinates that do not match the native mate axis.
        }
        private static IEnumerable<Feature> Children(Feature parent)
        {
            for(var child=parent.GetFirstSubFeature() as Feature;child!=null;child=child.GetNextSubFeature() as Feature)
            {yield return child;foreach(var nested in Children(child))yield return nested;}
        }
        public async Task<List<NativeMateRecord>> Capture(Action<string> progress,CancellationToken token)
        {
            if(!(model is AssemblyDoc assembly))throw new InvalidOperationException("Open the companion assembly to author native mates.");
            var start=model.GetUpdateStamp();var configuration=model.ConfigurationManager.ActiveConfiguration.Name;
            var instances=(assembly.GetComponents(false) as object[]??Array.Empty<object>()).Cast<Component2>().ToArray();
            var byName=instances.ToDictionary(c=>c.Name2);
            var placements=instances.Where(c=>!c.IsSuppressed()).Select(c=>{
                var reference=Reference(model,c);var owners=project.Components.Where(o=>o.Selections.Any(s=>s.ComponentReference==reference)).ToArray();
                return new NativePlacement {ComponentId=owners.Length==1?owners[0].Id:null,ComponentReference=reference,Fixed=c.IsFixed(),MemberId=project.JointWorkspace.Members.FirstOrDefault(m=>m.ComponentReference==reference)?.Id};
            }).Where(p=>p.ComponentId!=null).ToList();
            var contexts=new List<Tuple<ModelDoc2,Component2>> {Tuple.Create(model,(Component2)null)};
            foreach(var instance in instances.Where(c=>!c.IsSuppressed()))
                if(instance.GetModelDoc2() is ModelDoc2 document && document is AssemblyDoc)contexts.Add(Tuple.Create(document,instance));
            var result=new List<NativeMateRecord>();var seen=new HashSet<string>();
            foreach(var context in contexts)
            {
                var scope=context.Item1;var placement=context.Item2;
                for(var feature=scope.FirstFeature() as Feature;feature!=null;feature=feature.GetNextFeature() as Feature)
                {
                    token.ThrowIfCancellationRequested();
                    if(feature.GetTypeName2()!="MateGroup")continue;
                    foreach(var f in Children(feature))
                    {
                        token.ThrowIfCancellationRequested();
                        if(!(f.GetSpecificFeature2() is Mate2 mate))continue;
                        var reference=Reference(scope,f);var identity=Hash((placement?.Name2??"")+"|feature:"+f.GetID());
                        if(!seen.Add(identity))continue;
                        var record=new NativeMateRecord {Id=identity,Name=(placement==null?"":placement.Name2+" / ")+f.Name,
                            Reference=reference,Type=((swMateType_e)mate.Type).ToString().Replace("swMate",""),Suppressed=f.IsSuppressed()};
                        record.PositioningOnly=project.JointWorkspace.Mates.FirstOrDefault(m=>m.Id==identity)?.PositioningOnly??false;
                        try
                        {
                            var error=f.GetErrorCode2(out var warning);
                            if(error!=0&&!warning)throw new InvalidOperationException("Native mate is unsolved (SolidWorks error "+error+"). Rebuild and repair it before review.");
                            var definition=f.GetDefinition();
                            if(definition is ConcentricMateFeatureData concentric)record.LockRotation=concentric.LockRotation;
                            if(definition is DistanceMateFeatureData distance)
                            {
                                record.Value=distance.Distance;record.HasLimits=distance.IsAdvancedMate;
                                record.Minimum=distance.MinimumDistance;record.Maximum=distance.MaximumDistance;
                                if(record.HasLimits)record.Type="LIMITDISTANCE";
                            }
                            if(definition is AngleMateFeatureData angle)
                            {
                                record.Value=angle.Angle;record.HasLimits=angle.IsAdvancedMate;
                                record.Minimum=angle.MinimumAngle;record.Maximum=angle.MaximumAngle;
                                if(record.HasLimits)record.Type="LIMITANGLE";
                            }
                            for(var index=0;index<mate.GetMateEntityCount();index++)
                            {
                                var entity=mate.MateEntity(index);var component=entity.ReferenceComponent as Component2;
                                if(placement!=null && component!=null)byName.TryGetValue(placement.Name2+"/"+component.Name2,out component);
                                var componentRef=Reference(model,component);
                                var owners=project.Components.Where(c=>c.Selections.Any(s=>s.ComponentReference==componentRef||s.Kind=="component"&&s.Reference==componentRef)).ToArray();
                                if(owners.Length==0)
                                {
                                    var traced=TraceOwner(entity.Reference);
                                    if(traced!=null){component=traced;componentRef=Reference(model,traced);owners=project.Components.Where(c=>c.Selections.Any(s=>s.ComponentReference==componentRef)).ToArray();}
                                }
                                // Companion members have unambiguous instance ownership.
                                // Multi-group source parts need explicit reference capture.
                                if(owners.Length!=1)throw new InvalidOperationException("Importer could not resolve unique tagged ownership for this native mate reference ("+owners.Length+" groups). The CAD mate has not been changed.");
                                var parameters=(double[])entity.EntityParams;
                                if(parameters==null||parameters.Length<3)throw new InvalidOperationException("Native mate entity has no geometry parameters.");
                                var kind=GeometryKind(entity.Reference);
                                var member=project.JointWorkspace.Members.SingleOrDefault(m=>m.ComponentReference==componentRef);
                                var mappedPoint=Map(parameters,placement?.Transform2,false);
                                var mappedAxis=parameters.Length>=6?Map(parameters.Skip(3).ToArray(),placement?.Transform2,true):null;
                                record.Entities.Add(new NativeMateEntity {ComponentId=owners[0].Id,MemberId=member?.Id,
                                    ComponentReference=componentRef,Reference=Reference(scope,entity.Reference),Kind=kind,
                                    Point=mappedPoint,Axis=mappedAxis,AxisSites=AxisSites(entity.Reference,component,placement?.Transform2,mappedPoint,mappedAxis),
                                    Radius=parameters.Length>6?parameters[6]:0});
                            }
                        }
                        catch(Exception e){record.Issue=e.Message;}
                        result.Add(record);progress?.Invoke("Read native mate "+result.Count+": "+record.Name);
                        await Task.Yield();
                    }
                }
            }
            if(model.GetUpdateStamp()!=start || model.ConfigurationManager.ActiveConfiguration.Name!=configuration)
                throw new InvalidOperationException("CAD changed during mate scan. Scan again after the rebuild finishes.");
            project.JointWorkspace.Placements=placements;
            return result;
        }
    }
}
