using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;

namespace BeamNG.Cad.Preparation
{
    internal static class CompanionAssemblyLink
    {
        [DataContract] private sealed class Link
        {
            [DataMember] public string Format="beamng-companion-link";
            [DataMember] public string Receipt;
        }
        private static string LinkPath(string project)=>project+".companion.json";
        public static AssociationAssembly.Receipt Read(string path)
        {
            var value=JsonFile.Read<AssociationAssembly.Receipt>(path);
            if(value.Format!="beamng-association-assembly"||value.Version<1||value.Version>4||value.Status!="completed")
                throw new InvalidDataException("Choose a completed working-assembly.json receipt.");
            if(!File.Exists(value.Assembly)||!File.Exists(value.Project)||!File.Exists(value.SourceProject))
                throw new FileNotFoundException("A linked source project or companion file is missing. Restore it or choose the correct companion receipt.");
            return value;
        }
        public static string Find(VehicleProject project)
        {
            var link=LinkPath(project.FilePath);
            if(File.Exists(link))
            {
                var value=JsonFile.Read<Link>(link);
                if(value.Format!="beamng-companion-link")throw new InvalidDataException("Invalid companion link.");
                return value.Receipt;
            }
            var adjacent=Path.Combine(Path.GetDirectoryName(project.FilePath),"working-assembly.json");
            if(File.Exists(adjacent))
            {
                var value=Read(adjacent);
                if(ComponentAssignments.SameDocument(value.Project,project.FilePath))return adjacent;
            }
            return null;
        }
        public static void Register(string receiptPath)
        {
            receiptPath=Path.GetFullPath(receiptPath);var receipt=Read(receiptPath);
            WriteLinks(receiptPath,receipt);
        }
        private static void WriteLinks(string receiptPath,AssociationAssembly.Receipt receipt)
        {
            var link=new Link {Receipt=receiptPath};
            JsonFile.Write(LinkPath(receipt.SourceProject),link);JsonFile.Write(LinkPath(receipt.Project),link);
        }
        internal static void Promote(string receiptPath,AssociationAssembly.Receipt receipt)
        {
            receiptPath=Path.GetFullPath(receiptPath);
            // Links point to the still-valid previous receipt until the final
            // atomic replacement succeeds. A link write failure cannot advance it.
            WriteLinks(receiptPath,receipt);
            JsonFile.Write(receiptPath,receipt);
        }
        public static void Attach(VehicleProject project,string receiptPath)
        {
            var receipt=Read(receiptPath);
            if(!ComponentAssignments.SameDocument(receipt.SourceProject,project.FilePath)&&!ComponentAssignments.SameDocument(receipt.Project,project.FilePath))
                throw new InvalidOperationException("That companion belongs to another project.");
            Register(receiptPath);
        }
        internal static string Serialized(object value,Type type)
        {
            using(var stream=new MemoryStream())
            {
                new DataContractJsonSerializer(type).WriteObject(stream,value);
                return Encoding.UTF8.GetString(stream.ToArray());
            }
        }
        private static readonly HashSet<string> artifacts=new HashSet<string> {"GeometryDirectory","AppearanceDirectory","AppearancePackageState","AppearancePackageError"};
        internal static IEnumerable<FieldInfo> Fields=>typeof(ComponentDefinition).GetFields().Where(f=>f.IsDefined(typeof(DataMemberAttribute),false)&&!artifacts.Contains(f.Name)).OrderBy(f=>f.Name);
        internal static string State(ComponentDefinition c)=>c==null?"null":string.Join("\n",Fields.Select(f=>f.Name+":"+(f.Name=="AppearanceCoilover"?CoiloverState(c.AppearanceCoilover):Serialized(f.GetValue(c),f.FieldType))));
        private static string CoiloverState(CoiloverAppearance value)=>value==null?"null":value.HousingMount+"|"+string.Join("|",(value.Pieces??new List<CoiloverMeshAssignment>()).Select(p=>p.Kind+"|"+p.SourceDocument+"|"+p.Configuration+"|"+Serialized(p.Selections,typeof(List<SelectionReference>))+"|"+Serialized(p.BodyIds,typeof(List<string>))));
        public static string Status(VehicleProject current,string receiptPath)
        {
            if(string.IsNullOrEmpty(receiptPath))return "No companion linked. Create one, or use Update companion assembly to select an existing copy.";
            var receipt=Read(receiptPath);var source=VehicleProject.Load(receipt.SourceProject);
            if(!ComponentAssignments.SameDocument(current.FilePath,receipt.SourceProject)&&!ComponentAssignments.SameDocument(current.FilePath,receipt.Project))
                return "This is an earlier companion revision. Open companion to continue editing the latest revision.";
            if(receipt.SourceComponents==null)return "Existing companion linked. First update will establish assignment tracking; matching groups are retained.";
            var before=receipt.SourceComponents.ToDictionary(c=>c.Id);var now=source.Components.ToDictionary(c=>c.Id);
            var added=now.Keys.Except(before.Keys).Count();var removed=before.Keys.Except(now.Keys).Count();var changed=now.Keys.Intersect(before.Keys).Count(id=>State(now[id])!=State(before[id]));
            var layout=Serialized(source.MvpTemplates,typeof(List<MvpTemplateChoice>))!=Serialized(receipt.SourceTemplates,typeof(List<MvpTemplateChoice>));
            var order=!source.Components.Select(c=>c.Id).SequenceEqual(receipt.SourceComponents.Select(c=>c.Id));
            var additions=now.Keys.Except(before.Keys).Select(id=>now[id].Name).ToArray();
            var replacements=AssociationAssembly.ReplacementIds(receipt).Count;
            var retained=replacements==0?"":" "+replacements+" reviewed replacement groups are owned by the companion and retained during source updates, including full geometry refresh.";
            return (added+removed+changed>0||layout||order?"Companion updates pending: "+added+" added, "+removed+" removed, "+changed+" changed"+(layout?"; vehicle layout changed":"")+(order&&added+removed==0?"; order changed":"")+"."
                +(additions.Length>0?" Added: "+string.Join(", ",additions.Take(5))+(additions.Length>5?", ...":"")+".":"")
                +" Use Update companion assembly to apply saved changes.":"Saved assignments are synchronized. Use Refresh assigned geometry too for shape/material changes inside the same bodies.")+retained;
        }
    }
}
