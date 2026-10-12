using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.Serialization;

namespace BeamNG.Cad.Preparation
{
    [DataContract] internal sealed class CoiloverSpring
    {
        [DataMember] public string Mode="auto";
        [DataMember] public double MainRateNPerM=30000;
        [DataMember] public double TenderRateNPerM=15000;
        [DataMember] public double CrossoverCompressionM=.01;
    }
    [DataContract] internal sealed class CoiloverMeshAssignment
    {
        [DataMember] public string Kind;
        [DataMember] public string SourceDocument;
        [DataMember] public string Configuration;
        [DataMember] public List<SelectionReference> Selections=new List<SelectionReference>();
        [DataMember] public List<string> BodyIds=new List<string>();
        [DataMember] public string GeometryDirectory;
    }
    [DataContract] internal sealed class CoiloverAppearance
    {
        [DataMember] public string HousingMount="top";
        [DataMember] public List<CoiloverMeshAssignment> Pieces=new List<CoiloverMeshAssignment>();
        public static readonly string[] Kinds={"housing","shaft","spring"};
        public static bool Supported(ComponentDefinition c)=>c?.MvpRole?.EndsWith("_spring_damper",StringComparison.Ordinal)==true;
        public static bool Active(ComponentDefinition c)=>c?.AppearanceCoilover?.Pieces?.Count>0;
        public static FrameAssignment Assignment(CoiloverMeshAssignment piece)=>new FrameAssignment {Configuration=piece.Configuration,Selections=piece.Selections};
        public static void Assign(ComponentDefinition c,string kind,FrameAssignment selection,List<string> ids,string source)
        {
            if(!Supported(c)||!Kinds.Contains(kind))throw new InvalidOperationException("Choose a coilover group and a moving piece.");
            if(selection==null||selection.Selections==null||selection.Selections.Count==0||ids==null||ids.Count==0)throw new InvalidOperationException("Select the bodies belonging to this coilover piece.");
            var value=c.AppearanceCoilover??new CoiloverAppearance();
            if(value.Pieces.Any(p=>p.Kind!=kind && p.BodyIds.Intersect(ids).Any()))
                throw new InvalidOperationException("These bodies already belong to another piece of this coilover. Housing, shaft and spring must be separate. No assignment changed.");
            value.Pieces.RemoveAll(p=>p.Kind==kind);
            value.Pieces.Add(new CoiloverMeshAssignment {Kind=kind,Configuration=selection.Configuration,SourceDocument=source,Selections=selection.Selections.Select(s=>new SelectionReference {Kind=s.Kind,Name=s.Name,Reference=s.Reference,ComponentReference=s.ComponentReference}).ToList(),BodyIds=ids.ToList()});
            c.AppearanceCoilover=value;Pending(c);
        }
        public static void Validate(ComponentDefinition c,string document)
        {
            if(!Active(c))return;
            var value=c.AppearanceCoilover;
            if(!Supported(c)||!new[]{"top","bottom"}.Contains(value.HousingMount))throw new InvalidOperationException("Invalid coilover role or housing mount.");
            var missing=Kinds.Where(k=>!value.Pieces.Any(p=>p.Kind==k && p.Selections?.Count>0)).ToArray();
            if(missing.Length>0)throw new InvalidOperationException(c.Name+": assign the coilover "+string.Join(", ",missing)+" before packaging. Saved selections are retained.");
            if(value.Pieces.Count!=3||value.Pieces.SelectMany(p=>p.BodyIds).Distinct().Count()!=value.Pieces.Sum(p=>p.BodyIds.Count))
                throw new InvalidOperationException(c.Name+": coilover pieces have duplicate body ownership.");
            if(value.Pieces.Any(p=>!ComponentAssignments.SameDocument(p.SourceDocument,document)))throw new InvalidOperationException(c.Name+": activate the assembly containing the coilover assignments.");
        }
        public static void Pending(ComponentDefinition c){c.AppearancePackageState="pending";c.AppearancePackageError=null;}
    }
}
