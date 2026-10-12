using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace BeamNG.Cad.FramePipeline
{
    internal static class StaticFrameBuilder
    {
        public static Task<string> InstallAsync(string python, string receipt, string game, string mods, IProgress<string> progress)
            => InstallAsync(python, receipt, game, mods, progress, false);

        public static Task<string> InstallAsync(string python, string receipt, string game, string mods, IProgress<string> progress, bool reinstall)
        {
            if (!Path.IsPathRooted(python) || !File.Exists(python))
                throw new ArgumentException("Select a Python 3.10 or newer executable.");
            if (string.IsNullOrWhiteSpace(game) || string.IsNullOrWhiteSpace(mods))
                throw new ArgumentException("Set the BeamNG installation and mods folder in Settings first.");
            if (!File.Exists(receipt)) throw new FileNotFoundException("Select a completed frame build first.", receipt);
            var script = Path.Combine(Path.GetDirectoryName(typeof(StaticFrameBuilder).Assembly.Location),
                "FramePipeline", "build_static_frame.py");
            return Task.Run(() =>
            {
                var start = new ProcessStartInfo
                {
                    FileName = python, Arguments = "-X utf8 -E -s -u " + Quote(script) + " --install " + Quote(receipt)
                        + " --game " + Quote(game) + " --mods " + Quote(mods) + (reinstall ? " --reinstall" : ""),
                    UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
                };
                using (var process = new Process { StartInfo = start })
                {
                    process.OutputDataReceived += (sender, args) => { if (args.Data != null) progress?.Report(args.Data); };
                    process.ErrorDataReceived += (sender, args) => { if (args.Data != null) progress?.Report(args.Data); };
                    process.Start();
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    process.WaitForExit();
                    if (process.ExitCode != 0) throw new InvalidOperationException("Mod installation failed. See the log above.");
                }
                return Path.Combine(mods, "ak1di_mochi.zip");
            });
        }

        // Windows process arguments: quote each value without invoking a shell.
        internal static string Quote(string value)
        {
            var result = new StringBuilder("\"");
            var slashes = 0;
            foreach (var character in value)
            {
                if (character == '\\') { slashes++; continue; }
                result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
                result.Append(character);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }
    }
}
