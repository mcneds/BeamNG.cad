using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
namespace BeamNG.Cad.Preparation
{
    internal sealed partial class FrameSelection
    {
        private readonly ISldWorks app;
        private readonly ModelDoc2 model;
        private readonly bool allowSurfaceBodies;
        public FrameSelection(ISldWorks app, ModelDoc2 model):this(app,model,false){}
        public FrameSelection(ISldWorks app, ModelDoc2 model,bool allowSurfaceBodies) { this.app = app; this.model = model;this.allowSurfaceBodies=allowSurfaceBodies; }
        public string Configuration => model.ConfigurationManager.ActiveConfiguration.Name;
        public string Document => model.GetPathName();
        public void ValidateDocument()
        {
            try
            {
                // Check native identity before dereferencing a possibly closed document.
                var active=app.ActiveDoc;
                if (active == null || app.IsSame(active, model) != (int)swObjectEquality.swObjectSame)
                    throw new InvalidOperationException("Activate the assembly used by this frame editor. If it was reopened, return to Frame to reload its CAD context.");
                if (model.GetType() != (int)swDocumentTypes_e.swDocASSEMBLY || string.IsNullOrEmpty(Document))
                    throw new InvalidOperationException("Open and save the top-level assembly first.");
            }
            catch(System.Runtime.InteropServices.COMException error) when(error.ErrorCode==unchecked((int)0x80010108))
            {
                throw new InvalidOperationException("The CAD document was closed or replaced. Activate the saved source assembly and refresh the frame preview.",error);
            }
        }
        private string Reference(object item)
        {
            var bytes = model.Extension.GetPersistReference3(item) as byte[];
            if (bytes == null || bytes.Length == 0) throw new InvalidOperationException("SolidWorks could not create a durable reference for this selection.");
            return Convert.ToBase64String(bytes);
        }
        private object Resolve(string reference)
        {
            int status;
            var item = model.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference), out status);
            if(status==(int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Suppressed)
                throw new InvalidOperationException("Saved selection is genuinely suppressed in this configuration. Unsuppress it explicitly in SolidWorks or replace the saved selection.");
            if (item == null || status != 0) throw new InvalidOperationException("A saved frame reference is missing or unavailable (status " + status + "). Replace the frame selection.");
            return item;
        }
        public FrameAssignment Capture()=>CaptureScope(false);
        public GeometryPackage ExportDisplay(FrameAssignment frame,string folder)
        {
            Validate(frame);var stamp=model.GetUpdateStamp();var dirty=model.GetSaveFlag();
            List<Tuple<Component2,Body2>> bodies;using(var saved=new SelectionSnapshot(model))bodies=Expand(frame);
            var materials=ReadMaterials(frame);var math=(MathUtility)app.GetMathUtility();
            var appearanceScene=new SolidWorksAppearances.Scene(model);
            var package=new GeometryPackage {SourceDocument=Document,Configuration=Configuration,Assignment=frame};
            Directory.CreateDirectory(folder);
            foreach(var pair in bodies){
                var component=pair.Item1;var body=pair.Item2;var id=BodyId(component,body);var properties=(double[])body.GetMassProperties(1);var transform=component.Transform2;
                var material=materials.Bodies.Single(v=>v.BodyId==id);var surface=body.GetType()==(int)swBodyType_e.swSheetBody;
                var point=(MathPoint)math.CreatePoint(properties.Take(3).ToArray());if(transform!=null)point=(MathPoint)point.MultiplyTransform(transform);
                var axes=Enumerable.Range(0,3).Select(i=>{var p=new double[3];p[i]=1;var vector=(MathVector)math.CreateVector(p);if(transform!=null)vector=(MathVector)vector.MultiplyTransform(transform);return (double[])vector.ArrayData;}).ToArray();
                var record=new MeshRecord {Id=id,File=id+".stl",Component=component.Name2,Body=body.Name,SourceDocument=component.GetPathName(),Configuration=component.ReferencedConfiguration,
                    ComponentReference=Reference(component),BodyReference=Reference(body),MassKg=surface?null:material.Density*properties[3],MassSource="Native CAD volume times captured SolidWorks material density",
                    BodyKind=surface?"surface":"solid",SurfaceAreaM2=surface?(double?)properties[3]:null,DensityKgM3=material.Density,
                    NativeUnitDensityProperties=properties,NativeCenterAssembly=(double[])point.ArrayData,NativeAxesAssembly=axes,TessellationSource="SolidWorks display tessellation; native CAD physical moments"};
                try {record.AppearanceGroups=StlAssemblyExporter.ExportDisplayBodyWithAppearance(app,component,body,Path.Combine(folder,record.File),transform,appearanceScene);}
                catch(InvalidOperationException error) when(error.Message.StartsWith("Display tessellation unavailable",StringComparison.Ordinal)){
                    record.AppearanceGroups=StlAssemblyExporter.ExportSelectedBodyWithAppearance(app,component,body,Path.Combine(folder,record.File),transform,appearanceScene);
                    record.TessellationSource="Fresh body tessellation; native CAD physical moments";
                }
                package.Meshes.Add(record);
            }
            Validate(frame);if(model.GetUpdateStamp()!=stamp||model.GetSaveFlag()!=dirty||materials.Fingerprint()!=ReadMaterials(frame).Fingerprint())throw new InvalidOperationException("CAD changed during display capture");
            JsonFile.Write(Path.Combine(folder,"geometry.json"),package);JsonFile.Write(Path.Combine(folder,"material-snapshot.json"),materials);return package;
        }
        public FrameAssignment CaptureOwningComponents()=>CaptureScope(true);
        private FrameAssignment CaptureScope(bool wholeComponents)
        {
            ValidateDocument();
            using(var preserved=new SelectionSnapshot(model))
            {
                var normalizer=new SelectionNormalizer(model);
                var frame=allowSurfaceBodies?normalizer.CaptureComponentGeometry(wholeComponents):normalizer.Capture();
                // Explicit selection actions load only the chosen scope, including
                // lightweight children of a selected subassembly. Refresh stays read-only.
                Expand(frame);
                return frame;
            }
        }
        public void Show(FrameAssignment frame)
        {
            Validate(frame);
            // Resolve and check the complete group before touching the user's
            // selection. Never show a partial group as if it were complete.
            var normalizer=new SelectionNormalizer(model);
            var loaded=new HashSet<string>();
            var items=frame.Selections.Select(s=>
            {
                try
                {
                    // A persisted body cannot resolve until its owning nested
                    // component is loaded. Export already follows this order.
                    var owner=s.Kind=="component"?s.Reference:s.ComponentReference;
                    if(!string.IsNullOrEmpty(owner)&&loaded.Add(owner))normalizer.Available((Component2)Resolve(owner),true);
                    var item=Resolve(s.Reference);
                    if(!((s.Kind=="component" && item is Component2) || (s.Kind=="body" && item is Body2)))
                        throw new InvalidOperationException("Saved selection changed type. Repair this group's CAD assignment.");
                    return item;
                }
                catch(Exception e){throw new InvalidOperationException(s.Name+": "+e.Message,e);}
            }).ToArray();
            var previous=new SelectionSnapshot(model);
            try
            {
                model.ClearSelection2(true);
                var data=((SelectionMgr)model.SelectionManager).CreateSelectData();data.Mark=0;
                for(var i=0;i<items.Length;i++)
                {
                    var selected=items[i] is Component2 component ? component.Select4(true,data,false)
                        : items[i] is Body2 body && body.Select2(true,data);
                    if(!selected)throw new InvalidOperationException(frame.Selections[i].Name+": saved geometry could not be highlighted. Resolve/show the component or repair its saved assignment.");
                }
            }
            catch{previous.Dispose();throw;}
        }
        private void Validate(FrameAssignment frame)
        {
            ValidateDocument();
            if (frame == null || frame.Selections.Count == 0) throw new InvalidOperationException("Define the frame selection first.");
            if (frame.Configuration != Configuration) throw new InvalidOperationException("The active configuration changed. Reopen the frame workflow for this configuration.");
        }
        private IEnumerable<Tuple<Component2, Body2>> Bodies(Component2 component)
            => AvailableBodies(component,true);
        private IEnumerable<Tuple<Component2, Body2>> AvailableBodies(Component2 component,bool load)
        {
            component=new SelectionNormalizer(model).Available(component,load);
            var children = component.GetChildren() as object[];
            if (children != null && children.Length > 0)
            {
                foreach (Component2 child in children)
                {
                    // An explicitly selected suppressed component still fails above.
                    if(child.GetSuppression2()==(int)swComponentSuppressionState_e.swComponentSuppressed)continue;
                    foreach (var body in AvailableBodies(child,load)) yield return body;
                }
                yield break;
            }
            if (!(component.GetModelDoc2() is ModelDoc2 part)) throw new InvalidOperationException("Resolve the lightweight/unavailable component: " + component.Name2);
            if (!(part is PartDoc)) throw new InvalidOperationException("Selected component has no available part geometry: " + component.Name2);
            // Component bodies respect instance configuration and assembly features without changing a document configuration.
            object info;
            var bodies = component.GetBodies3((int)swBodyType_e.swAllBodies, out info) as object[];
            if (bodies == null || bodies.Length == 0) throw new InvalidOperationException("No available bodies: " + component.Name2+
                " in configuration '"+component.ReferencedConfiguration+"'. Geometry assignments require solid or surface bodies; reference planes, axes and sketches do not count. Deselect this component or check its configuration. The saved assignment has not changed.");
            foreach (Body2 body in bodies)
            {
                if(body.GetType()!=(int)swBodyType_e.swSolidBody && (!allowSurfaceBodies||body.GetType()!=(int)swBodyType_e.swSheetBody))
                    throw new InvalidOperationException(component.Name2+" / "+body.Name+": "+(allowSurfaceBodies?"Only solid and surface bodies are supported.":"The frame requires solid bodies. Assign surface panels in Components / mounts."));
                yield return Tuple.Create(component, body);
            }
        }
        private List<Tuple<Component2, Body2>> Expand(FrameAssignment frame)
            => ExpandAvailable(frame,true);
        // Explicit snapshot action; includes surfaces and preserves the caller's selection.
        public List<Tuple<Component2,Body2>> SnapshotBodies(FrameAssignment frame)
        {
            using(var preserved=new SelectionSnapshot(model))return Expand(frame);
        }
        private List<Tuple<Component2, Body2>> ExpandAvailable(FrameAssignment frame,bool load)
        {
            Validate(frame);
            var bodies = new List<Tuple<Component2, Body2>>();
            foreach (var selection in frame.Selections)
            {
                try
                {
                    if (selection.Kind == "component") bodies.AddRange(AvailableBodies((Component2)Resolve(selection.Reference),load));
                    else if (selection.Kind == "body")
                    {
                        var component = new SelectionNormalizer(model).Available((Component2)Resolve(selection.ComponentReference),load);
                        bodies.Add(Tuple.Create(component, (Body2)Resolve(selection.Reference)));
                    }
                    else throw new InvalidDataException("Unsupported selection kind.");
                }
                catch (Exception e) { throw new InvalidOperationException(selection.Name + ": " + e.Message, e); }
            }
            var unique = new List<Tuple<Component2, Body2>>();
            var identities = new HashSet<string>();
            foreach (var pair in bodies)
                if (identities.Add(Reference(pair.Item1) + "|" + Reference(pair.Item2))) unique.Add(pair);
            return unique;
        }
        public string Summary(FrameAssignment frame)
        {
            var bodies = ExpandAvailable(frame,false);
            return bodies.Count + " bodies in " + bodies.Select(b => b.Item1.Name2).Distinct().Count() + " component instances\r\n"
                + string.Join("\r\n", bodies.Select(b => b.Item1.Name2 + " / " + b.Item2.Name));
        }
        public GeometryPackage Export(FrameAssignment frame, string folder)
            => ExportAsync(frame, folder, CancellationToken.None, false).GetAwaiter().GetResult();
        public List<string> BodyIds(FrameAssignment frame)
        {using(var preserved=new SelectionSnapshot(model))return Expand(frame).Select(p=>BodyId(p.Item1,p.Item2)).Distinct().ToList();}
        private string BodyId(Component2 component,Body2 body)
        {
            using(var hash=SHA256.Create())return "body_"+BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Reference(component)+"|"+Reference(body)))).Replace("-","").ToLowerInvariant().Substring(0,24);
        }
        public MaterialSnapshot ReadMaterials(FrameAssignment frame)
        {
            var reader=new SolidWorksMaterials(app);var snapshot=new MaterialSnapshot();
            foreach(var pair in ExpandAvailable(frame,false))snapshot.Bodies.Add(reader.Read(pair.Item1,pair.Item2,BodyId(pair.Item1,pair.Item2)));
            return snapshot;
        }
        public List<Tuple<Component2, Body2>> MaterialBodies(FrameAssignment savedFrame)
        {
            ValidateDocument();
            using(var preserved=new SelectionSnapshot(model))
            {
                if(savedFrame==null)savedFrame=Capture();
                var expanded=Expand(savedFrame);
                foreach(var pair in expanded)
                    if(pair.Item2.GetType()!=(int)swBodyType_e.swSolidBody && savedFrame.Selections.Any(s=>s.Kind=="body" && s.Reference==Reference(pair.Item2)))
                        throw new InvalidOperationException("Material assignment requires solid bodies: "+pair.Item2.Name);
                return expanded.Where(p=>p.Item2.GetType()==(int)swBodyType_e.swSolidBody).ToList();
            }
        }
        public void EditSelectedMaterials()
        {
            ValidateDocument();
            var manager=(SelectionMgr)model.SelectionManager;
            if(manager.GetSelectedObjectCount2(-1)==0)throw new InvalidOperationException("Select bodies or part components in SolidWorks first");
            for(var i=1;i<=manager.GetSelectedObjectCount2(-1);i++)
                if(!(manager.GetSelectedObject6(i,-1) is Body2) && !(manager.GetSelectedObject6(i,-1) is Component2))
                    throw new InvalidOperationException("Select bodies or part components to edit their native materials");
            // swCommands_EditMaterial. The native dialog owns selection scope,
            // Apply/Cancel and the shared-part semantics; this code sets no material.
            if(!app.RunCommand(501,""))throw new InvalidOperationException("SolidWorks could not open Edit Material for this selection. Use its Material > Edit Material context menu.");
        }
        public async Task<GeometryPackage> ExportAsync(FrameAssignment frame, string folder, CancellationToken token, bool yield = true)
        {
            token.ThrowIfCancellationRequested();
            List<Tuple<Component2,Body2>> bodies;
            using(var preserved=new SelectionSnapshot(model))bodies=Expand(frame);
            var version = model.GetUpdateStamp();
            Directory.CreateDirectory(folder);
            var package = new GeometryPackage { SourceDocument = Document, Configuration = Configuration, Assignment = frame };
            var materialSnapshot=ReadMaterials(frame);
            var appearanceScene=new SolidWorksAppearances.Scene(model);
            var sourceLookup=new Dictionary<Tuple<ModelDoc2,string>,ILookup<string,Body2>>();
            foreach (var pair in bodies)
            {
                token.ThrowIfCancellationRequested(); Validate(frame);
                if (model.GetUpdateStamp() != version) throw new InvalidOperationException("Assembly changed during export. Prepare again.");
                var component = pair.Item1; var body = pair.Item2;
                var componentRef = Reference(component); var bodyRef = Reference(body);
                string id;
                using (var hash = SHA256.Create()) id = "body_" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(componentRef + "|" + bodyRef))).Replace("-", "").ToLowerInvariant().Substring(0, 24);
                var record = new MeshRecord { Id = id, File = id + ".stl", Component = component.Name2, Body = body.Name,
                    SourceDocument = component.GetPathName(), Configuration = component.ReferencedConfiguration,
                    ComponentReference = componentRef, BodyReference = bodyRef };
                record.AppearanceGroups=StlAssemblyExporter.ExportSelectedBodyWithAppearance(app,component,body,Path.Combine(folder,record.File),component.Transform2,appearanceScene);
                if(body.GetType()==(int)swBodyType_e.swSheetBody)
                {
                    if(!allowSurfaceBodies)throw new InvalidOperationException("Surface bodies require the component workflow");
                    record.BodyKind="surface";
                    record.SurfaceAreaM2=((double[])body.GetMassProperties(1))[3];
                    record.DensityKgM3=materialSnapshot.Bodies.Single(m=>m.BodyId==id).Density;
                    record.MassSource="Surface body: weight is determined by the component's surface thickness/mass setting";
                    package.Meshes.Add(record);
                    if(yield)await Task.Delay(1,token);
                    continue;
                }
                try
                {
                    // Resolve the part body so its own material/density is used.
                    // Component bodies do not always support GetCorresponding2.
                    var sourceModel = (ModelDoc2)component.GetModelDoc2();
                    if (sourceModel.ConfigurationManager.ActiveConfiguration.Name != component.ReferencedConfiguration)
                        throw new InvalidOperationException("Referenced part configuration is not active");
                    var key=Tuple.Create(sourceModel,component.ReferencedConfiguration);
                    if(!sourceLookup.TryGetValue(key,out var lookup)){
                        lookup=(((PartDoc)sourceModel).GetBodies2((int)swBodyType_e.swSolidBody,false) as object[]??Array.Empty<object>()).Cast<Body2>().ToLookup(b=>b.Name);sourceLookup.Add(key,lookup);
                    }
                    var sourceBody=lookup[body.Name].SingleOrDefault();
                    if (sourceBody == null) throw new InvalidOperationException("Body has no part-context counterpart");
                    var mass = (MassProperty2)sourceModel.Extension.CreateMassProperty2();
                    mass.UseSystemUnits = true;
                    // The API requires IDispatch, not an array of COM IUnknowns.
                    mass.SelectedItems = new[] { new System.Runtime.InteropServices.DispatchWrapper(sourceBody) };
                    if (!mass.Recalculate()) throw new InvalidOperationException("Body mass calculation failed");
                    var bodyMass = mass.Mass;
                    var selectedVolume = mass.Volume;
                    var bodyVolume = ((double[])body.GetMassProperties(1))[3];
                    if (bodyVolume <= 0 || Math.Abs(selectedVolume/bodyVolume-1) > 1e-6)
                        throw new InvalidOperationException("Selected mass volume differs from exported body");
                    if (bodyMass <= 0 || double.IsNaN(bodyMass) || double.IsInfinity(bodyMass))
                        throw new InvalidOperationException("Body has no positive finite material mass");
                    record.MassKg = bodyMass;
                    record.MassSource = "SolidWorks explicit part-body MassProperty2; document material/density settings";
                }
                catch(OperationCanceledException){throw;}
                catch (Exception error) { record.MassSource = "Unavailable from SolidWorks for this body: " + error.Message; }
                package.Meshes.Add(record);
                if (yield) await Task.Delay(1, token);
            }
            token.ThrowIfCancellationRequested(); Validate(frame);
            if (model.GetUpdateStamp() != version) throw new InvalidOperationException("Assembly changed during export. Prepare again.");
            JsonFile.Write(Path.Combine(folder, "geometry.json"), package);
            var latestMaterials=ReadMaterials(frame);
            if(materialSnapshot.Fingerprint()!=latestMaterials.Fingerprint())throw new InvalidOperationException("SolidWorks materials changed during export. Prepare again.");
            JsonFile.Write(Path.Combine(folder,"material-snapshot.json"),materialSnapshot);
            return package;
        }
    }
}
