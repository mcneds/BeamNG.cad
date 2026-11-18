using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Forms.Integration;
using System.Windows.Media;
using System.Windows.Media.Media3D;
using BeamNG.Cad.Preparation;
using Wpf=System.Windows;
using Input=System.Windows.Input;

namespace BeamNG.Cad.UI
{
    internal sealed partial class FramePreviewWindow : Form
    {
        private readonly ElementHost host=new ElementHost {Dock=DockStyle.Fill};
        private readonly GpuFramePreview gpu=new GpuFramePreview {Visible=false};
        private readonly Label backend=new Label {AutoSize=true,Dock=DockStyle.Bottom};
        private readonly ToolTip tips=new ToolTip();
        internal bool ForceCpuPreview=false;
        private bool gpuReady;
        private readonly System.Windows.Controls.Viewport3D viewport=new System.Windows.Controls.Viewport3D {IsHitTestVisible=false};
        private readonly ModelVisual3D visual=new ModelVisual3D();
        private readonly PerspectiveCamera camera=new PerspectiveCamera {FieldOfView=45,NearPlaneDistance=.001,FarPlaneDistance=100};
        private readonly Label state=new Label {AutoSize=true,Dock=DockStyle.Top,Text="Capture the saved frame to begin."};
        private readonly Label limits=new Label {AutoSize=true,Dock=DockStyle.Top,Text="Live hull estimate: GPU pruning proxy, requested grid, nearest-CAD projection, offset, bisect/mirror and weld. Proxy resolution and topology choices can differ from CGAL/Blender. Prepare actual hull to confirm."};
        private readonly CheckBox showSource=new CheckBox {Text="CAD",AutoSize=true,Checked=true};
        private readonly CheckBox showProxy=new CheckBox {Text="Approximation / prepared edges",AutoSize=true,Checked=true};
        private readonly CheckBox showVolume=new CheckBox {Text="Pruning volume",AutoSize=true,Enabled=false};
        private readonly System.Windows.Forms.Timer debounce=new System.Windows.Forms.Timer {Interval=80};
        private readonly SemaphoreSlim worker=new SemaphoreSlim(1,1);
        private CancellationTokenSource pending;
        private Point3D[] source;
        private HullOptions options;
        private PreviewGeometry.Scene scene;
        private int revision;
        private bool stopped;
        private double yaw=-.7,pitch=.45,distance=2;
        private Wpf.Point? drag;
        internal bool HasSnapshot=>source!=null;
        internal event Action RefreshRequested;
        internal event Action SettingsRequested;
        private readonly Button capturePreview=new Button {Name="PreviewCapture",Text="Start preview",AutoSize=true};
        internal event Action<string> Measured;

