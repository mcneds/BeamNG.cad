using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using Environment=System.Environment;

namespace BeamNG.Cad.Preparation
{
    // Detached values: never change entities or setters on a source appearance.
    internal sealed class NativeAppearance
    {
        private readonly Dictionary<PropertyInfo,object> values=new Dictionary<PropertyInfo,object>();
        private readonly string file;
        private readonly double[] u,v,center;
        private static readonly PropertyInfo[] properties=typeof(IRenderMaterial).GetProperties()
            .Where(p=>p.CanRead&&p.CanWrite&&p.Name!="FileName"&&p.Name!="LinkToFile"&&p.Name!="IgnoreMissingFile").ToArray();
        public NativeAppearance(RenderMaterial source)
        {
            file=source.FileName;
            foreach(var property in properties)values[property]=property.GetValue(source);
            double x,y,z;source.GetUDirection2(out x,out y,out z);u=new[]{x,y,z};
            source.GetVDirection2(out x,out y,out z);v=new[]{x,y,z};
            source.GetCenterPoint2(out x,out y,out z);center=new[]{x,y,z};
        }
        private static string Asset(string path,string folder,List<string> notes)
        {
            if(string.IsNullOrWhiteSpace(path))return path;
            if(!File.Exists(path)){notes.Add("Appearance asset unavailable: "+path);return "";}
            // SolidWorks can keep a writable handle to the shared material
            // library while another document reads it. Snapshot through a
            // compatible read handle, and hash exactly the bytes we copied.
            var directory=Path.Combine(folder,"appearances");Directory.CreateDirectory(directory);
            var temporary=Path.Combine(directory,Guid.NewGuid().ToString("N")+".tmp");
            try
            {
                var before=new FileInfo(path);var length=before.Length;var modified=before.LastWriteTimeUtc;
                using(var input=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))
                using(var output=new FileStream(temporary,FileMode.CreateNew,FileAccess.Write,FileShare.None))input.CopyTo(output);
                var after=new FileInfo(path);
                if(after.Length!=length||after.LastWriteTimeUtc!=modified||new FileInfo(temporary).Length!=length)
                    throw new IOException("Appearance asset changed while being copied; retry after its edit finishes: "+path);
                string hash;using(var stream=File.OpenRead(temporary))using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
                var destination=Path.Combine(directory,hash.Substring(0,16)+Path.GetExtension(path));
                if(!File.Exists(destination))File.Move(temporary,destination);
                return destination;
            }
            finally {if(File.Exists(temporary))File.Delete(temporary);}
        }
        public void Apply(ModelDoc2 part,IEnumerable<Face2> faces,string folder,List<string> notes)
        {
            var sourceFile=Asset(file,folder,notes);
            if(string.IsNullOrEmpty(sourceFile))
            {
                // A saved CAD appearance often outlives the custom .p2m file on
                // its author's machine. Reconstruct its exposed values and maps.
                sourceFile=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),@"SOLIDWORKS Corp\SOLIDWORKS\data\graphics\materials\color.p2m");
                if(!File.Exists(sourceFile))throw new FileNotFoundException("Cannot recreate the saved CAD finish; locate its appearance file.",file);
            }
            var material=part.Extension.CreateRenderMaterial(sourceFile)??throw new InvalidOperationException("Could not recreate native appearance: "+file);
            // Shader/colour modes can reset colour and texture properties. Apply
            // modes first, then the saved values they control.
            foreach(var item in values.OrderBy(v=>v.Key.Name=="IlluminationShaderType"||v.Key.Name=="ColorForm"||v.Key.Name=="MappingType"?0:
                v.Key.Name.EndsWith("Color",StringComparison.Ordinal)||v.Key.Name.EndsWith("TextureFilename",StringComparison.Ordinal)?2:1))
            {
                var value=item.Value;
                if(item.Key.Name.EndsWith("TextureFilename",StringComparison.Ordinal))value=Asset((string)value,folder,notes);
                item.Key.SetValue(material,value);
            }
            material.SetUDirection2(u[0],u[1],u[2]);material.SetVDirection2(v[0],v[1],v[2]);material.SetCenterPoint2(center[0],center[1],center[2]);
            foreach(var face in faces)if(!material.AddEntity(face))throw new InvalidOperationException("Could not attach the copied appearance to an imported face.");
            int id1=0,id2=0;
            var displayStates=part.ConfigurationManager.ActiveConfiguration.GetDisplayStates();
            if(!part.Extension.AddDisplayStateSpecificRenderMaterial(material,(int)swDisplayStateOpts_e.swSpecifyDisplayState,displayStates,out id1,out id2))
                throw new InvalidOperationException("Could not save the copied native appearance: "+file);
            part.Extension.UpdateRenderMaterialsInSceneGraph(true);
            part.SetSaveFlag();
        }
    }
}
