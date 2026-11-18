using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Text.RegularExpressions;
using BeamNG.Cad.FramePipeline;

namespace BeamNG.Cad.Preparation
{
    [DataContract] internal sealed class ProjectIdentity
    {
        [DataMember(Name="id")] public string Id;
        [DataMember(Name="namespace")] public string Namespace;
        public static ProjectIdentity Create(string name)
        {
            var id=Guid.NewGuid().ToString("N");
            var slug=Regex.Replace((name??"vehicle").ToLowerInvariant(),"[^a-z0-9]+","_").Trim('_');
            if(slug.Length==0 || !char.IsLetter(slug[0]))slug="vehicle_"+slug;
            if(slug.Length>32)slug=slug.Substring(0,32).TrimEnd('_');
            return new ProjectIdentity {Id=id,Namespace=slug+"_"+id.Substring(0,8)};
        }
        public void Validate()
        {
            if(!Regex.IsMatch(Id??"","^[0-9a-f]{32}$") || !Regex.IsMatch(Namespace??"","^[a-z][a-z0-9_]{1,45}$"))
                throw new InvalidDataException("Invalid project/package identity.");
        }
    }

    [DataContract] internal sealed class VehicleProject
    {
        [DataMember] public int Version=3;
        [DataMember] public string SourceDocument;
        [DataMember] public ProjectIdentity Identity;
        [DataMember] public string LastBuildReceipt="";
        [DataMember] public string FrameBuildReceipt="";
        [DataMember] public string PhysicsBuildReceipt="";
        [DataMember] public string TemplateDefinitionPath="";
        [DataMember] public string PhysicsTemplateReceipt="";
        [DataMember] public List<ComponentDefinition> Components=new List<ComponentDefinition>();
        [DataMember] public List<MountAnchor> Anchors=new List<MountAnchor>();
        [DataMember] public List<MountConnection> Connections=new List<MountConnection>();
        [DataMember] public List<MvpTemplateChoice> MvpTemplates=new List<MvpTemplateChoice>();
        [DataMember] public JointWorkspace JointWorkspace=new JointWorkspace();
        [DataMember(EmitDefaultValue=false)] public Driveline Driveline;
        public string FilePath {get;private set;}
        public string ProfilePath=>FilePath+".profile.json";
        public static string PathFor(string document)=>document+".beamng-project.json";
        public static VehicleProject Load(string path)
        {
            var project=JsonFile.Read<VehicleProject>(path);
            if(project.Version!=2 && project.Version!=3 && project.Version!=4)throw new InvalidDataException("Unsupported vehicle project.");
            project.Identity.Validate();project.FilePath=Path.GetFullPath(path);
            project.Components=project.Components??new List<ComponentDefinition>();
            project.Anchors=project.Anchors??new List<MountAnchor>();
            project.Connections=project.Connections??new List<MountConnection>();
            project.MvpTemplates=project.MvpTemplates??new List<MvpTemplateChoice>();
            project.JointWorkspace=project.JointWorkspace??new JointWorkspace();
            project.JointWorkspace.Normalize();
            project.Driveline?.Normalize();
            foreach(var component in project.Components)
            {
                // Older projects inferred visual-only from excluded sheet mass.
                // Preserve their parent, but require explicit current-geometry acknowledgement.
                component.Representation=component.Representation??(!string.IsNullOrEmpty(component.VisualParentId)&&component.SurfaceMassMode=="ignore"?"visual_only":"physical");
                component.MassPolicy=component.MassPolicy??"cad";
            }
            return project;
        }
        public static VehicleProject CreateFresh(string document,string path,MvpCatalog catalog,string authoringMode)
        {
            if(string.IsNullOrWhiteSpace(document)||!File.Exists(document))throw new InvalidOperationException("Save the source assembly first.");
            path=Path.GetFullPath(path);
            if(File.Exists(path)||File.Exists(path+".profile.json"))throw new IOException("Choose a new project filename. Existing work is preserved.");
            var label=Path.GetFileNameWithoutExtension(document);
            var fresh=new VehicleProject {FilePath=path,SourceDocument=Path.GetFullPath(document),Identity=ProjectIdentity.Create(label)};
            fresh.JointWorkspace.Mode=authoringMode=="authored"?"authored":"legacy";
            catalog.AddMissingGroups(fresh);fresh.Save();new ModProfile {Name=label,Brand="",Author="",Description="Generated from CAD.",Configuration="CAD vehicle",PreviewImage=""}.Save(fresh.ProfilePath);return fresh;
        }
        public static VehicleProject Open(string document)
        {
            if(string.IsNullOrWhiteSpace(document)||!File.Exists(document))throw new InvalidOperationException("Save the assembly before creating a vehicle project.");
            var path=PathFor(Path.GetFullPath(document));
            if(File.Exists(path))return Load(path);
            var profile=ModProfile.Load(ModProfile.DefaultPath);
            var project=new VehicleProject {SourceDocument=Path.GetFullPath(document),FilePath=path,Identity=ProjectIdentity.Create(profile.Name)};
            project.Save();
            // Missing old thumbnails must not prevent creation of a new project.
            if(!File.Exists(profile.PreviewImage))profile.PreviewImage="";
            profile.Save(project.ProfilePath);
            return project;
        }
        public static VehicleProject ForDocument(string document,string selectedPath)
        {
            if(File.Exists(selectedPath))
            {
                var selected=Load(selectedPath);
                if(string.Equals(selected.SourceDocument,document,StringComparison.OrdinalIgnoreCase))return selected;
            }
            return Open(document);
        }
        public void Save()
        {
            Identity.Validate();
            // Back up the on-disk version, even after an in-memory clone/migration.
            if(File.Exists(FilePath) && JsonFile.Read<VehicleProject>(FilePath).Version==2 && !File.Exists(FilePath+".v2.bak"))
                File.Copy(FilePath,FilePath+".v2.bak");
            if(Driveline!=null&&File.Exists(FilePath))
            {
                var oldVersion=JsonFile.Read<VehicleProject>(FilePath).Version;
                if(oldVersion<4&&!File.Exists(FilePath+".v"+oldVersion+".bak"))File.Copy(FilePath,FilePath+".v"+oldVersion+".bak");
            }
            Version=Driveline==null?Math.Max(3,Version):4;Driveline?.Normalize();JointWorkspace=JointWorkspace??new JointWorkspace();JointWorkspace.Normalize();JsonFile.Write(FilePath,this);
        }
        public void SelectBuild(string receipt)
        {
            var current=Load(FilePath);current.LastBuildReceipt=receipt;current.Save();LastBuildReceipt=receipt;
        }
        public void SelectFrameBuild(string receipt)
        {
            var current=Load(FilePath);current.FrameBuildReceipt=receipt;current.LastBuildReceipt=receipt;current.Save();
            FrameBuildReceipt=receipt;LastBuildReceipt=receipt;
        }
        public VehicleProject Fork(string path)
        {
            if(File.Exists(path))throw new IOException("Choose a new project filename.");
            var copy=Load(FilePath);copy.FilePath=Path.GetFullPath(path);
            var profile=ModProfile.Load(ProfilePath);copy.Identity=ProjectIdentity.Create(profile.Name);
            copy.LastBuildReceipt="";copy.FrameBuildReceipt="";copy.PhysicsBuildReceipt="";copy.PhysicsTemplateReceipt="";copy.Save();profile.Save(copy.ProfilePath);return copy;
        }
        public VehicleProject StartFresh(string path,MvpCatalog catalog,bool requiredGroups)
        {
            path=Path.GetFullPath(path);
            if(File.Exists(path)||File.Exists(path+".profile.json"))throw new IOException("Choose a new project filename. Existing projects are preserved.");
            var profile=ModProfile.Load(ProfilePath);
            var fresh=new VehicleProject {FilePath=path,SourceDocument=SourceDocument,Identity=ProjectIdentity.Create(profile.Name),
                MvpTemplates=MvpTemplates.Select(c=>new MvpTemplateChoice {Category=c.Category,Template=c.Template}).ToList()};
            if(requiredGroups)catalog.AddMissingGroups(fresh);
            fresh.Save();profile.Save(fresh.ProfilePath);return fresh;
        }
    }