        public FramePreviewWindow()
            :this(null){}
        internal FramePreviewWindow(ExporterSettings candidateSettings)
        {
            this.candidateSettings=candidateSettings;
            Text="Frame live preview";Width=850;Height=650;MinimumSize=new System.Drawing.Size(420,360);ShowInTaskbar=false;
            var toolbar=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
            capturePreview.Click+=(s,e)=>RefreshRequested?.Invoke();
            var fit=new Button {Text="Fit view",AutoSize=true};fit.Click+=(s,e)=>ResetCamera();
            var stop=new Button {Text="Stop update",AutoSize=true};stop.Click+=(s,e)=>{CancelUpdate();state.Text="Preview update stopped. Change a setting or refresh CAD to resume.";};
            var details=new CheckBox {Text="Preview details",AutoSize=true};
            showProxy.Text="Hull";
            toolbar.Controls.AddRange(new Control[]{capturePreview,fit,stop,showSource,showProxy,showVolume,details});
            var help=new Label {AutoSize=true,Dock=DockStyle.Bottom,Text="Drag to orbit; wheel or +/− to zoom; arrows to orbit; Home to fit. Orange: approximation or prepared edges. Grey: captured CAD."};
            var views=new Panel {Dock=DockStyle.Fill};views.Controls.Add(host);views.Controls.Add(gpu);
            Controls.Add(views);Controls.Add(state);Controls.Add(limits);Controls.Add(toolbar);Controls.Add(help);Controls.Add(backend);
            InitializeSearch();
            // Keep the viewport usable in a narrow native task pane. Full diagnostics
            // and approximation limits remain available without taking its whole height.
            state.AutoSize=false;state.Height=38;state.AutoEllipsis=true;
            limits.Visible=help.Visible=backend.Visible=false;
            details.CheckedChanged+=(s,e)=>{
                limits.Visible=help.Visible=backend.Visible=details.Checked;
                state.AutoSize=details.Checked;if(!details.Checked)state.Height=38;
            };
            state.TextChanged+=(s,e)=>tips.SetToolTip(state,state.Text);
            tips.SetToolTip(showProxy,"Orange: projected preview grid or actual prepared hull edges. Prepare actual hull to confirm the estimate.");
            tips.SetToolTip(showSource,"Grey: captured CAD. Drag to orbit; scroll to zoom; Home to fit.");
            var surface=new System.Windows.Controls.Border {Background=new SolidColorBrush(Color.FromRgb(24,29,36)),Focusable=true,Child=viewport};
            host.Child=surface;viewport.Camera=camera;viewport.Children.Add(visual);
            RenderOptions.SetEdgeMode(viewport,EdgeMode.Aliased);
            surface.MouseLeftButtonDown+=(s,e)=>{surface.Focus();drag=e.GetPosition(surface);surface.CaptureMouse();};
            surface.MouseLeftButtonUp+=(s,e)=>{drag=null;surface.ReleaseMouseCapture();};
            surface.LostMouseCapture+=(s,e)=>drag=null;
            surface.MouseMove+=(s,e)=>{
                if(!drag.HasValue)return;var next=e.GetPosition(surface);
                yaw-=(next.X-drag.Value.X)*.01;pitch+=(next.Y-drag.Value.Y)*.01;drag=next;UpdateCamera();
            };
            surface.MouseWheel+=(s,e)=>{distance*=Math.Exp(-e.Delta/120.0*.12);UpdateCamera();e.Handled=true;};
            surface.KeyDown+=(s,e)=>{
                switch(e.Key){case Input.Key.Left:yaw-=.1;break;case Input.Key.Right:yaw+=.1;break;
                    case Input.Key.Up:pitch+=.1;break;case Input.Key.Down:pitch-=.1;break;
                    case Input.Key.Add:case Input.Key.OemPlus:distance*=.85;break;
                    case Input.Key.Subtract:case Input.Key.OemMinus:distance/=.85;break;
                    case Input.Key.Home:ResetCamera();e.Handled=true;return;default:return;}
                UpdateCamera();e.Handled=true;
            };
            showSource.CheckedChanged+=(s,e)=>Render();showProxy.CheckedChanged+=(s,e)=>Render();showVolume.CheckedChanged+=(s,e)=>Render();
            gpu.Failed+=message=>{if(!stopped&&gpuReady)BeginInvoke(new Action(()=>UseFallback(message)));};
            gpu.Timing+=message=>Measured?.Invoke(message);
            debounce.Tick+=(s,e)=>{debounce.Stop();UpdateProxy();};
            Resize+=(s,e)=>{foreach(var label in new[]{state,limits,help,backend})label.MaximumSize=new System.Drawing.Size(Math.Max(180,ClientSize.Width-16),0);};
            ResetCamera();
        }
        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            if(ForceCpuPreview){UseFallback("CPU fallback selected for verification.");return;}
            try{gpu.Initialize();gpuReady=true;backend.Text="GPU compute + direct rendering: "+gpu.Renderer;}
            catch(Exception error){UseFallback(error.Message);}
        }
        private void UseFallback(string reason)
        {
            if(stopped)return;
            CancelUpdate();gpuReady=false;gpu.Visible=false;host.Visible=true;
            UpdateVolumeAvailability();
            backend.Text="GPU compute unavailable: "+reason+" CPU approximation / "+((RenderCapability.Tier>>16)==0?"software viewport.":"WPF viewport.");
            limits.Text="CPU fallback: conservative triangle-box proxy and approximate alpha closing, followed by grid pruning, nearest-CAD projection, offset, bisect/mirror and weld. CGAL/Blender topology may differ.";
            if(source!=null)UpdateOptions(options);
        }
        private void ResetCamera(){yaw=-.7;pitch=.45;distance=2;UpdateCamera();gpu.ResetView();}
        private void UpdateCamera()
        {
            pitch=Math.Max(-1.45,Math.Min(1.45,pitch));distance=Math.Max(.15,Math.Min(20,distance));
            camera.Position=new Point3D(distance*Math.Cos(pitch)*Math.Cos(yaw),distance*Math.Cos(pitch)*Math.Sin(yaw),distance*Math.Sin(pitch));
            camera.LookDirection=new Vector3D(-camera.Position.X,-camera.Position.Y,-camera.Position.Z);camera.UpDirection=new Vector3D(0,0,1);
        }
        private void Render()
        {
            gpu.ShowSource=showSource.Checked;gpu.ShowProxy=showProxy.Checked;gpu.ShowVolume=showVolume.Checked;gpu.Invalidate();
            var group=new Model3DGroup();group.Children.Add(new AmbientLight(Colors.White));
            if(scene!=null)
            {
                if(showSource.Checked&&scene.Source!=null)group.Children.Add(Model(scene.Source,Color.FromArgb(90,170,185,200)));
                if(showProxy.Checked&&scene.Overlay!=null)group.Children.Add(Model(scene.Overlay,Color.FromArgb(150,255,165,40)));
            }
            group.Freeze();visual.Content=group;
        }
        private static GeometryModel3D Model(MeshGeometry3D mesh,Color color)
        {
            var material=new DiffuseMaterial(new SolidColorBrush(color));material.Freeze();
            return new GeometryModel3D(mesh,material){BackMaterial=material};
        }
        private void UpdateVolumeAvailability()
        {
            showVolume.Enabled=gpuReady&&gpu.Visible&&gpu.HasPruningVolume;
            showVolume.Text=showVolume.Enabled?"Pruning volume":"Pruning volume (not retained)";
            if(!gpuReady||!gpu.Visible||(gpu.HasResult&&!gpu.HasPruningVolume))showVolume.Checked=false;
            gpu.ShowVolume=showVolume.Checked;
            tips.SetToolTip(showVolume,showVolume.Enabled?"Show the coarse pruning volume for this approximation, before grid projection.":"Pruning volume is available for GPU live approximations. Checked/prepared hulls and the software view do not retain this intermediate volume.");
        }
        private void CancelUpdate(){revision++;debounce.Stop();pending?.Cancel();gpu.InvalidateResult();UpdateVolumeAvailability();}
        internal void SetSnapshot(Point3D[] points,HullOptions value)
        {
            capturePreview.Text="Refresh CAD";
            InvalidateSearch();
            source=points;scene=null;gpu.ClearSnapshot();Render();ResetCamera();UpdateOptions(value);
            searchMessage.Text="Preview captured. Choose Find sparse hull to search the current settings. Show current settings opens Hull settings.";
        }
        internal void UpdateOptions(HullOptions value)
        {
            InvalidateSearch();
            CancelUpdate();options=value;
            // Remove the old result immediately; no stale shape is presented as current.
            if(scene!=null)scene=new PreviewGeometry.Scene {Source=scene.Source,Center=scene.Center,Scale=scene.Scale};
            Render();
            if(source==null){state.Text="Prepared view is stale. Refresh CAD for a live approximation or prepare the hull again.";return;}
            state.Text="Settings changed — updating approximate preview…";debounce.Interval=gpuReady?80:250;debounce.Start();
        }
        internal void MarkStale(string reason)
        {
            capturePreview.Text="Start preview";
            InvalidateSearch();
            CancelUpdate();source=null;scene=null;gpu.ClearSnapshot();Render();state.Text=reason+" Refresh CAD to update the preview.";
        }
        internal void SetMessage(string text){if(!stopped)state.Text=text;}
        private async void UpdateProxy()
        {
            if(stopped||source==null)return;
            var version=revision;var input=source;var value=options;var local=new CancellationTokenSource();pending=local;
            var clock=Stopwatch.StartNew();bool entered=false;
            try
            {
                await worker.WaitAsync(local.Token);entered=true;
                value.Validate();
                if(gpuReady)
                {
                    host.Visible=false;gpu.Visible=true;gpu.BringToFront();
                    var message=await gpu.UpdateAsync(input,value,local.Token);
                    if(stopped||version!=revision){gpu.InvalidateResult();return;}
                    state.Text=message;UpdateVolumeAvailability();return;
                }
                var result=await Task.Run(()=>PreviewGeometry.Proxy(input,value,local.Token),local.Token);
                if(stopped||version!=revision)return;
                scene=result;Render();state.Text="Approximate preview · "+clock.ElapsedMilliseconds+" ms\r\n"+result.Summary;
                Measured?.Invoke("Live proxy update: "+clock.ElapsedMilliseconds+" ms. "+result.Summary);
            }
            catch(OperationCanceledException){}
            catch(System.IO.InvalidDataException error){if(!stopped&&version==revision)state.Text="Invalid preview settings: "+error.Message;}
            catch(Exception error){if(!stopped&&version==revision){if(gpuReady)UseFallback(error.Message);else state.Text="Preview unavailable: "+error.Message;}}
            finally{if(entered)worker.Release();if(ReferenceEquals(pending,local))pending=null;local.Dispose();}
        }
        internal Task ShowExactAsync(string file,CancellationToken token)
            =>PreviewUiThread.Run(this,async ()=>{await ShowExactCoreAsync(file,token);return true;});
        private async Task ShowExactCoreAsync(string file,CancellationToken token)
        {
            InvalidateSearch();
            CancelUpdate();var version=revision;var context=scene;
            using(var local=CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                pending=local;bool entered=false;
                try
                {
                    state.Text="Loading prepared hull into viewport…";
                    await worker.WaitAsync(local.Token);entered=true;
                    if(context==null&&source!=null)
                        context=await Task.Run(()=>PreviewGeometry.Proxy(source,options,local.Token),local.Token);
                    var result=await Task.Run(()=>PreviewGeometry.Exact(file,context,local.Token),local.Token);
                    if(stopped||version!=revision)return;
                    gpu.Visible=false;host.Visible=true;scene=result;Render();state.Text=result.Summary;UpdateVolumeAvailability();
                }
                finally{if(entered)worker.Release();if(ReferenceEquals(pending,local))pending=null;}
            }
        }
        protected override void Dispose(bool disposing)
        {
            if(disposing&&!stopped)
            {
                stopped=true;CancelUpdate();debounce.Dispose();tips.Dispose();source=null;scene=null;
                StopSearch();SearchControls?.Dispose();
                visual.Content=null;viewport.Children.Clear();host.Child=null;
                // In-flight tasks release the semaphore and their CTS themselves.
            }
            base.Dispose(disposing);
        }
    }
}
