using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.Preparation
{
    // Only automated work belongs in this scope. Native dialogs and the owned
    // workflow/progress window remain outside the SolidWorks frame's redraw lock.
    internal sealed class MaterialUiUpdateScope : IDisposable
    {
        private sealed class TreeState
        {
            public FeatureManager Manager;
            public bool Updates, Enabled;
        }
        [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr window,uint message,IntPtr wParam,IntPtr lParam);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr window);
        [DllImport("user32.dll",CharSet=CharSet.Unicode)] private static extern IntPtr GetProp(IntPtr window,string name);
        [DllImport("user32.dll")] private static extern bool RedrawWindow(IntPtr window,IntPtr rectangle,IntPtr region,uint flags);
        private readonly ISldWorks app;
        private readonly IntPtr frame;
        private readonly bool commandInProgress;
        private readonly Dictionary<ModelDoc2,TreeState> trees=new Dictionary<ModelDoc2,TreeState>();
        private readonly Dictionary<IntPtr,Tuple<ModelView,bool>> views=new Dictionary<IntPtr,Tuple<ModelView,bool>>();
        private bool ownsRedraw,disposed;
        private MaterialWorkCover cover;

        public MaterialUiUpdateScope(ISldWorks app)
        {
            this.app=app;
            commandInProgress=app.CommandInProgress;
            frame=new IntPtr(((Frame)app.Frame()).GetHWndx64());
            try
            {
                // Do not accidentally show an already hidden window or undo
                // another operation's redraw lock.
                if(IsWindowVisible(frame) && GetProp(frame,"SysSetRedraw")==IntPtr.Zero)
                {
                    ownsRedraw=true;
                    SendMessage(frame,0x000B,IntPtr.Zero,IntPtr.Zero); // WM_SETREDRAW
                }
                app.CommandInProgress=true;
            }
            catch { Dispose();throw; }
        }

        public void Track(ModelDoc2 document)
        {
            if(disposed || document==null)return;
            app.CommandInProgress=true;
            HoldRedraw();
            if(!trees.ContainsKey(document))
            {
                var manager=document.FeatureManager;
                var state=new TreeState {Manager=manager,Updates=manager.EnableFeatureTree,Enabled=manager.EnableFeatureTreeWindow};
                trees.Add(document,state);
            }
            trees[document].Manager.EnableFeatureTreeWindow=false;
            trees[document].Manager.EnableFeatureTree=false;
            // Activation can create a view that did not exist while the source
            // part was loaded only as an assembly dependency.
            var view=document.ActiveView as ModelView;
            if(view!=null)
            {
                var handle=new IntPtr(view.GetViewHWndx64());
                if(!views.ContainsKey(handle))views.Add(handle,Tuple.Create(view,view.EnableGraphicsUpdate));
                view.EnableGraphicsUpdate=false;
            }
        }

        public void CoverDocumentTransitions()
        {
            if(!disposed && ownsRedraw && cover==null)cover=new MaterialWorkCover(frame);
        }
        public void SetStatus(string text) { cover?.SetStatus(text);HoldRedraw(); }
        public void ReleaseForRebuild()
        {
            // Native rebuilds must run with normal update/command state. The
            // cover remains visible while SolidWorks updates the source part.
            RestoreDocumentUpdates();
            app.CommandInProgress=commandInProgress;
            ReleaseRedrawForVisibility();
        }
        public void ReleaseRedrawForVisibility()
        {
            // SolidWorks treats child documents as already hidden while their
            // parent frame has WM_SETREDRAW disabled, so Visible=false can be a
            // no-op. Keep the cover up while restoring actual document windows.
            if(!disposed && ownsRedraw)SendMessage(frame,0x000B,new IntPtr(1),IntPtr.Zero);
        }
        private void HoldRedraw()
        {
            // Activation and rebuilds can re-enable redraw inside SolidWorks.
            // The cover protects the transition; re-arm the lock afterward.
            if(!disposed && ownsRedraw)SendMessage(frame,0x000B,IntPtr.Zero,IntPtr.Zero);
        }

        public void RestoreDocumentUpdates()
        {
            var failures=new List<string>();
            foreach(var pair in views)
                try { if(IsWindow(pair.Key))pair.Value.Item1.EnableGraphicsUpdate=pair.Value.Item2; } catch(Exception e) { failures.Add(e.Message); }
            foreach(var state in trees.Values)
            {
                try { state.Manager.EnableFeatureTree=state.Updates; } catch(Exception e) { failures.Add(e.Message); }
                try { state.Manager.EnableFeatureTreeWindow=state.Enabled; } catch(Exception e) { failures.Add(e.Message); }
            }
            // Keep the original snapshots through visibility restoration, which
            // can reset graphics again. A second Track must not replace them
            // with an intermediate disabled state. Window identity also avoids
            // saving the same native view twice through different COM wrappers.
            if(failures.Count>0)throw new InvalidOperationException(string.Join("; ",failures));
        }

        public void Dispose()
        {
            if(disposed)return;
            disposed=true;
            var failures=new List<string>();
            try { RestoreDocumentUpdates(); } catch(Exception e) { failures.Add(e.Message); }
            try { app.CommandInProgress=commandInProgress; } catch(Exception e) { failures.Add(e.Message); }
            // Always release frame painting, even if a document was closed or
            // another native cleanup step failed.
            if(ownsRedraw && IsWindow(frame))
            {
                SendMessage(frame,0x000B,new IntPtr(1),IntPtr.Zero);
                RedrawWindow(frame,IntPtr.Zero,IntPtr.Zero,0x0001|0x0004|0x0080|0x0100|0x0400);
            }
            try { cover?.Dispose(); } catch(Exception e) { failures.Add(e.Message); }
            if(failures.Count>0)throw new InvalidOperationException("Could not fully restore SolidWorks display updates: "+string.Join("; ",failures));
        }
    }
}
