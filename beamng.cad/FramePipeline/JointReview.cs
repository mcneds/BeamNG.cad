using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using BeamNG.Cad.Preparation;
using BeamNG.Cad.UI;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.FramePipeline
{
    internal static class JointReview
    {
        // Used by both build entry points. A scan saved before a CAD edit or
        // reopen is never treated as evidence about the current native mates.
        public static async Task Refresh(ISldWorks app,ModelDoc2 model,VehicleProject project,ExporterSettings settings,
            IProgress<string> progress,CancellationToken token)
        {
            var oldPlacements=project.JointWorkspace.Placements;
            var mates=await new NativeMateScanner(app,model,project).Capture(s=>progress?.Report(s),token);
            var stamp=model.GetUpdateStamp();var config=model.ConfigurationManager.ActiveConfiguration.Name;
            var workspace=project.JointWorkspace;var old=workspace.Mates;workspace.Mates=mates;
            var root=BuildStorage.EnsureDirectory(settings.FrameOutput);
            var snapshot=Path.Combine(root,"joint-job-"+Guid.NewGuid().ToString("N")+".json");var output=snapshot+".result";
            try
            {
                JsonFile.Write(snapshot,project);
                var worker=Path.Combine(Path.GetDirectoryName(typeof(JointReview).Assembly.Location),"FramePipeline","component_worker.py");
                await OwnedWorker.RunWithScratch(settings.CalibrationPythonExecutable,worker,
                    "joint-scan --project "+OwnedWorker.Quote(snapshot)+" --output "+OwnedWorker.Quote(output),progress,token,null,root);
                if(model.GetUpdateStamp()!=stamp||model.ConfigurationManager.ActiveConfiguration.Name!=config)
                    throw new InvalidOperationException("CAD changed during mate analysis. Scan again after the rebuild finishes.");
                var joints=JsonFile.Read<List<JointDefinition>>(output);
                workspace.Joints=joints;workspace.ScanDocument=model.GetPathName();workspace.ScanConfiguration=config;
                workspace.ScanStamp=stamp;workspace.ScanHash=ModPackage.Hash(output);
                project.Save();
            }
            catch {workspace.Mates=old;workspace.Placements=oldPlacements;throw;}
            finally {if(File.Exists(snapshot))File.Delete(snapshot);if(File.Exists(output))File.Delete(output);}
        }
    }
}
