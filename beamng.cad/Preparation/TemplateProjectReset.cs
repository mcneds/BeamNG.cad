using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using BeamNG.Cad.FramePipeline;

namespace BeamNG.Cad.Preparation
{
    // Stage the reset in memory. Worker failure/cancellation must leave the
    // on-disk project untouched; only a completed fork may be committed.
    internal sealed class TemplateProjectReset
    {
        private readonly string path;
        private readonly byte[] original;
        public VehicleProject Candidate {get;}
        public string BackupPath {get;private set;}
        public TemplateProjectReset(string projectPath)
        {
            path=Path.GetFullPath(projectPath);original=File.ReadAllBytes(path);
            Candidate=VehicleProject.Load(path);
            var receipt=Candidate.PhysicsTemplateReceipt;
            if(string.IsNullOrWhiteSpace(receipt))throw new InvalidOperationException("This project has no imported physics template to reset to.");
            ModPackage.ArchivePath(receipt);
            var baseline=JsonFile.Read<VehicleProject>(Path.Combine(Path.GetDirectoryName(receipt),"project.snapshot.json"));
            if((baseline.Version!=2&&baseline.Version!=3&&baseline.Version!=4)||baseline.Components==null||baseline.Components.Count==0)
                throw new InvalidDataException("The template has no supported component snapshot.");
            Candidate.Components=baseline.Components;
            Candidate.Driveline=baseline.Driveline?.Copy();
            Candidate.MvpTemplates=baseline.MvpTemplates??new List<MvpTemplateChoice>();
            Candidate.TemplateDefinitionPath=baseline.TemplateDefinitionPath;
            Candidate.FrameBuildReceipt=baseline.FrameBuildReceipt;
            Candidate.LastBuildReceipt="";Candidate.PhysicsBuildReceipt="";
            Candidate.Anchors=new List<MountAnchor>();Candidate.Connections=new List<MountConnection>();
            // Identity, source document, template source and profile stay with
            // the user's project. All component edits come from the baseline.
        }
        public void Commit(string output)
        {
            var receipt=Path.Combine(output,"static_frame_build.json");
            ModPackage.ArchivePath(receipt);
            var record=JsonFile.Read<ModBuildRecord>(receipt);
            if(record.identity?.Id!=Candidate.Identity.Id||record.identity?.Namespace!=Candidate.Identity.Namespace)
                throw new InvalidDataException("Reset package belongs to a different project.");
            if(string.IsNullOrWhiteSpace(record.parent_receipt)||!string.Equals(Path.GetFullPath(record.parent_receipt),Path.GetFullPath(Candidate.PhysicsTemplateReceipt),StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Reset package was not created from the imported template.");
            var definition=Path.Combine(output,"provenance","template-definition.json");
            if(!File.Exists(definition))throw new InvalidDataException("The reset package has no template hardpoint definition.");
            if(!original.SequenceEqual(File.ReadAllBytes(path)))
                throw new InvalidOperationException("The project changed during reset. Its current assignments were preserved; retry the reset.");
            var stamp=DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,8);
            var backups=path+".template-reset-backups";Directory.CreateDirectory(backups);
            BackupPath=Path.Combine(backups,stamp+".json");File.WriteAllBytes(BackupPath,original);
            var local=path+".template-"+stamp+".json";File.Copy(definition,local);
            Candidate.TemplateDefinitionPath=local;
            Candidate.LastBuildReceipt=receipt;Candidate.PhysicsBuildReceipt=receipt;
            Candidate.Save(); // JsonFile uses a temporary file and atomic replace.
        }
    }
}
