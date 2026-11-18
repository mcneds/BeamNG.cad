using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;

namespace BeamNG.Cad.Preparation
{
    [DataContract] internal sealed class Driveline
    {
        [DataMember(Name="version")] public int Version {get;set;}=1;
        [DataMember(Name="devices")] public List<DriveDevice> Devices {get;set;}=new List<DriveDevice>();
        [DataMember(Name="endpoints")] public List<DriveEndpoint> Endpoints {get;set;}=new List<DriveEndpoint>();
        [DataMember(Name="shafts")] public List<DriveShaft> Shafts {get;set;}=new List<DriveShaft>();
        [DataMember(Name="connections")] public List<DriveConnection> Connections {get;set;}=new List<DriveConnection>();
        public static readonly string[] DeviceTypes={"engine","clutch","cvt","reduction","shaft","differential","splitter","wheel"};
        public static bool IsDriveRole(string role)=>new[]{"engine","cvt","front_diff","rear_diff","rear_final_drive","front_propshaft","cvt_output_shaft","shaft_carrier","drive_housing","drive_shaft","drive_carrier"}.Contains(role)||(role??"").EndsWith("_halfshaft",StringComparison.Ordinal);
        public Driveline Copy(){using(var stream=new MemoryStream()){var serializer=new DataContractJsonSerializer(typeof(Driveline));serializer.WriteObject(stream,this);stream.Position=0;return (Driveline)serializer.ReadObject(stream);}}
        public static Driveline Read(string path)=>FromJson(File.ReadAllText(path));
        public static Driveline FromJson(string json){using(var stream=new MemoryStream(System.Text.Encoding.UTF8.GetBytes(json))){var result=(Driveline)new DataContractJsonSerializer(typeof(Driveline),new DataContractJsonSerializerSettings {UseSimpleDictionaryFormat=true}).ReadObject(stream);result.Normalize();return result;}}
        public void Normalize()
        {
            if(Version!=1&&Version!=2)throw new InvalidDataException("Unsupported driveline graph version.");
            Devices=Devices??new List<DriveDevice>();Endpoints=Endpoints??new List<DriveEndpoint>();Shafts=Shafts??new List<DriveShaft>();Connections=Connections??new List<DriveConnection>();
            foreach(var device in Devices){if(string.IsNullOrWhiteSpace(device.Name))device.Name=device.Id??"Device";device.Ports=device.Ports??new List<DrivePort>();device.Parameters=device.Parameters??new Dictionary<string,double>();foreach(var port in device.Ports)if(string.IsNullOrWhiteSpace(port.Name))port.Name=port.Id??"Port";}
            foreach(var endpoint in Endpoints)if(string.IsNullOrWhiteSpace(endpoint.Name))endpoint.Name=endpoint.Id??"Endpoint";
            foreach(var shaft in Shafts)if(string.IsNullOrWhiteSpace(shaft.Name))shaft.Name=shaft.Id??"Shaft";
            foreach(var connection in Connections)if(string.IsNullOrWhiteSpace(connection.Name))connection.Name=connection.Id??"Connection";
        }
        // 1 = centre, 2 = centre and axis. Wheel datums can come from suspension.
        internal Dictionary<string,int> DatumRequirements()
        {
            var result=new Dictionary<string,int>();
            void Require(string id,int level){if(!string.IsNullOrEmpty(id))result[id]=Math.Max(result.TryGetValue(id,out var prior)?prior:0,level);}
            if(Version==1){foreach(var endpoint in Endpoints)Require(endpoint.Id,2);return result;}
            foreach(var shaft in Shafts){int level=shaft.Representation=="ideal"?1:2;Require(shaft.A,level);Require(shaft.B,level);}
            foreach(var link in Connections.Where(l=>l.Kind!="internal" && l.Kind!="direct"))
            {int level=link.Kind=="slider"?2:1;Require(link.A,level);Require(link.B,level);}
            foreach(var device in Devices.Where(d=>d.Type=="engine"))foreach(var port in device.Ports)Require(port.Endpoint,2);
            var outputs=new HashSet<string>(Devices.SelectMany(d=>d.Ports).Where(p=>p.Direction=="output").Select(p=>p.Endpoint));
            foreach(var wheel in Devices.Where(d=>d.Type=="wheel").SelectMany(d=>d.Ports))
            {
                var pending=new Stack<string>();var visited=new HashSet<string>();pending.Push(wheel.Endpoint);
                while(pending.Count>0){
                    var current=pending.Pop();
                    if(string.IsNullOrEmpty(current)||!visited.Add(current))continue;
                    if(outputs.Contains(current)){Require(current,2);continue;}
                    foreach(var shaft in Shafts.Where(s=>s.A==current||s.B==current))pending.Push(shaft.A==current?shaft.B:shaft.A);
                    foreach(var link in Connections.Where(l=>l.Kind!="bearing" && (l.A==current||l.B==current)))pending.Push(link.A==current?link.B:link.A);
                }
                if(wheel.Endpoint!=null)result.Remove(wheel.Endpoint);
            }
            return result;
        }

        public IEnumerable<string> ReferenceIssues(VehicleProject project)
        {
            var requirements=DatumRequirements();
            foreach(var endpoint in Endpoints)
            {
                requirements.TryGetValue(endpoint.Id,out var required);
                var owner=project.Components.FirstOrDefault(c=>c.Id==endpoint.Component);
                if(owner==null){yield return endpoint.Name+": missing CAD owner";continue;}
                if(ComponentAssignments.State(project,owner,false)!="saved")yield return endpoint.Name+": assign this assembly's physical CAD";
                if(Version==2 && endpoint.Position==null && endpoint.Axis==null && string.IsNullOrEmpty(endpoint.Anchor)&&string.IsNullOrEmpty(endpoint.AxisAnchor)&&string.IsNullOrEmpty(endpoint.Joint)){if(required>0)yield return endpoint.Name+(required==2?": capture centre and axis point":": capture centre");continue;}
                if(!string.IsNullOrEmpty(endpoint.Joint))
                {
                    var joint=project.JointWorkspace.Joints.FirstOrDefault(j=>j.Id==endpoint.Joint&&j.Status=="approved"&&string.IsNullOrEmpty(j.Issue)&&(j.Parent==owner.Id||j.Child==owner.Id));
                    if(joint?.Center?.Length!=3||(required==2&&joint.Axis?.Length!=3&&!project.Anchors.Any(a=>a.Id==endpoint.AxisAnchor&&a.ComponentId==owner.Id&&a.Status=="resolved")))yield return endpoint.Name+": review joint centre and capture axis point";
                }
                else if(!string.IsNullOrEmpty(endpoint.Anchor)||!string.IsNullOrEmpty(endpoint.AxisAnchor)){
                    foreach(var id in required==2 || !string.IsNullOrEmpty(endpoint.AxisAnchor)?new[]{endpoint.Anchor,endpoint.AxisAnchor}:new[]{endpoint.Anchor})
                        if(!project.Anchors.Any(a=>a.Id==id&&a.ComponentId==owner.Id&&a.Status=="resolved"))yield return endpoint.Name+": repair captured datum";
                }else if(required>0 && endpoint.Position?.Length!=3 || required==2 && endpoint.Axis?.Length!=3)yield return endpoint.Name+": complete the required datum";
            }
            if(Devices.Count(d=>d.Type=="engine")!=1||Devices.Count(d=>d.Type=="cvt")!=1)yield return "Declare one engine and one controlled CVT";
            if(!Devices.Any(d=>d.Type=="wheel"))yield return "Connect at least one wheel hub";
        }
    }
    [DataContract] internal sealed class DriveDevice
    {
        [DataMember(Name="id"),ReadOnly(true)] public string Id {get;set;}="device_"+Guid.NewGuid().ToString("N");
        [DataMember(Name="name")] public string Name {get;set;}="Device";
        [DataMember(Name="type")] public string Type {get;set;}="reduction";
        [DataMember(Name="component")] public string Component {get;set;}
        [DataMember(Name="wheel",EmitDefaultValue=false)] public string Wheel {get;set;}
        [DataMember(Name="ports")] public List<DrivePort> Ports {get;set;}=new List<DrivePort>();
        [DataMember(Name="parameters")] public Dictionary<string,double> Parameters {get;set;}=new Dictionary<string,double>();
        public override string ToString()=>Name+" ("+Type+")";
    }
    [DataContract] internal sealed class DrivePort
    {
        [DataMember(Name="id"),ReadOnly(true)] public string Id {get;set;}="port_"+Guid.NewGuid().ToString("N");
        [DataMember(Name="name")] public string Name {get;set;}="Port";
        [DataMember(Name="direction")] public string Direction {get;set;}="output";
        [DataMember(Name="index")] public int Index {get;set;}=1;
        [DataMember(Name="endpoint")] public string Endpoint {get;set;}
        public override string ToString()=>Name+" ("+Direction+" "+Index+")";
    }
    [DataContract] internal sealed class DriveEndpoint
    {
        [DataMember(Name="id"),ReadOnly(true)] public string Id {get;set;}="endpoint_"+Guid.NewGuid().ToString("N");
        [DataMember(Name="name")] public string Name {get;set;}="Endpoint";
        [DataMember(Name="component")] public string Component {get;set;}
        [DataMember(Name="member",EmitDefaultValue=false)] public string Member {get;set;}
        [DataMember(Name="anchor",EmitDefaultValue=false),ReadOnly(true)] public string Anchor {get;set;}
        [DataMember(Name="axis_anchor",EmitDefaultValue=false),ReadOnly(true)] public string AxisAnchor {get;set;}
        [DataMember(Name="joint",EmitDefaultValue=false),ReadOnly(true)] public string Joint {get;set;}
        [DataMember(Name="position",EmitDefaultValue=false),Browsable(false)] public double[] Position {get;set;}
        [DataMember(Name="axis",EmitDefaultValue=false),Browsable(false)] public double[] Axis {get;set;}
        public override string ToString()=>Name;
    }
    [DataContract] internal sealed class DriveShaft
    {
        [DataMember(Name="id"),ReadOnly(true)] public string Id {get;set;}="section_"+Guid.NewGuid().ToString("N");
        [DataMember(Name="name")] public string Name {get;set;}="Shaft section";
        [DataMember(Name="component")] public string Component {get;set;}
        [DataMember(Name="member",EmitDefaultValue=false)] public string Member {get;set;}
        [DataMember(Name="a")] public string A {get;set;}
        [DataMember(Name="b")] public string B {get;set;}
        [DataMember(Name="representation",EmitDefaultValue=false)] public string Representation {get;set;}
        [DataMember(Name="half_travel_m",EmitDefaultValue=false)] public double HalfTravel {get;set;}
        [DataMember(Name="legacy_plunge_m",EmitDefaultValue=false),ReadOnly(true)] public double LegacyPlunge {get;set;}
        public override string ToString()=>Name;
    }
    [DataContract] internal sealed class DriveConnection
    {
        [DataMember(Name="id"),ReadOnly(true)] public string Id {get;set;}="connection_"+Guid.NewGuid().ToString("N");
        [DataMember(Name="name")] public string Name {get;set;}="Joint";
        [DataMember(Name="a")] public string A {get;set;}
        [DataMember(Name="b")] public string B {get;set;}
        [DataMember(Name="kind")] public string Kind {get;set;}="spherical";
        [DataMember(Name="travel")] public double Travel {get;set;}
        public override string ToString()=>Name+" ("+Kind+")";
    }
}