    [DataContract] internal sealed class ComponentDefinition
    {
        public string Label=>Name+" ["+(string.IsNullOrEmpty(MvpRole)?Template:MvpRole)+"] | "+RepresentationLabel;
        public string RepresentationLabel=>Representation=="visual_only"?"Visual only · "+(MassPolicy=="exclude"?"mass excluded"+ (string.IsNullOrEmpty(MassAcknowledgement)?" — review required":""):MassPolicy=="custom"?CustomMassKg.ToString("G4")+" kg added to parent":SurfaceMassMode=="ignore"?"CAD solid mass; surface mass excluded"+(string.IsNullOrEmpty(MassAcknowledgement)?" — review required":""):"CAD mass added to parent"):MassPolicy=="exclude"?"Physical · zero mass — review required":MassPolicy=="custom"?"Physical · "+CustomMassKg.ToString("G4")+" kg":SurfaceMassMode=="ignore"?"Physical · excluded surface mass — review required":"Physical";
        public string AssignmentLabel=>Label+" | "+AssignmentSummary;
        public string AssignmentSummary {get;set;}="CAD: missing | Visual: missing";
        [DataMember] public string Id=Guid.NewGuid().ToString("N");
        [DataMember] public string Name="Component";
        [DataMember] public string Template="bulk";
        [DataMember] public string MvpRole="";
        [DataMember] public string Configuration;
        [DataMember] public List<SelectionReference> Selections=new List<SelectionReference>();
        [DataMember] public List<string> BodyIds=new List<string>();
        [DataMember] public string GeometryDirectory;
        [DataMember(EmitDefaultValue=false)] public string CadSourceDocument;
        [DataMember] public string AppearanceDirectory;
        [DataMember] public List<SelectionReference> AppearanceSelections=new List<SelectionReference>();
        [DataMember] public string AppearanceConfiguration;
        [DataMember(EmitDefaultValue=false)] public string AppearanceSourceDocument;
        [DataMember(EmitDefaultValue=false)] public string AppearancePackageState;
        [DataMember(EmitDefaultValue=false)] public string AppearancePackageError;
        [DataMember] public double[] AppearanceTransform;
        [DataMember(EmitDefaultValue=false)] public CoiloverAppearance AppearanceCoilover;
        [DataMember(EmitDefaultValue=false)] public SteeringAppearance SteeringAppearance;
        [DataMember(EmitDefaultValue=false)] public CoiloverSpring CoiloverSpring;
        [DataMember] public HullOptions Hull=new HullOptions();
        [DataMember] public double Spacing=0;
        [DataMember] public double Thickness=0;
        [DataMember] public string SurfaceMassMode="thickness";
        [DataMember] public string VisualParentId="";
        [DataMember] public string Representation="physical",MassPolicy="cad",VisualParentMemberId="",MassAcknowledgement="";
        [DataMember] public double CustomMassKg;
        [DataMember] public bool AutoConnectNormalFlip;
        [DataMember] public string Method="auto";
        [DataMember] public double Alpha=0;
        [DataMember] public double WrapOffset=0;
    }
    [DataContract] internal sealed class SteeringAppearance
    {
        [DataMember] public bool Enabled;
        [DataMember] public double[] Pivot,Axis,Up;
        [DataMember] public string SourceHash,FitMethod;
        [DataMember] public double Radius,FitResidual;
    }
    [DataContract] internal sealed class MountAnchor
    {
        public string Label=>Name+" ["+Status+"]";
        [DataMember] public string Id=Guid.NewGuid().ToString("N");
        [DataMember] public string Name="Mount";
        [DataMember] public string ComponentId;
        [DataMember] public string Kind="point";
        [DataMember] public List<string> References=new List<string>();
        [DataMember] public List<string> BodyReferences=new List<string>();
        [DataMember] public string ComponentReference;
        [DataMember(EmitDefaultValue=false)] public string CoordinateSpace;
        [DataMember] public double[] LocalPosition;
        [DataMember] public double[] Offset=new double[3];
        [DataMember] public double[] Position;
        [DataMember] public string Status="needs_repair";
        [DataMember(EmitDefaultValue=false)] public string GeneratedSource,GeometryHash;
    }
    [DataContract] internal sealed class MountConnection
    {
        public string Label=>Name+" ["+Template+"]";
        [DataMember] public string Id=Guid.NewGuid().ToString("N");
        [DataMember] public string Name="Attachment";
        [DataMember] public string AnchorA;
        [DataMember] public string AnchorB;
        [DataMember] public string Template="breakable_fastener";
        [DataMember] public double Spring=0;
        [DataMember] public double Damping=0;
        [DataMember] public double Strength=4000;
        // Empty means this fastener alone. Shared keys are explicit linked release sets.
        [DataMember] public string ReleaseSet="";
        [DataMember] public double AttachmentLength=0.006;
        [DataMember(EmitDefaultValue=false)] public string GeneratedSource,GeneratedKey,GeneratedHash;
        [DataMember] public bool UserEdited;
        [DataMember(EmitDefaultValue=false)] public double[] SupportPosition,Normal;
    }
}
