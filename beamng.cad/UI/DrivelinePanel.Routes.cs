using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed partial class DrivelinePanel
    {
        private sealed class Route
        {
            internal DriveDevice Source, Target;
            internal DrivePort Output, Input;
            internal readonly List<DriveShaft> Shafts = new List<DriveShaft>();
            internal readonly List<DriveConnection> Links = new List<DriveConnection>();
            internal string Issue, RepairEndpoint;
            internal string Label => Source.Name+" / "+Output.Name;
            internal bool IsSimple => Shafts.Count == 0 || Shafts.Count == 1 && Shafts[0].Representation == "ideal";
            public override string ToString()
            {
                string destination = Target == null ? "Choose input" : Target.Name+" / "+Input.Name;
                string path = Shafts.Count == 0 ? "Direct" : string.Join(", ", Shafts.Select(s=>s.Name+
                    (s.Representation=="ideal"?" (ideal)":" (detailed)")));
                return Label+" → "+destination+"    "+path+(Issue==null?"":"    • "+Issue);
            }
        }

        private static List<Route> Routes(Driveline graph)
        {
            var rows=new List<Route>();
            var requirements=graph.DatumRequirements();
            var visited=new HashSet<DriveDevice>();
            void Visit(DriveDevice source)
            {
                if(!visited.Add(source))return;
                foreach(var output in source.Ports.Where(p=>p.Direction=="output").OrderBy(p=>p.Index))
                {
                    var route=new Route {Source=source,Output=output};
                    rows.Add(route);
                    string current=output.Endpoint;
                    var seen=new HashSet<string>();
                    while(true)
                    {
                        if(!seen.Add(current)){route.Issue="Cycle";break;}
                        var endpoint=graph.Endpoints.FirstOrDefault(e=>e.Id==current);
                        if(endpoint==null){route.Issue="Missing port endpoint";break;}
                        var target=graph.Devices.FirstOrDefault(d=>d.Ports.Any(p=>p.Endpoint==current && p.Direction=="input"));
                        if(target!=null)
                        {
                            route.Target=target;
                            route.Input=target.Ports.First(p=>p.Endpoint==current && p.Direction=="input");
                            break;
                        }
                        var links=graph.Connections.Where(l=>l.Kind!="bearing" && (l.A==current || l.B==current) && !route.Links.Contains(l)).ToList();
                        var shafts=graph.Shafts.Where(s=>(s.A==current || s.B==current) && !route.Shafts.Contains(s)).ToList();
                        if(links.Count+shafts.Count!=1){route.Issue=links.Count+shafts.Count==0?"Open port":"Multiple connections";break;}
                        if(links.Count==1){var link=links[0];route.Links.Add(link);current=link.A==current?link.B:link.A;}
                        else{var shaft=shafts[0];route.Shafts.Add(shaft);current=shaft.A==current?shaft.B:shaft.A;}
                    }
                    if(route.Target==null)continue;
                    var unassigned=route.Shafts.FirstOrDefault(s=>string.IsNullOrEmpty(s.Component));
                    if(unassigned!=null)route.Issue="Assign CAD group for "+unassigned.Name;
                    foreach(var id in seen)
                    {
                        if(route.Issue!=null)break;
                        var endpoint=graph.Endpoints.FirstOrDefault(e=>e.Id==id);
                        if(endpoint==null)continue;
                        if(string.IsNullOrEmpty(endpoint.Component)){route.Issue="Assign CAD owner for "+endpoint.Name;break;}
                        requirements.TryGetValue(id,out var required);
                        bool centre=endpoint.Joint!=null || endpoint.Anchor!=null || endpoint.Position?.Length==3;
                        bool axis=endpoint.Joint!=null || endpoint.AxisAnchor!=null || endpoint.Axis?.Length==3;
                        if(required>0 && !centre || required==2 && !axis)
                        {
                            route.Issue="Capture "+endpoint.Name+(centre?" axis":" centre");route.RepairEndpoint=id;break;
                        }
                    }
                    Visit(route.Target);
                }
            }
            foreach(var device in graph.Devices.OrderBy(d=>d.Type=="engine"?0:1))Visit(device);
            return rows;
        }

        private void SelectRecord(string tab,object item)
        {
            tabs.SelectedTab=lists[tab].Parent as TabPage;
            if(item!=null)lists[tab].SelectedItem=item;
        }

        internal void SelectGraphIssue(string message)
        {
            if(draft==null || string.IsNullOrEmpty(message))return;
            foreach(var e in draft.Endpoints)
                if(message.Contains(e.Id+":")){SelectRecord("Endpoints",e);return;}
            foreach(var d in draft.Devices)
                if(message.Contains(d.Id+":")){SelectRecord("Devices",d);return;}
            foreach(var s in draft.Shafts)
                if(message.Contains(s.Id+":")){
                    if(s.Representation=="ideal")SelectRecord("Routes",lists["Routes"].Items.Cast<Route>().FirstOrDefault(r=>r.Shafts.Contains(s)));
                    else SelectRecord("Shafts",s);
                    return;
                }
            foreach(var l in draft.Connections)
                if(message.Contains(l.Id+":")){SelectRecord("Connections",l);return;}
        }

        private void CreateRoutesTab()
        {
            var page=new TabPage("Routes"){Name="Routes"};
            var list=new ListBox {Name="DrivelineRoutes",Dock=DockStyle.Fill,IntegralHeight=false,HorizontalScrollbar=true};
            lists.Add("Routes",list);page.Controls.Add(list);tabs.TabPages.Add(page);
            var actions=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
            Add(actions,"Connect ports",()=>RouteDialog(null));
            Add(actions,"Edit route",EditSelectedRoute);
            Add(actions,"Repair datum",()=>{
                var row=list.SelectedItem as Route;
                if(row?.RepairEndpoint!=null)SelectRecord("Endpoints",draft.Endpoints.First(e=>e.Id==row.RepairEndpoint));
                else if(row!=null && row.Output.Endpoint!=null)SelectRecord("Endpoints",draft.Endpoints.FirstOrDefault(e=>e.Id==row.Output.Endpoint));
            });
            Add(actions,"Detailed shaft",()=>SelectRecord("Shafts",null));
            Add(actions,"Remove route",()=>{
                var row=list.SelectedItem as Route;
                if(row==null)return;
                if(!row.IsSimple){SelectRecord("Connections",row.Links.FirstOrDefault());return;}
                var next=draft.Copy();
                RemoveRouteRecords(next,row);
                Adopt(next);
            });
            page.Controls.Add(actions);
            list.DoubleClick+=(sender,args)=>EditSelectedRoute();
            list.SelectedIndexChanged+=(sender,args)=>Describe(list.SelectedItem);
        }

        private static void RemoveRouteRecords(Driveline next,Route route)
        {
            next.Connections.RemoveAll(l=>route.Links.Any(old=>old.Id==l.Id));
            next.Shafts.RemoveAll(s=>route.Shafts.Any(old=>old.Id==s.Id));
            var ends=new HashSet<string>(route.Shafts.SelectMany(s=>new[]{s.A,s.B}));
            ends.ExceptWith(next.Devices.SelectMany(d=>d.Ports).Select(p=>p.Endpoint));
            ends.ExceptWith(next.Connections.SelectMany(l=>new[]{l.A,l.B}));
            ends.ExceptWith(next.Shafts.SelectMany(s=>new[]{s.A,s.B}));
            next.Endpoints.RemoveAll(e=>ends.Contains(e.Id));
        }

        private void EditSelectedRoute()
        {
            var route=Current?.SelectedItem as Route;
            if(route==null)return;
            if(!route.IsSimple){SelectRecord("Shafts",route.Shafts.First());return;}
            RouteDialog(route);
        }

        private void RouteDialog(Route original)
        {
            if(draft==null)throw new InvalidOperationException("Create a graph or convert the current layout first.");
            var shaft=original?.Shafts.FirstOrDefault();
            bool imported=shaft!=null && original.Links.Count>0;
            bool Used(string endpoint)=>draft.Connections.Any(l=>l.Kind!="bearing" && (l.A==endpoint || l.B==endpoint) && !(original?.Links.Contains(l)??false))
                || draft.Shafts.Any(s=>(s.A==endpoint || s.B==endpoint) && s!=shaft);
            var ports=draft.Devices.SelectMany(d=>d.Ports.Select(p=>new {Device=d,Port=p}))
                .Where(v=>draft.Endpoints.Any(e=>e.Id==v.Port.Endpoint) && !Used(v.Port.Endpoint)).ToList();
            var outputs=ports.Where(v=>v.Port.Direction=="output").ToList();
            if(outputs.Count==0)throw new InvalidOperationException("Add a device with an available output port.");
            using(var form=new Fields("Connect device ports"))
            {
                var output=form.Pick("Output",outputs.Select(v=>new Choice {Id=v.Port.Endpoint,Name=v.Device.Name+" / "+v.Port.Name}),original?.Output.Endpoint??outputs[0].Port.Endpoint);
                var input=form.Pick("Input",Enumerable.Empty<Choice>(),null);
                var existing=Routes(draft).Where(r=>r.Target!=null && r.Output.Endpoint!=original?.Output.Endpoint).ToList();
                bool Reaches(DriveDevice from,DriveDevice destination,HashSet<DriveDevice> visited)
                {
                    if(from==destination)return true;
                    return visited.Add(from) && existing.Where(r=>r.Source==from).Any(r=>Reaches(r.Target,destination,visited));
                }
                void Inputs()
                {
                    input.Items.Clear();
                    var source=outputs.First(v=>v.Port.Endpoint==Id(output)).Device;
                    foreach(var v in ports.Where(v=>v.Port.Direction=="input" && (v.Device.Type!="clutch" || source.Type=="engine") && !Reaches(v.Device,source,new HashSet<DriveDevice>())))
                        input.Items.Add(new Choice {Id=v.Port.Endpoint,Name=v.Device.Name+" / "+v.Port.Name});
                    input.SelectedItem=input.Items.Cast<Choice>().FirstOrDefault(c=>c.Id==original?.Input?.Endpoint)??input.Items.Cast<Choice>().FirstOrDefault();
                }
                Inputs();output.SelectedIndexChanged+=(s,e)=>Inputs();
                var available=project.Components.Where(c=>c.Representation!="visual_only" && c.MvpRole!="frame" && !draft.Devices.Any(d=>d.Component==c.Id) && !draft.Shafts.Any(s=>s!=shaft && s.Component==c.Id))
                    .Select(c=>new Choice {Id=c.Id,Name=c.Name}).ToList();
                var owner=form.Pick("CAD shaft",new[]{new Choice {Name="Direct torque connection"}}.Concat(available.Select(c=>new Choice {Id=c.Id,Name="Ideal shaft ("+c.Name+")"})),shaft?.Component);
                var bounded=form.Pick("Plunge",Options("Free","Bounded"),shaft?.HalfTravel>0?"Bounded":"Free");
                var travel=form.TextField("Half travel in each direction (m)",(shaft?.HalfTravel??0).ToString("R",CultureInfo.InvariantCulture));
                void TravelFields(){bool ideal=Id(owner)!=null;form.ShowField(bounded,ideal);form.ShowField(travel,ideal && Id(bounded)=="Bounded");}
                owner.SelectedIndexChanged+=(s,e)=>TravelFields();bounded.SelectedIndexChanged+=(s,e)=>TravelFields();TravelFields();
                output.Name="RouteOutput";input.Name="RouteInput";owner.Name="RouteOwner";
                bounded.Name="RoutePlunge";travel.Name="RouteHalfTravel";
                if(imported)owner.Enabled=false;
                if(form.ShowDialog(this)!=DialogResult.OK)return;
                var a=Id(output);var b=Id(input);var component=Id(owner);double halfTravel=0;
                if(a==null || b==null)throw new InvalidOperationException("Choose a compatible output and input.");
                if(component!=null && ports.Any(v=>v.Port.Endpoint==b && v.Device.Type=="clutch"))throw new InvalidOperationException("Connect the clutch directly to the engine.");
                if(component!=null && Id(bounded)=="Bounded" && (!double.TryParse(travel.Text,NumberStyles.Float,CultureInfo.InvariantCulture,out halfTravel) || !(halfTravel>0) || double.IsInfinity(halfTravel)))
                    throw new InvalidOperationException("Enter a positive finite half travel in metres.");
                if(shaft?.LegacyPlunge>0 && shaft.LegacyPlunge!=halfTravel)throw new InvalidOperationException("Preserve the original shaft half travel.");
                var next=draft.Copy();
                if(imported)
                {
                    string oldA=original.Output.Endpoint,oldB=original.Input?.Endpoint;
                    foreach(var link in next.Connections.Where(l=>original.Links.Any(old=>old.Id==l.Id)))
                    {
                        if(link.A==oldA)link.A=a;else if(link.A==oldB)link.A=b;
                        if(link.B==oldA)link.B=a;else if(link.B==oldB)link.B=b;
                    }
                }
                else if(original!=null)RemoveRouteRecords(next,original);
                if(component==null)
                {
                    if(shaft!=null)next.Shafts.RemoveAll(s=>s.Id==shaft.Id);
                    var link=new DriveConnection {A=a,B=b,Name="Torque connection",Kind=ports.First(v=>v.Port.Endpoint==a).Device.Component==ports.First(v=>v.Port.Endpoint==b).Device.Component?"internal":"direct"};
                    if(original?.Links.Count==1)link.Id=original.Links[0].Id;
                    next.Connections.Add(link);
                }
                else
                {
                    var item=imported?next.Shafts.First(s=>s.Id==shaft.Id):new DriveShaft();
                    if(shaft!=null){item.Id=shaft.Id;item.LegacyPlunge=shaft.LegacyPlunge;}
                    if(!imported){item.A=a;item.B=b;}
                    item.Component=component;item.Name=shaft?.Name??project.Components.First(c=>c.Id==component).Name;
                    item.Representation="ideal";item.HalfTravel=halfTravel;
                    if(!imported)next.Shafts.Add(item);
                    next.Version=2;
                }
                Adopt(next);
                lists["Routes"].SelectedItem=lists["Routes"].Items.Cast<Route>().FirstOrDefault(r=>r.Output.Endpoint==a);
            }
        }
    }
}
