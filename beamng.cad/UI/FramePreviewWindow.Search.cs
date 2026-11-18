using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Windows.Media.Media3D;
using BeamNG.Cad.Preparation;
using BeamNG.Cad.FramePipeline;

namespace BeamNG.Cad.UI
{
    internal sealed partial class FramePreviewWindow
    {
        private readonly ComboBox searchQuality=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Width=115};
        private readonly ListBox suggestions=new ListBox {Dock=DockStyle.Fill,HorizontalScrollbar=true,Name="HullSuggestions"};
        private readonly Label searchMessage=new Label {Dock=DockStyle.Bottom,Height=90,AutoEllipsis=true};
        private readonly Button findHull=new Button {Text="Find sparse hull",AutoSize=true};
        private readonly Button applyHull=new Button {Text="Apply",AutoSize=true,Enabled=false};
        private readonly Button checkHull=new Button {Text="Check selected",AutoSize=true,Enabled=false};
        private readonly Label applyStatus=new Label {Name="HullApplyStatus",Dock=DockStyle.Top,Height=62,AutoEllipsis=true};
        private CancellationTokenSource searchCancellation;
        private int searchVersion;
        private HullSearch search;
        private HullSearch.Candidate shownCandidate;
        private readonly ExporterSettings candidateSettings;
        private string checkSummary;
        internal bool IsOptimizing=>searchCancellation!=null;
        internal string SearchMessage=>searchMessage.Text;
        internal event Action<bool> SearchBusyChanged;
        internal event Action SearchOpened;
        internal event Action<HullOptions> ApplyRequested;
        internal event Action CheckContextRequested;
        internal Control SearchControls {get;private set;}
        internal void StopSearch()=>searchCancellation?.Cancel();
        private void InitializeSearch()
        {
            searchQuality.Items.AddRange(new object[]{"Coarser","Balanced","Finer"});searchQuality.SelectedIndex=1;
            searchQuality.SelectedIndexChanged+=(s,e)=>ReassessQuality();
            searchMessage.TextChanged+=(s,e)=>tips.SetToolTip(searchMessage,searchMessage.Text);
            var actions=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Top};
            var stopSearch=new Button {Text="Stop search/check",AutoSize=true};stopSearch.Click+=(s,e)=>StopSearch();
            var restore=new Button {Name="ShowHullSettings",Text="Show current settings",AutoSize=true};restore.Click+=(s,e)=>{StopSearch();SettingsRequested?.Invoke();shownCandidate=null;if(source!=null){CancelUpdate();UpdateProxy();}};
            var startPreview=new Button {Name="StartHullPreview",Text="Start / refresh preview",AutoSize=true};startPreview.Click+=(s,e)=>RefreshRequested?.Invoke();
            actions.Controls.AddRange(new Control[]{searchQuality,startPreview,findHull,stopSearch,checkHull,applyHull,restore});
            var panel=new Panel {Dock=DockStyle.Fill};panel.Controls.Add(suggestions);panel.Controls.Add(searchMessage);panel.Controls.Add(applyStatus);panel.Controls.Add(actions);SearchControls=panel;
            findHull.Click+=(s,e)=>StartSearch();checkHull.Click+=(s,e)=>CheckSelected();
            applyHull.Click+=(s,e)=>{var candidate=suggestions.SelectedItem as HullSearch.Candidate;if(candidate==null||IsOptimizing)return;var value=HullSearch.Copy(candidate.Options);ApplyRequested?.Invoke(value);};
            suggestions.SelectedIndexChanged+=(s,e)=>{if(stopped)return;UpdateCandidateActions();var candidate=suggestions.SelectedItem as HullSearch.Candidate;if(!IsOptimizing&&candidate!=null)ShowCandidate(candidate);};
            // A separate launch button leaves the action in reach when suggestions are hidden.
            var launch=new Button {Text="Find sparse hull",AutoSize=true};launch.Click+=(s,e)=>{SearchOpened?.Invoke();StartSearch();};
            var bar=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Bottom};bar.Controls.Add(launch);Controls.Add(bar);
            searchMessage.Text="Find a closed outer shell that bridges openings and preserves the main outline with fewer vertices. Candidate settings are applied only when you choose Apply.";
            UpdateCandidateActions();
        }
        private void InvalidateSearch()
        {
            searchVersion++;StopSearch();suggestions.Items.Clear();search=null;shownCandidate=null;checkSummary=null;applyHull.Enabled=checkHull.Enabled=false;
        }
        private void SearchBusy(bool value)
        {
            findHull.Enabled=searchQuality.Enabled=suggestions.Enabled=!value;
            UpdateCandidateActions();
            SearchBusyChanged?.Invoke(value);
        }
        private void UpdateCandidateActions()
        {
            var candidate=suggestions.SelectedItem as HullSearch.Candidate;
            applyHull.Enabled=!IsOptimizing&&candidate!=null;checkHull.Enabled=!IsOptimizing&&candidate!=null;
            applyHull.Text=candidate!=null&&!candidate.Accepted?"Apply anyway":"Apply";
            applyStatus.Text=IsOptimizing?"Search or checking is running. Settings remain unchanged.":candidate==null?"Select a candidate to see whether it meets the current quality target.":candidate.Eligibility(searchQuality.SelectedIndex);
            tips.SetToolTip(applyStatus,applyStatus.Text);
        }
        private void ReassessQuality()
        {
            if(stopped||IsOptimizing)return;
            var selected=suggestions.SelectedItem;var rows=suggestions.Items.Cast<HullSearch.Candidate>().ToArray();
            checkSummary="Quality changed. Existing meshes were reassessed; no Blender/CGAL work was rerun. Find sparse hull explores new candidates for this target.";
            suggestions.BeginUpdate();try{suggestions.Items.Clear();foreach(var candidate in rows){candidate.SetQuality(searchQuality.SelectedIndex);suggestions.Items.Add(candidate);}suggestions.SelectedItem=selected;}finally{suggestions.EndUpdate();}
            UpdateCandidateActions();if(selected==null)searchMessage.Text=checkSummary;
        }
        private void SearchStatus(string message){if(stopped)return;searchMessage.Text=message;state.Text=message;}
        private async void StartSearch()
        {
            try{await PreviewUiThread.Run(this,async ()=>{await SearchCoreAsync();return true;});}
            catch(OperationCanceledException){}
        }
        private async Task SearchCoreAsync()
        {
            if(IsOptimizing)return;
            if(source==null){SearchStatus("Choose Start preview above, or Start / refresh preview here, then Find sparse hull. Show current settings opens the Hull settings tab.");return;}
            try{options.Validate();CheckContextRequested?.Invoke();}catch(Exception error){SearchStatus(error.Message);return;}
            // Cancel only the pending live update; preserve the baseline viewport.
            revision++;debounce.Stop();pending?.Cancel();
            var local=new CancellationTokenSource();searchCancellation=local;int version=++searchVersion;var input=source;var initial=HullSearch.Copy(options);int quality=searchQuality.SelectedIndex;
            bool restoreCurrent=shownCandidate!=null;suggestions.Items.Clear();shownCandidate=null;SearchBusy(true);bool entered=false;
            try
            {
                await worker.WaitAsync(local.Token);entered=true;SearchStatus("Building fixed CAD silhouette reference…");
                if(restoreCurrent){if(gpuReady)await gpu.UpdateAsync(input,initial,local.Token);else{scene=await Task.Run(()=>PreviewGeometry.Proxy(input,initial,local.Token),local.Token);Render();}}
                var reference=await Task.Run(()=>new HullSearch(input,initial.Orientation,local.Token),local.Token);local.Token.ThrowIfCancellationRequested();if(version!=searchVersion)return;search=reference;
                // Populate the immutable GPU snapshot before starting the timed search.
                if(gpuReady)await gpu.PrepareSnapshotAsync(input,initial,local.Token);
                Func<HullOptions,CancellationToken,Task<PreviewHull.Result>> evaluate=async (value,token)=>{
                    if(gpuReady)return await gpu.EvaluateCandidateAsync(input,value,token);
                    var result=await Task.Run(()=>PreviewGeometry.Proxy(input,value,token),token);
                    return new PreviewHull.Result {Surface=result.Surface,Lines=result.Surface.Lines(),Points=result.Surface.Vertices,Faces=result.Surface.Triangles.Length/3};
                };
                double referenceCell=CpuCell(reference);
                Func<HullOptions,string> key=value=>gpuReady?gpu.ProxyKey(value):Math.Min(6,Math.Ceiling(1/value.ProxyDivisor/2/referenceCell))+":"+Math.Min(6,Math.Ceiling(1/value.ProxyDivisor/value.ProxyOffsetRatio/referenceCell));
                var results=await reference.RunAsync(initial,quality,evaluate,key,SearchStatus,local.Token);
                local.Token.ThrowIfCancellationRequested();CheckContextRequested?.Invoke();if(version!=searchVersion||stopped)return;
                foreach(var candidate in results)suggestions.Items.Add(candidate);
                SearchStatus((results.Any(c=>c.Accepted)?"Search complete. Select a candidate to preview; Check selected tests Blender/CGAL and offset ratio. Settings remain unchanged.":"No acceptable closed outer shell found within the search limits. Closest attempts are shown; adjust quality or current settings and retry.")+" Evaluated "+reference.Evaluations+" candidates in "+reference.ElapsedSeconds.ToString("0.0")+" s after snapshot setup.");
                Measured?.Invoke(searchMessage.Text);
            }
            catch(OperationCanceledException){if(!stopped&&version==searchVersion)SearchStatus("Search stopped. Current settings remain unchanged.");}
            catch(Exception error){Measured?.Invoke(error.ToString());if(!stopped&&version==searchVersion)SearchStatus("Hull search failed: "+error.Message);}
            finally{if(entered)worker.Release();if(ReferenceEquals(searchCancellation,local))searchCancellation=null;local.Dispose();if(!stopped)SearchBusy(false);}
        }
        private static double CpuCell(HullSearch reference)
        {var b=Rect3D.Empty;foreach(var p in reference.Mapped)b.Union(p);return Math.Max(b.SizeX,Math.Max(b.SizeY,b.SizeZ))/reference.Scale/38;}
        private void ShowCandidate(HullSearch.Candidate candidate)
        {
            if(source==null||search==null)return;shownCandidate=candidate;
            if(gpuReady){host.Visible=false;gpu.Visible=true;gpu.PresentCandidate(candidate.Preview??new PreviewHull.Result {Surface=candidate.Surface,Lines=candidate.Surface.Lines(),Points=candidate.Surface.Vertices,Faces=candidate.Surface.Triangles.Length/3});}
            else{gpu.Visible=false;host.Visible=true;scene=PreviewGeometry.Candidate(search,candidate.Surface,CancellationToken.None);Render();}
            UpdateVolumeAvailability();
            state.Text="Candidate—not applied · "+candidate;searchMessage.Text="Candidate—not applied. "+candidate+"\r\nAlpha divisor "+candidate.Options.ProxyDivisor.ToString("G4")+", weld "+candidate.Options.Weld.ToString("G4")+" m, offset ratio "+candidate.Options.ProxyOffsetRatio.ToString("G4")+". "+(candidate.Problem??"Prepare actual hull is required after Apply.")+(checkSummary==null?"":"\r\n"+checkSummary);
        }
        private async void CheckSelected()
        {
            try{await PreviewUiThread.Run(this,async ()=>{await CheckCoreAsync();return true;});}
            catch(OperationCanceledException){}
        }
        private async Task CheckCoreAsync()
        {
            var candidate=suggestions.SelectedItem as HullSearch.Candidate;if(candidate==null||IsOptimizing||search==null)return;
            try{CheckContextRequested?.Invoke();}catch(Exception error){SearchStatus(error.Message);return;}
            var reference=search;int version=searchVersion;int quality=searchQuality.SelectedIndex;var settings=candidateSettings??new ExporterSettings(null);
            var local=new CancellationTokenSource();searchCancellation=local;SearchBusy(true);bool entered=false;string report=null;string failure=null;
            try
            {
                await worker.WaitAsync(local.Token);entered=true;
                var directory=Path.Combine(BuildStorage.EnsureDirectory(settings.FrameOutput),"hull-search-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);
                var stl=Path.Combine(directory,"snapshot.stl");WriteSnapshot(stl,reference.Mapped);
                double ratio=candidate.Options.ProxyOffsetRatio;var ratios=new[]{Math.Max(.001,ratio/2),ratio,Math.Min(1000000,ratio*2)}.Distinct().ToArray();
                var job=Path.Combine(directory,"check-job.json");report=Path.Combine(directory,"check-results.json");
                var payload=new Dictionary<string,object>{{"frame",stl},{"hull",candidate.Options},{"ratios",ratios},{"blender",settings.BlenderExecutable},{"cgal",settings.CgalPythonExecutable}};
                File.WriteAllText(job,new JavaScriptSerializer().Serialize(payload));SearchStatus("Checking selected candidate with Blender/CGAL at "+ratios.Length+" offset ratios. Current settings remain unchanged.");
                var script=Path.Combine(Path.GetDirectoryName(typeof(FramePreviewWindow).Assembly.Location),"FramePipeline","preview_search_worker.py");
                await OwnedWorker.RunWithScratch(settings.PythonExecutable,script,"--job "+OwnedWorker.Quote(job),new SearchLog(this),local.Token,null,settings.FrameOutput);
            }
            catch(OperationCanceledException){failure="Check stopped; completed ratio checks retained.";}
            catch(Exception error){failure="Candidate check failed: "+error.Message;}
            finally
            {
                if(entered)worker.Release();
                try
                {
                    if(!stopped&&version==searchVersion&&report!=null&&File.Exists(report))
                    {
                        CheckContextRequested?.Invoke();var data=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(report));var records=(System.Collections.IEnumerable)data["results"];var checkedCandidates=new List<HullSearch.Candidate>();var errors=new List<string>();
                        foreach(Dictionary<string,object> record in records)
                        {
                            if(!Convert.ToBoolean(record["success"])){errors.Add(Convert.ToString(record["error"]));continue;}
                            try
                            {
                            var value=HullSearch.Copy(candidate.Options);value.ProxyOffsetRatio=Convert.ToDouble(record["ratio"]);
                            var mesh=PreviewSurface.ReadOff(Convert.ToString(record["off"]),reference.Center,reference.Scale,CancellationToken.None);
                            var result=await Task.Run(()=>reference.Score(value,mesh,quality,CancellationToken.None));result.Check="CGAL checked snapshot";checkedCandidates.Add(result);
                            }
                            catch(Exception error){errors.Add(error.Message);Measured?.Invoke("Candidate mesh rejected: "+error.Message);}
                        }
                        if(version==searchVersion&&!stopped)
                        {
                            foreach(var result in checkedCandidates)suggestions.Items.Add(result);
                            var best=HullSearch.Shortlist(checkedCandidates).FirstOrDefault(c=>c.Accepted);
                            checkSummary=(failure??"Candidate checks complete.")+" "+checkedCandidates.Count+" completed meshes; "+errors.Count+" failed ratios. "+(best==null?"No checked result met the outer-shell criteria.":"A checked candidate meets the criteria. Select it and Apply; fresh preparation is still required.");SearchStatus(checkSummary);Measured?.Invoke(checkSummary);
                            if(best!=null)suggestions.SelectedItem=best;
                        }
                    }
                    else if(!stopped&&version==searchVersion){checkSummary=failure??"No completed candidate checks.";SearchStatus(checkSummary);Measured?.Invoke(checkSummary);}
                }
                catch(Exception error){if(!stopped&&version==searchVersion)SearchStatus("Could not review candidate checks: "+error.Message);}
                if(ReferenceEquals(searchCancellation,local))searchCancellation=null;local.Dispose();if(!stopped){SearchBusy(false);if(suggestions.SelectedItem is HullSearch.Candidate selected)ShowCandidate(selected);}
            }
        }
        private sealed class SearchLog:IProgress<string>
        {
            private readonly FramePreviewWindow owner;internal SearchLog(FramePreviewWindow owner){this.owner=owner;}
            public void Report(string value){owner.Measured?.Invoke(value);if(value.StartsWith("Checking candidate ratio",StringComparison.Ordinal)&&!owner.stopped)try{owner.BeginInvoke(new Action(()=>owner.SearchStatus(value)));}catch(InvalidOperationException){}}
        }
        private static void WriteSnapshot(string file,Point3D[] points)
        {
            using(var writer=new BinaryWriter(File.Create(file))){writer.Write(new byte[80]);writer.Write((uint)(points.Length/3));for(int i=0;i<points.Length;i+=3){writer.Write(0f);writer.Write(0f);writer.Write(0f);for(int k=0;k<3;k++){var p=points[i+k];writer.Write((float)p.X);writer.Write((float)p.Y);writer.Write((float)p.Z);}writer.Write((ushort)0);}}
        }
    }
}
