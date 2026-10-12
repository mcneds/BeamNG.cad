using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
namespace BeamNG.Cad.Preparation
{
    [DataContract] internal sealed class PreparationFile
    {
        [DataMember] public string Format = "beamng-cad-preparation";
        [DataMember] public int Version = 1;
        [DataMember] public string SourceDocument;
        [DataMember] public List<FrameAssignment> Assignments = new List<FrameAssignment>();
        public static string FileName(string assembly) => assembly + ".truemesh-prep.json";
        public static PreparationFile Load(string assembly)
        {
            var path = FileName(assembly);
            if (!File.Exists(path)) return new PreparationFile { SourceDocument = assembly };
            var file = JsonFile.Read<PreparationFile>(path);
            if (file.Format != "beamng-cad-preparation" || file.Version != 1) throw new InvalidDataException("Unsupported preparation file.");
            if (!string.Equals(Path.GetFullPath(file.SourceDocument), Path.GetFullPath(assembly), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Preparation file belongs to another assembly. Define the frame selection for this document.");
            // Only editable assignments migrate. Geometry snapshots and archived builds
            // retain their original mapping and provenance.
            if (file.Assignments.Any(a => a.Hull.Orientation != AxisMapping.Standard || a.Hull.CoordinateConvention != AxisMapping.Convention))
            {
                File.Copy(path, path + ".coordinates-" + Guid.NewGuid().ToString("N") + ".bak");
                foreach (var assignment in file.Assignments)
                {
                    assignment.Hull.Orientation = AxisMapping.Standard;
                    assignment.Hull.CoordinateConvention = AxisMapping.Convention;
                }
                JsonFile.Write(path, file);
            }
            return file;
        }
        public FrameAssignment Frame(string configuration) => Assignments.FirstOrDefault(a => a.Configuration == configuration && a.Role == "frame");
        public void Save(FrameAssignment frame)
        {
            Assignments.RemoveAll(a => a.Configuration == frame.Configuration && a.Role == frame.Role);
            Assignments.Add(frame); JsonFile.Write(FileName(SourceDocument), this);
        }
    }
    [DataContract] internal sealed class FrameAssignment
    {
        // Capture feedback only; saved body references remain the durable identity.
        public int SelectedItemCount;
        public string CaptureSummary(int bodyCount)=>SelectedItemCount+" selected items -> "+bodyCount+" unique bodies";
        [DataMember] public string Id = Guid.NewGuid().ToString("N");
        [DataMember] public string Role = "frame";
        [DataMember] public string Configuration;
        [DataMember] public List<SelectionReference> Selections = new List<SelectionReference>();
        [DataMember] public HullOptions Hull = new HullOptions();
    }
    [DataContract] internal sealed class SelectionReference
    {
        [DataMember] public string Kind;
        [DataMember] public string Reference;
        [DataMember] public string ComponentReference;
        [DataMember] public string Name;
    }
    [DataContract] internal sealed class HullOptions
    {
        [DataMember] public int Width = 3;
        [DataMember] public int Height = 5;
        [DataMember] public int Length = 7;
        [DataMember] public double Offset = 0.01;
        [DataMember] public double Weld = 0.15;
        [DataMember] public double ProxyDivisor = 7;
        [DataMember] public double ProxyOffsetRatio = 100;
        [DataMember] public bool Symmetry = false;
        [DataMember] public bool SymmetryBisectFlip = false;
        [DataMember] public double SymmetryMergeDistance = 0.0001;
        // Right-handed rotations only. All bodies use this same mapping, with no centering.
        [DataMember] public string Orientation = AxisMapping.Standard;
        [DataMember] public string CoordinateConvention = AxisMapping.Convention;
        // DataContract deserialization does not run field initializers. Preserve
        // the generator defaults when loading older saved assignments.
        [OnDeserializing]
        private void Defaults(StreamingContext context)
        {
            Width=3; Height=5; Length=7; Offset=0.01; Weld=0.15;
            ProxyDivisor=7; ProxyOffsetRatio=100; SymmetryMergeDistance=0.0001;
            Orientation="XYZ";
        }
        public void Validate()
        {
            if (new[] { Width, Height, Length }.Any(v => v < 2 || v > 100))
                throw new InvalidDataException("Grid dimensions must be integers from 2 to 100.");
            if (Symmetry && Width % 2 == 0)
                throw new InvalidDataException("X symmetry needs an odd width grid (3, 5, 7, ...).");
            AxisMapping.Matrix(Orientation);
            if (new[] { Offset, Weld, SymmetryMergeDistance }.Any(v => double.IsNaN(v) || double.IsInfinity(v) || v < 0))
                throw new InvalidDataException("Hull distances must be finite and non-negative.");
            if (new[] { ProxyDivisor, ProxyOffsetRatio }.Any(v => double.IsNaN(v) || double.IsInfinity(v) || v <= 0))
                throw new InvalidDataException("Proxy divisor and offset ratio must be finite and positive.");
        }
    }
    [DataContract] internal sealed class GeometryPackage
    {
        [DataMember] public string Format = "beamng-cad-frame-geometry";
        [DataMember] public int Version = 1;
        [DataMember] public string SourceDocument;
        [DataMember] public string Configuration;
        [DataMember] public string Units = "metres";
        [DataMember] public string CoordinateSystem = "assembly";
        [DataMember] public string MaterialSource = "solidworks";
        [DataMember] public FrameAssignment Assignment;
        [DataMember] public List<MeshRecord> Meshes = new List<MeshRecord>();
    }
    [DataContract] internal sealed class MeshRecord
    {
        [DataMember] public string Id;
        [DataMember] public string File;
        [DataMember] public string Component;
        [DataMember] public string Body;
        [DataMember] public string SourceDocument;
        [DataMember] public string Configuration;
        [DataMember] public string ComponentReference;
        [DataMember] public string BodyReference;
        [DataMember] public double? MassKg;
        [DataMember] public string MassSource;
        [DataMember(EmitDefaultValue=false)] public double[] NativeUnitDensityProperties,NativeCenterAssembly;
        [DataMember(EmitDefaultValue=false)] public double[][] NativeAxesAssembly;
        [DataMember(EmitDefaultValue=false)] public string TessellationSource;
        [DataMember(EmitDefaultValue=false)] public string BodyKind;
        [DataMember(EmitDefaultValue=false)] public double? SurfaceAreaM2;
        [DataMember(EmitDefaultValue=false)] public double? DensityKgM3;
        [DataMember(EmitDefaultValue=false)] public List<AppearanceRange> AppearanceGroups;
    }
    [DataContract] internal sealed class AppearanceRange
    {
        [DataMember] public uint StartTriangle;
        [DataMember] public uint TriangleCount;
        [DataMember] public VisualAppearance Appearance;
    }
    [DataContract] internal sealed class VisualAppearance
    {
        [DataMember] public double[] BaseColor;
        [DataMember] public double Roughness;
        [DataMember] public double Metallic;
        [DataMember] public string Source;
        [DataMember(EmitDefaultValue=false)] public string TextureFile;
        [DataMember(EmitDefaultValue=false)] public string Limitation;
    }
    internal static class JsonFile
    {
        public static T Read<T>(string path)
        { using (var stream = File.OpenRead(path)) return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(stream); }
        public static void Write<T>(string path, T value)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            var temporary = path + ".tmp";
            using (var stream = File.Create(temporary)) new DataContractJsonSerializer(typeof(T)).WriteObject(stream, value);
            if (File.Exists(path)) File.Replace(temporary, path, path + ".bak"); else File.Move(temporary, path);
        }
    }
}
