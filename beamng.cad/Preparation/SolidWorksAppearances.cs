using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    // Read-only visual properties. Mechanical materials and density are captured separately.
    internal sealed class SolidWorksAppearances
    {
        private readonly ISldWorks app;
        private readonly Component2 component;
        private readonly ModelDoc2 part;
        private readonly Body2 body,sourceBody;
        private readonly List<Tuple<object[],VisualAppearance>> rendered=new List<Tuple<object[],VisualAppearance>>();
        private readonly Scene scene,partScene;
        private readonly Dictionary<VisualAppearance,RenderMaterial> native=new Dictionary<VisualAppearance,RenderMaterial>();
        private readonly VisualAppearance componentAppearance,bodyAppearance,partAppearance;
        internal sealed class Scene
        {
            internal List<Tuple<object[],VisualAppearance,RenderMaterial>> Materials;
            private readonly ModelDoc2 assembly;
            private readonly Dictionary<Type,List<Tuple<object,VisualAppearance>>> entities=new Dictionary<Type,List<Tuple<object,VisualAppearance>>>();
            private readonly Dictionary<string,VisualAppearance> references=new Dictionary<string,VisualAppearance>();
            private readonly Dictionary<string,Scene> parts=new Dictionary<string,Scene>();
            private readonly Dictionary<string,List<Tuple<object[],VisualAppearance,RenderMaterial>>> components=new Dictionary<string,List<Tuple<object[],VisualAppearance,RenderMaterial>>>();
            private Dictionary<string,Body2> bodies;
            private static Type Kind(object entity)=>entity is Component2?typeof(Component2):entity is Face2?typeof(Face2):entity is Body2?typeof(Body2):entity is Feature?typeof(Feature):entity is ModelDoc2?typeof(ModelDoc2):null;
            private string Reference(object entity)
            {
                try{var bytes=assembly?.Extension.GetPersistReference3(entity) as byte[];return bytes?.Length>0?Convert.ToBase64String(bytes):null;}
                catch(System.Runtime.InteropServices.COMException){return null;}
            }
            public Scene(ModelDoc2 assembly)
            {
                this.assembly=assembly;
                Materials=CaptureRendered(assembly?.Extension.GetRenderMaterials2((int)swDisplayStateOpts_e.swThisDisplayState,null));
                foreach(var material in Materials)foreach(var entity in material.Item1)
                {
                    var kind=Kind(entity);if(kind==null)continue;
                    if(!entities.TryGetValue(kind,out var list))entities.Add(kind,list=new List<Tuple<object,VisualAppearance>>());
                    list.Add(Tuple.Create(entity,material.Item2));
                    var key=Reference(entity);if(key!=null)references[key]=material.Item2;
                }
            }
            internal Scene Part(ModelDoc2 document)
            {
                var key=document.GetPathName()+"|"+document.ConfigurationManager.ActiveConfiguration.Name;
                if(!parts.TryGetValue(key,out var result))parts.Add(key,result=new Scene(document));
                return result;
            }
            internal Body2 Body(string name)
            {
                if(bodies==null)bodies=(((assembly as PartDoc)?.GetBodies2((int)swBodyType_e.swAllBodies,false) as object[])??Array.Empty<object>())
                    .Cast<Body2>().GroupBy(b=>b.Name).ToDictionary(g=>g.Key,g=>g.First());
                return bodies.TryGetValue(name,out var body)?body:null;
            }
            internal List<Tuple<object[],VisualAppearance,RenderMaterial>> Component(Component2 component)
            {
                var key=Reference(component)??component.Name2;
                if(!components.TryGetValue(key,out var result))components.Add(key,result=CaptureRendered(component.GetRenderMaterials2((int)swDisplayStateOpts_e.swThisDisplayState,null)));
                return result;
            }
            internal VisualAppearance Read(ISldWorks app,object entity)
            {
                var kind=Kind(entity);if(kind==null||!entities.TryGetValue(kind,out var list))return null;
                var key=Reference(entity);
                if(key!=null&&references.TryGetValue(key,out var cached))return cached;
                // Some assembly-context wrappers have different reference bytes.
                // Keep native equality as a fallback, limited to the same entity
                // type; a face must never scan every painted component.
                var result=list.LastOrDefault(item=>app.IsSame(item.Item1,entity)==(int)swObjectEquality.swObjectSame)?.Item2;
                if(key!=null)references[key]=result;
                return result;
            }
        }
        public SolidWorksAppearances(ISldWorks app,Component2 component,Body2 body)
            :this(app,component,body,new Scene(app.ActiveDoc as ModelDoc2)){}
        public SolidWorksAppearances(ISldWorks app,Component2 component,Body2 body,Scene scene)
        {
            this.app=app;this.component=component;this.body=body;this.scene=scene;part=(ModelDoc2)component.GetModelDoc2();
            partScene=scene.Part(part);sourceBody=partScene.Body(body.Name);
            AddRendered(scene.Materials);
            var hierarchy=new Stack<Component2>();for(var instance=component;instance!=null;instance=instance.GetParent())hierarchy.Push(instance);
            foreach(var instance in hierarchy){componentAppearance=scene.Read(app,instance);if(componentAppearance!=null)break;}
            rendered.Clear();AddRendered(scene.Component(component));
            componentAppearance=componentAppearance??Rendered(component)??(component.HasMaterialPropertyValues()?Legacy(component.GetMaterialPropertyValues2((int)swInConfigurationOpts_e.swThisConfiguration,null),"component"):null);
            rendered.Clear();AddRendered(partScene.Materials);
            var appearanceBody=sourceBody??body;
            bodyAppearance=partScene.Read(app,appearanceBody)??(appearanceBody.HasMaterialPropertyValues()?Legacy(appearanceBody.MaterialPropertyValues2,"body"):null);
            partAppearance=partScene.Read(app,part)??Legacy(part.MaterialPropertyValues,"part")??new VisualAppearance {
                BaseColor=new[]{.7,.7,.7,1},Roughness=.6,Metallic=0,Source="SolidWorks default appearance"};
        }
        private static double Unit(double value)=>double.IsNaN(value)||double.IsInfinity(value)?0:Math.Max(0,Math.Min(1,value));
        internal static VisualAppearance Legacy(object values,string source)
        {
            var v=values as double[];
            if(v==null||v.Length<9||v.Take(3).Any(x=>x<0||double.IsNaN(x)||double.IsInfinity(x)))return null;
            return new VisualAppearance {BaseColor=new[]{Unit(v[0]),Unit(v[1]),Unit(v[2]),1-Unit(v[7])},
                Roughness=Math.Max(.04,1-Unit(v[6])),Metallic=0,Source="SolidWorks "+source,
                Limitation="Legacy shininess approximated as PBR roughness; metallic value is unavailable."};
        }
        private void AddRendered(IEnumerable<Tuple<object[],VisualAppearance,RenderMaterial>> values)
        {
            foreach(var value in values){rendered.Add(Tuple.Create(value.Item1,value.Item2));native[value.Item2]=value.Item3;}
        }
        private static List<Tuple<object[],VisualAppearance,RenderMaterial>> CaptureRendered(object values)
        {
            var result=new List<Tuple<object[],VisualAppearance,RenderMaterial>>();
            foreach(RenderMaterial material in values as object[]??Array.Empty<object>())
            {
                var color=material.PrimaryColor;
                var texture=material.TextureFilename;
                var appearance=new VisualAppearance {BaseColor=new[]{(color&255)/255.0,((color>>8)&255)/255.0,((color>>16)&255)/255.0,1-Unit(material.Transparency)},
                    Roughness=Math.Max(.04,Unit(material.Roughness)),Metallic=Unit(material.MetallicMix),
                    Source="SolidWorks render appearance: "+material.FileName,TextureFile=string.IsNullOrWhiteSpace(texture)?null:texture,
                    Limitation="PBR finish is an approximation. Texture maps, decals and procedural patterns are not baked."};
                result.Add(Tuple.Create(material.GetEntities() as object[]??Array.Empty<object>(),appearance,material));
            }
            return result;
        }
        private VisualAppearance Rendered(object entity)
            =>Rendered(rendered,entity);
        private VisualAppearance Rendered(List<Tuple<object[],VisualAppearance>> values,object entity)
        {
            if(entity==null)return null;
            return values.LastOrDefault(r=>r.Item1.Any(e=>app.IsSame(e,entity)==(int)swObjectEquality.swObjectSame))?.Item2;
        }
        public VisualAppearance Read(Face2 face)
        {
            if(componentAppearance!=null)return componentAppearance;
            var sourceFace=part.Extension.GetCorresponding2(face) as Face2??face;
            var feature=sourceFace.GetFeature() as Feature;
            // Assembly render queries can expose a part body's physical-material
            // finish. It must not mask paint on that body's faces/features when
            // reading the companion again to split or reassign its moving pieces.
            return scene.Read(app,face)??partScene.Read(app,sourceFace)??partScene.Read(app,face)??(sourceFace.HasMaterialPropertyValues()?Legacy(sourceFace.GetMaterialPropertyValues2((int)swInConfigurationOpts_e.swThisConfiguration,null),"face"):null)
                ??partScene.Read(app,feature)??(feature==null||!feature.HasMaterialPropertyValues()?null:Legacy(feature.GetMaterialPropertyValues2((int)swInConfigurationOpts_e.swThisConfiguration,null),"feature"))
                ??scene.Read(app,body)??bodyAppearance??partAppearance;
        }
        public RenderMaterial ReadNative(Face2 face)
        {var appearance=Read(face);return native.TryGetValue(appearance,out var material)?material:null;}
        public static bool Same(VisualAppearance a,VisualAppearance b)=>a.BaseColor.SequenceEqual(b.BaseColor)&&a.Roughness==b.Roughness&&a.Metallic==b.Metallic&&a.Source==b.Source&&a.TextureFile==b.TextureFile;
    }
}
