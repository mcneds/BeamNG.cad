using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
namespace BeamNG.Cad.FramePipeline
{
    // Gate the Python worker on stdin until it belongs to our kill-on-close job.
    // This prevents Blender/CGAL children escaping cancellation during process startup.
    internal static class OwnedWorker
    {
        public static Task Run(string python, string script, string arguments, IProgress<string> log, CancellationToken token, string cancelFile = null)
            => RunWithScratch(python,script,arguments,log,token,cancelFile,null);
        public static Task RunWithScratch(string python, string script, string arguments, IProgress<string> log, CancellationToken token, string cancelFile, string scratchRoot)
        {
            return Task.Run(() => {
                token.ThrowIfCancellationRequested();
                // run_path on a file does not add its directory to sys.path as
                // direct script execution does. Workers import sibling modules.
                var bootstrap = "import sys,runpy,os;sys.stdin.readline();sys.argv=sys.argv[1:];sys.path.insert(0,os.path.dirname(os.path.abspath(sys.argv[0])));runpy.run_path(sys.argv[0],run_name='__main__')";
                var start = new ProcessStartInfo(python, "-X utf8 -u -c " + Quote(bootstrap) + " " + Quote(script) + " " + arguments)
                { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
                if(scratchRoot!=null)BuildStorage.ConfigureScratch(start,scratchRoot);
                using (var job = new ProcessJob())
                using (var process = new Process { StartInfo = start })
                {
                    string errorDetail = null;
                    process.OutputDataReceived += (s,e) => { if (e.Data != null) log?.Report(e.Data); };
                    process.ErrorDataReceived += (s,e) => { if (e.Data != null) {
                        log?.Report(e.Data);
                        if(e.Data.StartsWith("RuntimeError:") || e.Data.StartsWith("ValueError:") || e.Data.StartsWith("FileNotFoundError:") || e.Data.StartsWith("ImportError:") || e.Data.StartsWith("ModuleNotFoundError:")) errorDetail=e.Data;
                    } };
                    process.Start();
                    try { job.Assign(process.Handle); }
                    catch { process.Kill(); throw; }
                    process.BeginOutputReadLine(); process.BeginErrorReadLine();
                    using (token.Register(() => {
                        if(cancelFile==null){job.Terminate();return;}
                        try{File.WriteAllText(cancelFile,"cancel");}catch{job.Terminate();return;}
                        // Let the harness close its owned Drive process and save cancellation evidence.
                        ThreadPool.QueueUserWorkItem(_=> {Thread.Sleep(15000);try{if(!process.HasExited)job.Terminate();}catch(InvalidOperationException){} });
                    }))
                    {
                        token.ThrowIfCancellationRequested();
                        process.StandardInput.WriteLine("GO"); process.StandardInput.Close();
                        process.WaitForExit();
                    }
                    token.ThrowIfCancellationRequested();
                    if (process.ExitCode != 0) throw new InvalidOperationException(errorDetail ?? ("Worker failed (exit " + process.ExitCode + "). See the generation log for details."));
                }
            }, token);
        }
        internal static string Quote(string value) => StaticFrameBuilder.Quote(value);
        private sealed class ProcessJob : IDisposable
        {
            private IntPtr handle;
            public ProcessJob()
            {
                handle = CreateJobObject(IntPtr.Zero, null);
                if (handle == IntPtr.Zero) throw new Win32Exception();
                var limits = new Extended { Basic = new Basic { Flags = 0x2000 } };
                if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(limits)))
                { Dispose(); throw new Win32Exception(); }
            }
            public void Assign(IntPtr process) { if (!AssignProcessToJobObject(handle, process)) throw new Win32Exception(); }
            public void Terminate() { if (handle != IntPtr.Zero) TerminateJobObject(handle, 1); }
            public void Dispose() { if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; } }
            [StructLayout(LayoutKind.Sequential)] private struct Basic { public long ProcessTime, JobTime; public uint Flags; public UIntPtr Min, Max; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling; }
            [StructLayout(LayoutKind.Sequential)] private struct Io { public ulong Read, Write, Other, ReadBytes, WriteBytes, OtherBytes; }
            [StructLayout(LayoutKind.Sequential)] private struct Extended { public Basic Basic; public Io Io; public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob; }
            [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] private static extern IntPtr CreateJobObject(IntPtr attrs, string name);
            [DllImport("kernel32.dll", SetLastError=true)] private static extern bool SetInformationJobObject(IntPtr job, int kind, ref Extended value, uint size);
            [DllImport("kernel32.dll", SetLastError=true)] private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
            [DllImport("kernel32.dll")] private static extern bool TerminateJobObject(IntPtr job, uint exit);
            [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr value);
        }
    }
}
