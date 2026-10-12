using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace BeamNG.Cad.Preparation
{
    internal sealed class NativeMaterialChoice
    {
        public string Database;
        public string Name;
    }

    internal sealed class BulkMaterialResult
    {
        public readonly List<string> Applied = new List<string>();
        public readonly List<string> Remaining = new List<string>();
        public string Error;
        public bool Cancelled;
        public int RebuildCount;
        public readonly List<string> Diagnostics = new List<string>();
        public string Summary => (Cancelled ? "Cancelled. " : "") + Applied.Count + " bodies assigned; " + Remaining.Count + " remaining."
            + (Error == null ? "" : " " + Error);
    }

    // All COM access stays on the SolidWorks UI thread. Only the native picker edits
    // the scratch document; it never receives a selection from the user's assembly.
    internal sealed class BulkMaterialAssignment : IDisposable
    {
        private sealed class Target
        {
            public ModelDoc2 Part;
            public string Configuration, Name, Label;
            public byte[] Reference;
        }
        private readonly ISldWorks app;
        private readonly ModelDoc2 assembly;
        private readonly string assemblyConfiguration;
        private readonly List<Target> targets = new List<Target>();
        private readonly Dictionary<ModelDoc2,string> configurations = new Dictionary<ModelDoc2,string>();
        private readonly Dictionary<ModelDoc2,bool> visibility = new Dictionary<ModelDoc2,bool>();
        private readonly HashSet<ModelDoc2> touched = new HashSet<ModelDoc2>();
        private readonly Dictionary<ModelDoc2,List<Tuple<byte[],int>>> partSelections = new Dictionary<ModelDoc2,List<Tuple<byte[],int>>>();
        private readonly List<Tuple<byte[],int>> selection = new List<Tuple<byte[],int>>();
        private bool disposed;
        private bool contextDirty;
        private MaterialUiUpdateScope quietUi;
        public int Count => targets.Count;
        public Action<string> Status { get; set; }

        public BulkMaterialAssignment(ISldWorks app, ModelDoc2 assembly, List<Tuple<Component2,Body2>> bodies)
        {
            this.app=app;this.assembly=assembly;
            assemblyConfiguration=assembly.ConfigurationManager.ActiveConfiguration.Name;
            var manager=(SelectionMgr)assembly.SelectionManager;
            for(var i=1;i<=manager.GetSelectedObjectCount2(-1);i++)
            {
                var reference=assembly.Extension.GetPersistReference3(manager.GetSelectedObject6(i,-1)) as byte[];
                if(reference==null || reference.Length==0)
                    throw new InvalidOperationException("The current selection cannot be restored. Clear it before using the saved-frame material action.");
                selection.Add(Tuple.Create(reference,manager.GetSelectedObjectMark(i)));
            }
            // Capture names/configurations before switching any source configuration:
            // assembly-context Body2 objects can become stale during that switch.
            foreach(var pair in bodies)
            {
                if(pair.Item2.GetType()!=(int)swBodyType_e.swSolidBody)
                    throw new InvalidOperationException("Material assignment requires solid bodies: "+pair.Item2.Name);
                var part=pair.Item1.GetModelDoc2() as ModelDoc2;
                if(!(part is PartDoc))throw new InvalidOperationException("Resolve component: "+pair.Item1.Name2);
                if(part.IsOpenedReadOnly() || (!string.IsNullOrEmpty(part.GetPathName()) && File.Exists(part.GetPathName()) &&
                    (File.GetAttributes(part.GetPathName()) & FileAttributes.ReadOnly)!=0))
                    throw new InvalidOperationException("Part is read-only: "+part.GetTitle());
                if(!configurations.ContainsKey(part))
                {
                    configurations.Add(part,part.ConfigurationManager.ActiveConfiguration.Name);
                    visibility.Add(part,part.Visible);
                    var saved=new List<Tuple<byte[],int>>();
                    var selected=(SelectionMgr)part.SelectionManager;
                    for(var i=1;i<=selected.GetSelectedObjectCount2(-1);i++)
                    {
                        var reference=part.Extension.GetPersistReference3(selected.GetSelectedObject6(i,-1)) as byte[];
                        if(reference==null || reference.Length==0)throw new InvalidOperationException("Clear the nonpersistent selection in "+part.GetTitle()+" before assigning materials.");
                        saved.Add(Tuple.Create(reference,selected.GetSelectedObjectMark(i)));
                    }
                    partSelections.Add(part,saved);
                }
                var config=pair.Item1.ReferencedConfiguration;
                var name=pair.Item2.Name;
                if(!targets.Any(t=>t.Part==part && t.Configuration==config && t.Name==name))
                    targets.Add(new Target {Part=part,Configuration=config,Name=name,Label=part.GetTitle()+" / "+config+" / "+name});
            }
            if(targets.Count==0)throw new InvalidOperationException("No solid bodies selected.");
            // Keep each source configuration together, including interleaved picks.
            var ordered=targets.GroupBy(t=>Tuple.Create(t.Part,t.Configuration)).SelectMany(g=>g).ToList();
            targets.Clear();targets.AddRange(ordered);
            using(quietUi=new MaterialUiUpdateScope(app))
            {
                quietUi.Track(assembly);
                try
                {
                    foreach(var group in targets.GroupBy(t=>Tuple.Create(t.Part,t.Configuration)))
                    {
                        // Reading already loaded source bodies needs no foreground
                        // activation, body selection, or document window.
                        if(group.Key.Item1.ConfigurationManager.ActiveConfiguration.Name!=group.Key.Item2)
                            Activate(group.Key.Item1,group.Key.Item2);
                        var sourceBodies=(((PartDoc)group.Key.Item1).GetBodies2((int)swBodyType_e.swSolidBody,false) as object[] ?? new object[0])
                            .Cast<Body2>().ToLookup(b=>b.Name);
                        foreach(var target in group)
                        {
                            var matches=sourceBodies[target.Name].ToArray();
                            if(matches.Length!=1)throw new InvalidOperationException("No unique source body for "+target.Label);
                            target.Reference=target.Part.Extension.GetPersistReference3(matches[0]) as byte[];
                            if(target.Reference==null || target.Reference.Length==0)throw new InvalidOperationException("Cannot retain body reference: "+target.Label);
                        }
                    }
                }
                finally { Restore(); }
            }
        }

        private void Activate(ModelDoc2 doc,string configuration)
        {
            contextDirty=true;
            if(configurations.ContainsKey(doc))touched.Add(doc);
            quietUi?.Track(doc);
            if(app.ActiveDoc!=doc)
            {
                quietUi?.CoverDocumentTransitions();
                int error=0;
                if(app.ActivateDoc3(doc.GetTitle(),false,(int)swRebuildOnActivation_e.swDontRebuildActiveDoc,ref error)==null)
                    throw new InvalidOperationException("Cannot activate "+doc.GetTitle()+" ("+error+").");
            }
            quietUi?.Track(doc);
            if(doc.ConfigurationManager.ActiveConfiguration.Name!=configuration && !doc.ShowConfiguration2(configuration))
                throw new InvalidOperationException("Cannot activate configuration "+configuration+" in "+doc.GetTitle());
        }

        // Kept separate from the picker so assignment/readback is integration-testable
        // without driving dialog controls or requiring the material to be calibratable.
        public async Task<BulkMaterialResult> ApplyAsync(NativeMaterialChoice material, Action<int,int,string> progress, CancellationToken token)
        {
            if(disposed)throw new ObjectDisposedException(nameof(BulkMaterialAssignment));
            if(material==null || string.IsNullOrWhiteSpace(material.Name))throw new ArgumentException("Choose a material first.");
            var database=ResolveDatabase(app,material.Database);
            // IBody2 documents database filenames registered in Material Databases.
            var databaseName=Path.GetFileName(database);
            if(!string.Equals(ResolveDatabase(app,databaseName),database,StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("The selected material database is not uniquely registered in SolidWorks: "+database);
            var result=new BulkMaterialResult();
            result.Remaining.AddRange(targets.Select(t=>t.Label));
            var elapsed=Stopwatch.StartNew();
            try
            {
                quietUi=new MaterialUiUpdateScope(app);
                quietUi.Track(assembly);
                foreach(var group in targets.GroupBy(t=>Tuple.Create(t.Part,t.Configuration)))
                {
                    token.ThrowIfCancellationRequested();
                    var part=group.Key.Item1;
                    var configuration=group.Key.Item2;
                    Activate(part,configuration);
                    var stage=Stopwatch.StartNew();
                    foreach(var target in group)
                    {
                        token.ThrowIfCancellationRequested();
                        if(target.Part.IsOpenedReadOnly())throw new InvalidOperationException("Part became read-only: "+target.Label);
                        int error;
                        var body=target.Part.Extension.GetObjectByPersistReference3(target.Reference,out error) as Body2;
                        if(body==null || error!=0)throw new InvalidOperationException("Body reference is stale: "+target.Label);
                        // The native setter can return NoError without assigning an
                        // unselected body. Establish explicit part/body editing scope.
                        if(!body.Select2(false,null))throw new InvalidOperationException("Cannot select source body: "+target.Label);
                        var status=body.SetMaterialProperty(target.Configuration,databaseName,material.Name);
                        if(status!=1)throw new InvalidOperationException("SolidWorks rejected "+target.Label+" (material status "+status+").");
                        VerifyMaterial(target,material,database);
                        target.Part.SetSaveFlag();
                        result.Applied.Add(target.Label);result.Remaining.Remove(target.Label);
                        quietUi.Track(target.Part);
                        quietUi.SetStatus("Assigning "+material.Name+": "+result.Applied.Count+" / "+targets.Count+" bodies verified");
                        progress?.Invoke(result.Applied.Count,targets.Count,target.Label);
                        // Yield to the WinForms/SolidWorks message pump, never Task.Run(COM).
                        await Task.Delay(1);
                    }
                    result.Diagnostics.Add(part.GetTitle()+" / "+configuration+": assignment/readback "+stage.ElapsedMilliseconds+" ms.");
                    token.ThrowIfCancellationRequested();
                    if(part.ConfigurationManager.ActiveConfiguration.NeedsRebuild)
                    {
                        ReportStatus("Updating changed features in "+part.GetTitle()+" / "+configuration+"...");
                        await Task.Delay(1);
                        token.ThrowIfCancellationRequested();
                        // A rebuild can replace bodies. Do not retain pre-rebuild
                        // confirmations if it fails or the references become stale.
                        foreach(var target in group)
                        {
                            result.Applied.Remove(target.Label);
                            if(!result.Remaining.Contains(target.Label))result.Remaining.Add(target.Label);
                        }
                        quietUi.ReleaseForRebuild();
                        stage.Restart();
                        try
                        {
                            result.RebuildCount++;
                            if(!part.EditRebuild3())throw new InvalidOperationException("Rebuild failed for "+part.GetTitle()+" / "+configuration+"; material assignments are not confirmed.");
                        }
                        finally
                        {
                            result.Diagnostics.Add(part.GetTitle()+" / "+configuration+": conditional rebuild "+stage.ElapsedMilliseconds+" ms.");
                            quietUi.Track(part);
                        }
                        ReportStatus("Verifying materials in "+part.GetTitle()+" / "+configuration+"...");
                        stage.Restart();
                        foreach(var target in group)
                        {
                            VerifyMaterial(target,material,database);
                            result.Applied.Add(target.Label);result.Remaining.Remove(target.Label);
                        }
                        result.Diagnostics.Add(part.GetTitle()+" / "+configuration+": post-rebuild verification "+stage.ElapsedMilliseconds+" ms.");
                    }
                }
            }
            catch(OperationCanceledException) { result.Cancelled=true; }
            catch(Exception e) { result.Error=e.Message; }
            finally
            {
                // Status observers must not prevent native cleanup.
                try { quietUi?.SetStatus("Restoring assembly view..."); } catch(Exception e) { result.Error=(result.Error+" "+e.Message).Trim(); }
                try { Status?.Invoke("Restoring assembly view..."); } catch(Exception e) { result.Error=(result.Error+" "+e.Message).Trim(); }
                try { Restore(); }
                catch(Exception e) { result.Error=(result.Error+" Restore failed: "+e.Message).Trim(); }
                try { quietUi?.Dispose(); }
                catch(Exception e) { result.Error=(result.Error+" "+e.Message).Trim(); }
                result.Diagnostics.Add("Material assignment total: "+elapsed.ElapsedMilliseconds+" ms; "+result.RebuildCount+" conditional rebuilds.");
            }
            return result;
        }

        private void ReportStatus(string message)
        {
            quietUi?.SetStatus(message);
            Status?.Invoke(message);
        }

        private void VerifyMaterial(Target target,NativeMaterialChoice material,string database)
        {
            int error;
            var body=target.Part.Extension.GetObjectByPersistReference3(target.Reference,out error) as Body2;
            if(body==null || error!=0)throw new InvalidOperationException("Body unavailable after material assignment: "+target.Label);
            string actualDatabase;
            var actual=body.GetMaterialPropertyName(target.Configuration,out actualDatabase);
            if(actual!=material.Name || !string.Equals(ResolveDatabase(app,actualDatabase),database,StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Assignment could not be verified for "+target.Label+"; this body may have changed. Read back '"+actual+"' from '"+actualDatabase+"', expected '"+material.Name+"' from '"+database+"'.");
        }

        internal static string ResolveDatabase(ISldWorks app,string database)
        {
            if(!string.IsNullOrWhiteSpace(database) && Path.IsPathRooted(database) && File.Exists(database))return Path.GetFullPath(database);
            var known=app.GetMaterialDatabases() as System.Collections.IEnumerable;
            var paths=(known?.Cast<string>() ?? Enumerable.Empty<string>()).Where(p=>File.Exists(p) &&
                (string.Equals(Path.GetFileName(p),Path.GetFileName(database),StringComparison.OrdinalIgnoreCase) ||
                 string.Equals(Path.GetFileNameWithoutExtension(p),database,StringComparison.OrdinalIgnoreCase)))
                .Select(Path.GetFullPath).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
            if(paths.Length!=1)throw new InvalidOperationException("Material database is unavailable or ambiguous: "+database);
            return paths[0];
        }

        public Task<NativeMaterialChoice> PickAsync(Control dispatcher)
        {
            if(disposed)throw new ObjectDisposedException(nameof(BulkMaterialAssignment));
            var completion=new TaskCompletionSource<NativeMaterialChoice>();
            ModelDoc2 scratch=null;
            var events=(DSldWorksEvents_Event)app;
            DSldWorksEvents_CommandCloseNotifyEventHandler handler=null;
            var finished=false;
            Action<Exception> finish=error=>
            {
                if(finished)return;
                finished=true;
                NativeMaterialChoice choice=null;
                try
                {
                    if(error==null && scratch!=null)
                    {
                        string database;
                        var name=((PartDoc)scratch).GetMaterialPropertyName2(scratch.ConfigurationManager.ActiveConfiguration.Name,out database);
                        if(!string.IsNullOrWhiteSpace(name))choice=new NativeMaterialChoice {Name=name,Database=ResolveDatabase(app,database)};
                    }
                }
                catch(Exception e) { error=e; }
                finally
                {
                    if(handler!=null)events.CommandCloseNotify-=handler;
                    try
                    {
                        using(quietUi=new MaterialUiUpdateScope(app))
                        {
                            quietUi.CoverDocumentTransitions();
                            // Do not track the scratch document: it is about to
                            // be closed and has no display state to restore.
                            try { if(scratch!=null)app.CloseDoc(scratch.GetTitle()); }
                            finally { Restore(); }
                        }
                    }
                    catch(Exception e) { error=error??e; }
                }
                if(error!=null)completion.TrySetException(error);else completion.TrySetResult(choice);
            };
            try
            {
                contextDirty=true;
                scratch=(ModelDoc2)app.NewDocument(app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart),0,0,0);
                if(scratch==null)throw new InvalidOperationException("Configure a default SolidWorks part template to use the material picker.");
                ((PartDoc)scratch).SetMaterialPropertyName2(scratch.ConfigurationManager.ActiveConfiguration.Name,"","");
                string ignored;
                if(!string.IsNullOrEmpty(((PartDoc)scratch).GetMaterialPropertyName2(scratch.ConfigurationManager.ActiveConfiguration.Name,out ignored)))
                    throw new InvalidOperationException("Could not clear the temporary part's default material.");
                handler=(command,reason)=>
                {
                    if(command==501)dispatcher.BeginInvoke(new Action(()=>finish(null)));
                    return 0;
                };
                events.CommandCloseNotify+=handler;
                if(!app.RunCommand(501,""))finish(new InvalidOperationException("SolidWorks could not open its material picker."));
            }
            catch(Exception e) { finish(e); }
            return completion.Task;
        }

        private void Restore()
        {
            if(!contextDirty)return;
            var failures=new List<string>();
            foreach(var part in touched.ToArray())
                try { Activate(part,configurations[part]);RestoreSelection(part,partSelections[part]); } catch(Exception e) { failures.Add(e.Message); }
            try
            {
                Activate(assembly,assemblyConfiguration);
                RestoreSelection(assembly,selection);
            }
            catch(Exception e) { failures.Add(e.Message); }
            // Restore view flags before hiding windows created by activation;
            // their native view handles may disappear when hidden.
            try { quietUi?.RestoreDocumentUpdates(); } catch(Exception e) { failures.Add(e.Message); }
            quietUi?.ReleaseRedrawForVisibility();
            foreach(var part in touched)
                // Visible can read false solely because frame redraw is disabled.
                // Always restore the saved document visibility explicitly.
                try { part.Visible=visibility[part]; } catch(Exception e) { failures.Add(e.Message); }
            try
            {
                Activate(assembly,assemblyConfiguration);
                RestoreSelection(assembly,selection);
            }
            catch(Exception e) { failures.Add(e.Message); }
            if(failures.Count>0)throw new InvalidOperationException(string.Join("\r\n",failures));
            touched.Clear();
            contextDirty=false;
        }

        private static void RestoreSelection(ModelDoc2 document,List<Tuple<byte[],int>> saved)
        {
            document.ClearSelection2(true);
            var manager=(SelectionMgr)document.SelectionManager;
            foreach(var item in saved)
            {
                int error;
                var obj=document.Extension.GetObjectByPersistReference3(item.Item1,out error);
                if(obj==null || error!=0)throw new InvalidOperationException("An original selection is no longer available.");
                var data=manager.CreateSelectData();data.Mark=item.Item2;
                var selected=obj is Body2 body ? body.Select2(true,data)
                    : obj is Component2 component ? component.Select4(true,data,false)
                    : obj is Entity entity ? entity.Select4(true,data)
                    : obj is Feature feature ? feature.Select2(true,item.Item2)
                    : manager.AddSelectionListObject(obj,data);
                if(!selected)throw new InvalidOperationException("Could not restore an original selection.");
            }
        }

        public void Dispose()
        {
            if(disposed)return;
            disposed=true;
            if(contextDirty)using(quietUi=new MaterialUiUpdateScope(app))Restore();
        }
    }
}
