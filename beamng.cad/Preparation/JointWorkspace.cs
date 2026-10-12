using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.Serialization;

namespace BeamNG.Cad.Preparation
{
    [DataContract] internal sealed class JointWorkspace
    {
        [DataMember] public string Mode="legacy";
        [DataMember] public List<JointDefinition> Joints=new List<JointDefinition>();
        [DataMember] public List<HardpointBinding> Bindings=new List<HardpointBinding>();
        [DataMember] public List<NativeMateRecord> Mates=new List<NativeMateRecord>();
        [DataMember] public List<MovingMember> Members=new List<MovingMember>();
        [DataMember] public List<NativePlacement> Placements=new List<NativePlacement>();
        [DataMember] public Dictionary<string,double> Parameters=new Dictionary<string,double>();
        [DataMember] public string ScanDocument,ScanConfiguration,ScanHash;
        [DataMember] public int ScanStamp;
        public void Normalize()
        {
            Mode=Mode??"legacy";Joints=Joints??new List<JointDefinition>();Bindings=Bindings??new List<HardpointBinding>();
            Mates=Mates??new List<NativeMateRecord>();Members=Members??new List<MovingMember>();Parameters=Parameters??new Dictionary<string,double>();
            Placements=Placements??new List<NativePlacement>();
            foreach(var joint in Joints){joint.MateIds=joint.MateIds??new List<string>();joint.AnchorIds=joint.AnchorIds??new List<string>();}
            foreach(var mate in Mates)mate.Entities=mate.Entities??new List<NativeMateEntity>();
            foreach(var member in Members){member.Selections=member.Selections??new List<SelectionReference>();member.BodyIds=member.BodyIds??new List<string>();}
        }
        public void Invalidate(IEnumerable<string> owners,string reason)
        {
            var changed=new HashSet<string>(owners);
            foreach(var joint in Joints.Where(j=>changed.Contains(j.Parent)||changed.Contains(j.Child))) {joint.Status="needs_repair";joint.Issue=reason;}
            foreach(var binding in Bindings.Where(b=>changed.Contains(b.ComponentId)))binding.Status="needs_repair";
            ScanHash=null;
        }
    }
    [DataContract] internal sealed class NativePlacement
    {
        [DataMember] public string ComponentId,ComponentReference,MemberId;
        [DataMember] public bool Fixed;
    }
    [DataContract] internal sealed class JointDefinition
    {
        [DataMember] public string Id=Guid.NewGuid().ToString("N");
        [DataMember] public string Name="Joint",Kind="unresolved",Parent,Child,ParentMember,ChildMember;
        [DataMember] public string Status="review",Issue,Source="manual",SourceHash;
        [DataMember] public List<string> MateIds=new List<string>();
        [DataMember] public List<string> AnchorIds=new List<string>();
        [DataMember] public double[] Center,Axis;
        [DataMember] public bool HasLimits;
        [DataMember] public double Minimum,Maximum;
        public string Label=>Name+" | "+Kind+" | "+Status;
    }
    [DataContract] internal sealed class HardpointBinding
    {
        [DataMember] public string Request,ComponentId,AnchorId,JointId,Point="center",Status="resolved";
        [DataMember] public string GeneratedSource;
    }
    [DataContract] internal sealed class MovingMember
    {
        [DataMember] public string Id=Guid.NewGuid().ToString("N"),ComponentId,Name,Kind,ComponentReference,Part;
        [DataMember] public string GeometryDirectory;
        [DataMember] public List<SelectionReference> Selections=new List<SelectionReference>();
        [DataMember] public List<string> BodyIds=new List<string>();
        [DataMember] public bool PlacementFixed=true;
    }
    [DataContract] internal sealed class NativeMateRecord
    {
        [DataMember] public string Id,Name,Type,Reference,Issue;
        [DataMember] public bool Suppressed,PositioningOnly,LockRotation;
        [DataMember] public List<NativeMateEntity> Entities=new List<NativeMateEntity>();
        [DataMember] public double Value,Minimum,Maximum;
        [DataMember] public bool HasLimits;
    }
    [DataContract] internal sealed class NativeMateEntity
    {
        [DataMember] public string ComponentId,MemberId,ComponentReference,Reference,Kind;
        [DataMember] public double[] Point,Axis;
        [DataMember] public double[][] AxisSites;
        [DataMember] public double Radius;
    }
}
