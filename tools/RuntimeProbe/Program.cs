using Microsoft.Diagnostics.Runtime;

// Read-only live inspection: no suspension, injection, process control or heap writes.
using var target = DataTarget.AttachToProcess(int.Parse(args[0]), suspend: false);
foreach (var clr in target.ClrVersions)
{
    using var runtime = clr.CreateRuntime();
    foreach (var module in runtime.EnumerateModules())
        if (new[] { "TrueMesh", "beamng.cad", "Xarial", "System.Resources.Extensions", "System.Memory", "System.Buffers", "Unsafe" }
            .Any(n => (module.Name ?? "").Contains(n, StringComparison.OrdinalIgnoreCase)))
            Console.WriteLine("MODULE " + module.Name);
    foreach (var obj in runtime.Heap.EnumerateObjects())
    {
        if (!obj.IsValid) continue;
        var name = obj.Type?.Name ?? "";
        if (args.Contains("--workflow") && name == "BeamNG.Cad.UI.ComponentWorkflow")
        {
            Console.WriteLine("WORKFLOW " + obj.Address.ToString("x"));
            foreach (var key in new[] { "log", "status", "project", "settings", "cancel" })
            {
                var value = obj.ReadObjectField(key);
                Console.WriteLine("WORKFLOW_FIELD " + key + " " + value.Address.ToString("x"));
                if (!value.IsValid) continue;
                foreach (var field in value.Type.Fields.Where(f => f.ElementType == ClrElementType.String))
                {
                    var text = field.ReadString(value.Address, false);
                    if (!string.IsNullOrEmpty(text)) Console.WriteLine(key + "." + field.Name + "=" + text);
                }
            }
        }
        if (args.Contains("--workflow") && name.EndsWith("Exception"))
        {
            var evidence=obj.AsException().ToString();
            if(evidence.Contains("BeamNG.Cad"))Console.WriteLine("WORKFLOW_EXCEPTION "+evidence);
        }
        if (name == "BeamNG.Cad.MainSwAddIn" || name == "TrueMeshExporter.Sw.MainSwAddIn")
        {
            Console.WriteLine("ADDIN " + obj.Address.ToString("x"));
            foreach (var field in obj.Type.Fields)
                Console.WriteLine("FIELD " + field.Name + " " + field.Type?.Name);
        }
        if (name.EndsWith("Exception") && (name.Contains("FileNotFound") || name.Contains("FileLoad")
                || name.Contains("TargetInvocation") || name.Contains("TypeLoad") || name.Contains("MissingMethod")))
        {
            var error = obj.AsException();
            var text = error.ToString();
            if (new[] { "TrueMesh", "beamng.cad", "Xarial", "System.Resources", "System.Memory", "System.Buffers", "Unsafe" }
                .Any(n => text.Contains(n, StringComparison.OrdinalIgnoreCase)))
                Console.WriteLine("EXCEPTION " + text);
        }
    }
}
