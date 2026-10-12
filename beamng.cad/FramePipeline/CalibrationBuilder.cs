using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using BeamNG.Cad.UI;
namespace BeamNG.Cad.FramePipeline
{
    internal static class CalibrationBuilder
    {
        private sealed class ForwardProgress : IProgress<string>
        {
            private readonly Action<string> action;
            public ForwardProgress(Action<string> action){this.action=action;}
            public void Report(string value)=>action(value);
        }
        private static string Script=>Path.Combine(Path.GetDirectoryName(typeof(CalibrationBuilder).Assembly.Location),"FramePipeline","calibration_worker.py");
        private static string NewOutput(ExporterSettings settings,string prefix)=>Path.Combine(BuildStorage.EnsureDirectory(settings.FrameOutput),prefix+"-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,8));
        private static async Task Run(ExporterSettings settings,string args,IProgress<string> log,CancellationToken token,string job=null)
        {
            var python=settings.CalibrationPythonExecutable;
            if(!File.Exists(python))throw new InvalidOperationException("Set Calibration Python in Settings (Python 3.11+, NumPy, SciPy and Matplotlib).");
            var cancel=job==null?null:Path.Combine(job,"cancel-"+Guid.NewGuid().ToString("N")+".signal");
            var logGate=new object();
            var progress=new ForwardProgress(line=>{
                log?.Report(line);
                lock(logGate)if(job!=null&&Directory.Exists(job)){
                    try{File.AppendAllText(Path.Combine(job,"worker.log"),line+Environment.NewLine);}
                    catch(IOException e){log?.Report("Could not append worker log: "+e.Message);}
                }
            });
            try { await OwnedWorker.RunWithScratch(python,Script,args+(settings.SaveBuildReports=="true"?" --save-report":"")+(cancel==null?"":" --cancel-file "+OwnedWorker.Quote(cancel)),progress,token,cancel,settings.FrameOutput); }
            catch(InvalidOperationException e) { throw new InvalidOperationException(e.Message+(job==null?"":" Evidence: "+Path.Combine(job,"worker.log")),e); }
        }
        public static async Task<string> PrepareAsync(ExporterSettings settings,string source,IProgress<string> log,CancellationToken token)
        {
            var output=NewOutput(settings,"generation");
            var previous=Directory.Exists(settings.LastCalibrationGeneration)?" --previous "+OwnedWorker.Quote(settings.LastCalibrationGeneration):"";
            await Run(settings,"prepare --source "+OwnedWorker.Quote(source)+" --output "+OwnedWorker.Quote(output)+previous,log,token,output);
            return output;
        }
        public static Task CalibrateAsync(ExporterSettings settings,string job,IProgress<string> log,CancellationToken token)=>
            Run(settings,"calibrate --job "+OwnedWorker.Quote(job)+(Directory.Exists(Path.Combine(job,"study"))?" --resume":""),log,token,job);
        public static Task CalibrateSelectedAsync(ExporterSettings settings,string job,string material,IProgress<string> log,CancellationToken token)=>
            Run(settings,"calibrate --job "+OwnedWorker.Quote(job)+" --case "+OwnedWorker.Quote(material)+(Directory.Exists(Path.Combine(job,"study"))?" --resume":""),log,token,job);
        public static Task VerifySelectedAsync(ExporterSettings settings,string job,string material,IProgress<string> log,CancellationToken token,bool diagnostic=false)=>
            Run(settings,"verify --job "+OwnedWorker.Quote(job)+" --case "+OwnedWorker.Quote(material)+(diagnostic?" --diagnostic":"")+" --game "+OwnedWorker.Quote(settings.GameDirectory)+" --profile "+OwnedWorker.Quote(settings.HarnessProfile),log,token,job);
        public static Task VerifyModeAsync(ExporterSettings settings,string job,string material,string mode,IProgress<string> log,CancellationToken token,bool diagnostic=false)
        {
            if(mode!="quick" && mode!="full")throw new ArgumentException("Choose Quick check or Full verification.");
            return Run(settings,"verify --job "+OwnedWorker.Quote(job)+" --case "+OwnedWorker.Quote(material)+" --verification "+mode+(diagnostic?" --diagnostic":"")+" --game "+OwnedWorker.Quote(settings.GameDirectory)+" --profile "+OwnedWorker.Quote(settings.HarnessProfile),log,token,job);
        }
        public static Task VerifyAsync(ExporterSettings settings,string job,IProgress<string> log,CancellationToken token,bool diagnostic=false)=>
            Run(settings,"verify --job "+OwnedWorker.Quote(job)+(diagnostic?" --diagnostic":"")+" --game "+OwnedWorker.Quote(settings.GameDirectory)+" --profile "+OwnedWorker.Quote(settings.HarnessProfile),log,token,job);
        public static async Task<string> PackageAsync(ExporterSettings settings,string job,string material,IProgress<string> log,CancellationToken token)
        {
            var output=NewOutput(settings,"calibrated-frame");
            await Run(settings,"package --job "+OwnedWorker.Quote(job)+" --case "+OwnedWorker.Quote(material)+" --output "+OwnedWorker.Quote(output),log,token,job);
            var receipt=Path.Combine(output,"static_frame_build.json");
            if(File.Exists(ModProfile.DefaultPath))receipt=await ModPackage.CustomizeAsync(settings.CalibrationPythonExecutable,receipt,ModProfile.DefaultPath,log,token);
            return receipt;
        }
        public static async Task<string> PackageProjectAsync(ExporterSettings settings,string job,string material,BeamNG.Cad.Preparation.VehicleProject project,IProgress<string> log,CancellationToken token)
        {
            var output=NewOutput(settings,"calibrated-frame");
            await Run(settings,"package --job "+OwnedWorker.Quote(job)+" --case "+OwnedWorker.Quote(material)+" --output "+OwnedWorker.Quote(output),log,token,job);
            return await ModPackage.CustomizeForProjectAsync(settings.CalibrationPythonExecutable,Path.Combine(output,"static_frame_build.json"),project.ProfilePath,log,token,settings.FrameOutput,project.FilePath);
        }
    }
}
