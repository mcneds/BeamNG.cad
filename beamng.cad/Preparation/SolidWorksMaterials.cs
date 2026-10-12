using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Xml;
using System.Xml.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    [DataContract] internal sealed class MaterialSnapshot
    {
        [DataMember(Name="format")] public string Format = "solidworks-body-materials";
        [DataMember(Name="version")] public int Version = 1;
        [DataMember(Name="units")] public string Units = "SI";
        [DataMember(Name="bodies")] public List<BodyMaterial> Bodies = new List<BodyMaterial>();
        public string Fingerprint()
        {
            using(var stream=new MemoryStream()) using(var hash=SHA256.Create())
            {
                new DataContractJsonSerializer(typeof(MaterialSnapshot)).WriteObject(stream,this);
                return BitConverter.ToString(hash.ComputeHash(stream.ToArray())).Replace("-","").ToLowerInvariant();
            }
        }
        public string Summary() => string.Join("\r\n\r\n",Bodies.Select(b=>b.Component+" / "+b.Body+"\r\n"+
            (b.Error??(b.Name+" ("+b.Assignment+")\r\n"+
            string.Format(CultureInfo.InvariantCulture,"Density {0:G6} kg/m³ | E {1:G6} GPa | ν {2:G6} | G {3:G6} GPa\r\nYield {4:G6} MPa | Tensile {5:G6} MPa",
                b.Density,b.Young/1e9,b.Poisson,b.Shear/1e9,b.Yield/1e6,b.Ultimate/1e6)))));
    }
    [DataContract] internal sealed class BodyMaterial
    {
        [DataMember(Name="body_id")] public string BodyId;
        [DataMember(Name="body")] public string Body;
        [DataMember(Name="component")] public string Component;
        [DataMember(Name="configuration")] public string Configuration;
        [DataMember(Name="name")] public string Name;
        [DataMember(Name="assignment")] public string Assignment;
        [DataMember(Name="database")] public string Database;
        [DataMember(Name="database_sha256")] public string DatabaseHash;
        [DataMember(Name="entry_sha256")] public string EntryHash;
        [DataMember(Name="model")] public string Model = "linear_isotropic";
        [DataMember(Name="density_kg_m3")] public double? Density;
        [DataMember(Name="young_pa")] public double? Young;
        [DataMember(Name="poisson")] public double? Poisson;
        [DataMember(Name="shear_pa")] public double? Shear;
        [DataMember(Name="shear_source")] public string ShearSource;
        [DataMember(Name="yield_pa")] public double? Yield;
        [DataMember(Name="ultimate_pa")] public double? Ultimate;
        [DataMember(Name="error")] public string Error;
    }
    // Reads the same assignments and databases as the native material editor.
    // No setter, document activation, or configuration change belongs here.
    internal sealed class SolidWorksMaterials
    {
        private readonly ISldWorks app;
        private readonly Dictionary<string,Tuple<XDocument,string>> databases = new Dictionary<string,Tuple<XDocument,string>>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<Tuple<ModelDoc2,string>,ILookup<string,Body2>> bodyLookup = new Dictionary<Tuple<ModelDoc2,string>,ILookup<string,Body2>>();
        public SolidWorksMaterials(ISldWorks application) { app=application; }
        internal static Body2 PartBody(Component2 component,Body2 body)
        {
            var model=component.GetModelDoc2() as ModelDoc2;
            if(!(model is PartDoc part))throw new InvalidOperationException("Resolve the component before reading its material");
            if(model.ConfigurationManager.ActiveConfiguration.Name!=component.ReferencedConfiguration)
                throw new InvalidOperationException("Activate the referenced part configuration '"+component.ReferencedConfiguration+"' before reading its body materials");
            var bodies=(object[])part.GetBodies2((int)swBodyType_e.swSolidBody,false);
            return (bodies??new object[0]).Cast<Body2>().SingleOrDefault(b=>b.Name==body.Name)
                ??throw new InvalidOperationException("Body has no unique part-context counterpart");
        }
        public BodyMaterial Read(Component2 component,Body2 body,string id)
        {
            var result=new BodyMaterial { BodyId=id, Body=body.Name, Component=component.Name2, Configuration=component.ReferencedConfiguration };
            try
            {
                var model=component.GetModelDoc2() as ModelDoc2;
                if(!(model is PartDoc part))throw new InvalidOperationException("Resolve the component before reading its material");
                if(model.ConfigurationManager.ActiveConfiguration.Name!=result.Configuration)
                    throw new InvalidOperationException("Activate the referenced part configuration '"+result.Configuration+"' before reading its body materials");
                var key=Tuple.Create(model,result.Configuration);
                if(!bodyLookup.TryGetValue(key,out var lookup))
                {
                    lookup=((part.GetBodies2((int)swBodyType_e.swAllBodies,false) as object[])??new object[0]).Cast<Body2>().ToLookup(b=>b.Name);
                    bodyLookup.Add(key,lookup);
                }
                var source=lookup[result.Body].SingleOrDefault()??throw new InvalidOperationException("Body has no unique part-context counterpart");
                string database;
                var name=source.GetMaterialPropertyName(component.ReferencedConfiguration,out database);
                result.Assignment="body";
                if(string.IsNullOrWhiteSpace(name))
                {
                    name=((PartDoc)component.GetModelDoc2()).GetMaterialPropertyName2(component.ReferencedConfiguration,out database);
                    result.Assignment="inherited part";
                }
                if(string.IsNullOrWhiteSpace(name))throw new InvalidDataException("No SolidWorks material assigned; choose a material for this body or its part");
                result.Name=name;
                var candidates=new List<string>();
                if(!string.IsNullOrWhiteSpace(database))
                {
                    if(Path.IsPathRooted(database) && File.Exists(database))candidates.Add(Path.GetFullPath(database));
                    else
                    {
                        var known=(System.Collections.IEnumerable)app.GetMaterialDatabases();
                        if(known!=null)candidates.AddRange(known.Cast<string>().Where(p=>
                            (string.Equals(Path.GetFileName(p),Path.GetFileName(database),StringComparison.OrdinalIgnoreCase) ||
                             string.Equals(Path.GetFileNameWithoutExtension(p),database,StringComparison.OrdinalIgnoreCase)) && File.Exists(p)).Select(Path.GetFullPath));
                    }
                }
                candidates=candidates.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                if(candidates.Count!=1)throw new InvalidDataException("Material database is unavailable or ambiguous: "+database);
                result.Database=candidates[0];
                if(!databases.TryGetValue(result.Database,out var loaded))
                {
                    var bytes=File.ReadAllBytes(result.Database);
                    using(var stream=new MemoryStream(bytes)) using(var reader=XmlReader.Create(stream,new XmlReaderSettings { DtdProcessing=DtdProcessing.Prohibit,XmlResolver=null }))
                        loaded=Tuple.Create(XDocument.Load(reader),Hash(bytes));
                    databases.Add(result.Database,loaded);
                }
                result.DatabaseHash=loaded.Item2;
                var entries=loaded.Item1.Descendants().Where(e=>e.Name.LocalName=="material" && (string)e.Attribute("name")==name).ToList();
                if(entries.Count!=1)throw new InvalidDataException("Material entry is missing or ambiguous: "+name);
                ReadEntry(entries[0],result);
            }
            catch(Exception e) { result.Error=e.Message; }
            return result;
        }
        private static string Hash(byte[] bytes)
        { using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-","").ToLowerInvariant(); }
        internal static void ReadEntry(XElement entry,BodyMaterial result)
        {
            result.EntryHash=Hash(System.Text.Encoding.UTF8.GetBytes(entry.ToString(SaveOptions.DisableFormatting)));
            var physical=entry.Elements().SingleOrDefault(e=>e.Name.LocalName=="physicalproperties")
                ??throw new InvalidDataException("Material has no physical properties");
            var names=physical.Elements().Select(e=>e.Name.LocalName).ToArray();
            if(names.Any(n=>new[]{"EY","EZ","NUYZ","NUXZ","GYZ","GXZ"}.Contains(n)))
                throw new InvalidDataException("Orthotropic materials require a different reference model");
            double ReadValue(string name)
            {
                var elements=physical.Elements().Where(e=>e.Name.LocalName==name).ToArray();
                if(elements.Length!=1)throw new InvalidDataException("Missing or ambiguous material property: "+name);
                var property=elements[0];
                if(property.Attributes().Any(a=>a.Name.LocalName.IndexOf("curve",StringComparison.OrdinalIgnoreCase)>=0))
                    throw new InvalidDataException("Temperature-dependent/curve property is unsupported: "+name);
                if(!double.TryParse((string)property.Attribute("value"),NumberStyles.Float,CultureInfo.InvariantCulture,out var value) || double.IsNaN(value) || double.IsInfinity(value))
                    throw new InvalidDataException("Invalid material property: "+name);
                if(name=="NUXY" ? value<=-1 || value>=.5 : value<=0)throw new InvalidDataException("Nonphysical material property: "+name);
                return value;
            }
            result.Density=ReadValue("DENS");result.Young=ReadValue("EX");result.Poisson=ReadValue("NUXY");
            result.Yield=ReadValue("SIGYLD");result.Ultimate=ReadValue("SIGXT");
            if(result.Ultimate<result.Yield)throw new InvalidDataException("Tensile strength is below yield strength");
            result.Shear=names.Contains("GXY")?ReadValue("GXY"):result.Young/(2*(1+result.Poisson));
            result.ShearSource=names.Contains("GXY")?"SolidWorks GXY":"derived from EX and NUXY";
        }
    }
}
