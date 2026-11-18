using System.Collections.Generic;

namespace BeamNG.Cad.Preparation
{
    internal static class DrivelineTemplates
    {
        private static readonly string[] Corners = { "RR", "RL", "FL", "FR" };

        internal static IEnumerable<(string Key, string Label, string Role)> PreAuditOwners()
        {
            yield return ("engine", "Engine", "engine");
            yield return ("cvt", "CVT", "cvt");
            yield return ("gearbox", "Rear gearbox", "rear_final_drive");
            yield return ("rear_section", "Rear propshaft section", "front_propshaft");
            yield return ("front_section", "Front propshaft section", "front_propshaft");
            yield return ("front_diff", "Front differential", "front_diff");
            foreach (var corner in Corners)
            {
                yield return (corner + "_axle", corner + " halfshaft", corner.ToLowerInvariant() + "_halfshaft");
                yield return (corner + "_hub", corner + " wheel hub", corner.ToLowerInvariant() + "_wheel");
            }
        }

        internal static Driveline CreatePreAuditFourWheelDrive(
            IReadOnlyDictionary<string, string> owners, IReadOnlyDictionary<string, double> parameters)
        {
            var graph = new Driveline { Version = 2 };

            DriveEndpoint Endpoint(string name, string owner)
            {
                var endpoint = new DriveEndpoint { Name = name, Component = owner };
                graph.Endpoints.Add(endpoint);
                return endpoint;
            }

            DriveDevice Device(string name, string type, string ownerKey, string corner = null, params string[] outputs)
            {
                var device = new DriveDevice { Name = name, Type = type, Component = owners[ownerKey], Wheel = corner };
                void Port(string label, string direction, int index)
                {
                    var endpoint = Endpoint(name + " " + label, device.Component);
                    device.Ports.Add(new DrivePort { Name = label, Direction = direction, Index = index, Endpoint = endpoint.Id });
                }
                if (type != "engine") Port("Input", "input", 1);
                for (var i = 0; i < outputs.Length; i++) Port(outputs[i], "output", i + 1);
                graph.Devices.Add(device);
                return device;
            }

            void Link(string a, string b, string kind, string name) =>
                graph.Connections.Add(new DriveConnection { A = a, B = b, Kind = kind, Name = name });

            void Setting(DriveDevice device, string projectKey, string deviceKey)
            {
                if (parameters.TryGetValue(projectKey, out var value)) device.Parameters[deviceKey] = value;
            }

            var engine = Device("Engine", "engine", "engine", null, "Output");
            var cvt = Device("CVT", "cvt", "cvt", null, "Output");
            var gearbox = Device("Rear gearbox", "reduction", "gearbox", null, "Final reduction");
            var takeoff = Device("Gearbox takeoff", "splitter", "gearbox", null, "Rear drive", "Front drive");
            var rearDiff = Device("Gearbox rear differential", "differential", "gearbox", null, "RL output", "RR output");
            var frontOutput = Device("Gearbox front output", "reduction", "gearbox", null, "Propshaft output");
            var frontDiff = Device("Front differential", "differential", "front_diff", null, "FL output", "FR output");
            Setting(cvt, "cvt_min", "minGearRatio");
            Setting(cvt, "cvt_max", "maxGearRatio");
            Setting(gearbox, "rear_reduction", "gearRatio");
            Setting(frontOutput, "front_output_ratio", "gearRatio");
            Setting(frontDiff, "front_reduction", "gearRatio");

            Link(engine.Ports[0].Endpoint, cvt.Ports[0].Endpoint, "direct", "Engine to CVT");
            Link(cvt.Ports[1].Endpoint, gearbox.Ports[0].Endpoint, "direct", "CVT to rear gearbox");
            // These ports share the gearbox housing when one is assigned.
            var gearboxLink = gearbox.Component == null ? "direct" : "internal";
            Link(gearbox.Ports[1].Endpoint, takeoff.Ports[0].Endpoint, gearboxLink, "Gearbox to takeoff");
            Link(takeoff.Ports[1].Endpoint, rearDiff.Ports[0].Endpoint, gearboxLink, "Rear drive");
            Link(takeoff.Ports[2].Endpoint, frontOutput.Ports[0].Endpoint, gearboxLink, "Geared front output");

            string Section(string name, string key, string upstream, string joint)
            {
                var owner = owners[key];
                var a = Endpoint(name + " input end", owner);
                var b = Endpoint(name + " output end", owner);
                graph.Shafts.Add(new DriveShaft { Name = name, Component = owner, A = a.Id, B = b.Id, Representation = "detailed" });
                Link(upstream, a.Id, "spherical", joint);
                return b.Id;
            }

            var rearEnd = Section("Rear propshaft section", "rear_section", frontOutput.Ports[1].Endpoint, "Gearbox propshaft joint");
            var frontEnd = Section("Front propshaft section", "front_section", rearEnd, "Intermediate propshaft joint");
            Link(frontEnd, frontDiff.Ports[0].Endpoint, "spherical", "Front differential propshaft joint");

            foreach (var corner in Corners)
            {
                var wheel = Device(corner + " wheel hub", "wheel", corner + "_hub", corner);
                var diff = corner[0] == 'R' ? rearDiff : frontDiff;
                var port = diff.Ports[corner[1] == 'L' ? 1 : 2];
                graph.Shafts.Add(new DriveShaft
                {
                    Name = corner + " halfshaft", Component = owners[corner + "_axle"],
                    A = port.Endpoint, B = wheel.Ports[0].Endpoint, Representation = "ideal"
                });
            }
            return graph;
        }
    }
}
