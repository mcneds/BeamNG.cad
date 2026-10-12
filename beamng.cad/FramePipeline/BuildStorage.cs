using System;
using System.Diagnostics;
using System.IO;

namespace BeamNG.Cad.FramePipeline
{
    internal static class BuildStorage
    {
        public static string EnsureDirectory(string path)
        {
            if(string.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path) || !Path.IsPathRooted(Path.GetPathRoot(path)) || Path.GetPathRoot(path).Length<3)
                throw new ArgumentException("Choose a full build directory path, such as H:\\beamng project programs\\builds.");
            var full=Path.GetFullPath(path);
            Directory.CreateDirectory(full);
            var probe=Path.Combine(full,".write-check-"+Guid.NewGuid().ToString("N"));
            using(var file=new FileStream(probe,FileMode.CreateNew,FileAccess.Write,FileShare.None,1,FileOptions.DeleteOnClose))file.WriteByte(0);
            return full;
        }
        public static void ConfigureScratch(ProcessStartInfo start,string root)
        {
            var scratch=EnsureDirectory(Path.Combine(EnsureDirectory(root),"scratch"));
            start.EnvironmentVariables["TEMP"]=scratch;
            start.EnvironmentVariables["TMP"]=scratch;
            start.EnvironmentVariables["TMPDIR"]=scratch;
            start.EnvironmentVariables["MPLCONFIGDIR"]=Path.Combine(scratch,"matplotlib");
        }
    }
}
