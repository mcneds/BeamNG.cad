using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Media.Media3D;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    // GPU proxy approximation followed by background CPU grid/pruning/projection
    // and topology, then GPU edge rendering. Never used by the actual generator.
    internal sealed class GpuFramePreview : Control
    {
        internal const int Resolution=64,MaxRadius=6;
        private const uint Storage=0x90D2;
        private const uint Barrier=0x2000|0x40|0x200; // shader-storage + indirect command + buffer readback
        private PreviewGl gl;
        private uint compute,render,vao,vertices,seeds,scratchA,scratchB,faces,draw,lines,displayVolume;
        private bool volumeReady;
        internal bool HasPruningVolume=>hasResult&&volumeReady;
        private PreviewHull hull;
        private PreviewHull.Result projected;
        private bool evaluating;
        private PreviewHull.Result evaluated;
        private readonly System.Collections.Generic.Dictionary<string,uint[]> proxyCache=new System.Collections.Generic.Dictionary<string,uint[]>();
        internal string ProxyKey(HullOptions value)=>Math.Min(MaxRadius,Math.Ceiling(1/value.ProxyDivisor/2/cell))+":"+Math.Min(MaxRadius,Math.Ceiling(1/value.ProxyDivisor/value.ProxyOffsetRatio/cell));
        internal Task<bool> PrepareSnapshotAsync(Point3D[] source,HullOptions value,CancellationToken token)
            =>PreviewUiThread.Run(this,async ()=>{Initialize();if(!ReferenceEquals(source,cached)||orientation!=value.Orientation)await UploadSnapshot(source,value,token);return true;});
        // Caller owns the preview worker gate. Evaluation does not replace displayed buffers.
        internal Task<PreviewHull.Result> EvaluateCandidateAsync(Point3D[] source,HullOptions value,CancellationToken token)
            =>PreviewUiThread.Run(this,async ()=>{evaluating=true;try{await UpdateCoreAsync(source,value,token);return evaluated;}finally{evaluating=false;}});
        internal void PresentCandidate(PreviewHull.Result result)
        {
            using(gl.Current())
            {
                gl.Upload(lines,result.Lines,result.Lines.Length*4);
                volumeReady=result.PruningVolume!=null;
                if(volumeReady)
                {
                    gl.Upload(displayVolume,result.PruningVolume,result.PruningVolume.Length*4);
                    gl.Upload(draw,new uint[]{0,1,0,0},16);
                    Common(compute);Int(compute,"mode",3);gl.BindBufferBase(Storage,1,displayVolume);
                    gl.DispatchCompute(Resolution*Resolution*Resolution/64,1,1);gl.MemoryBarrier(Barrier);CheckError();
                }
            }
            projected=result;hasResult=true;Invalidate();
        }
        private int sourceCount;
        private Point3D[] cached;
        private string orientation;
        private float lowX,lowY,lowZ,cell;
        private double diagonal;
        private bool hasResult,disposed;
        private float yaw=-.7f,pitch=.45f,distance=2;
        private System.Drawing.Point? drag;
        internal bool ShowSource=true,ShowProxy=true,ShowVolume=false;
        internal string Renderer {get;private set;}
        internal event Action<string> Failed;
        internal event Action<string> Timing;
        internal double LastUpdateMilliseconds {get;private set;}
        internal bool HasResult=>hasResult;
        protected override CreateParams CreateParams {get{var value=base.CreateParams;value.ClassStyle|=0x20;return value;}} // CS_OWNDC
        public GpuFramePreview()
        {
            Dock=DockStyle.Fill;TabStop=true;SetStyle(ControlStyles.Opaque|ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint,true);
            AccessibleName="GPU frame approximation. Drag or arrows to orbit, wheel or plus/minus to zoom, Home to fit.";
        }
        internal void Initialize()
        {
            if(gl!=null)return;
            try
            {
                gl=new PreviewGl(Handle);
                using(gl.Current())
                {
                    Renderer=Marshal.PtrToStringAnsi(gl.GetString(0x1F01));
                    compute=Program(new[]{Tuple.Create(0x91B9u,"volume.comp")});
                    render=Program(new[]{Tuple.Create(0x8B31u,"view.vert"),Tuple.Create(0x8B30u,"view.frag")});
                    gl.GenVertexArrays(1,out vao);
                    gl.GenBuffers(1,out vertices);gl.GenBuffers(1,out seeds);gl.GenBuffers(1,out scratchA);gl.GenBuffers(1,out scratchB);
                    gl.GenBuffers(1,out faces);gl.GenBuffers(1,out draw);gl.GenBuffers(1,out lines);gl.GenBuffers(1,out displayVolume);
                    int bytes=Resolution*Resolution*Resolution*4;
                    gl.Allocate(seeds,bytes);gl.Allocate(scratchA,bytes);gl.Allocate(scratchB,bytes);
                    gl.Allocate(faces,bytes*6);gl.Upload(draw,new uint[]{0,1,0,0},16);
                    CheckError();
                }
            }
            catch{Release();throw;}
        }
        private uint Program(Tuple<uint,string>[] stages)
        {
            uint program=gl.CreateProgram();
            try
            {
                foreach(var stage in stages)
                {
                    uint shader=gl.CreateShader(stage.Item1);
                    try
                    {
                        string code;
                        var assembly=typeof(GpuFramePreview).Assembly;
                        var resource=assembly.GetManifestResourceNames().Single(n=>n.EndsWith("PreviewShaders."+stage.Item2,StringComparison.Ordinal));
                        using(var reader=new StreamReader(assembly.GetManifestResourceStream(resource)))code=reader.ReadToEnd();
                        gl.ShaderSource(shader,1,new[]{code},new[]{code.Length});gl.CompileShader(shader);
                        gl.GetShaderiv(shader,0x8B81,out var compiled);
                        if(compiled==0){var log=new System.Text.StringBuilder(8192);gl.GetShaderInfoLog(shader,log.Capacity,out var length,log);throw new InvalidOperationException("Preview shader: "+log);}
                        gl.AttachShader(program,shader);
                    }
                    finally{gl.DeleteShader(shader);}
                }
                gl.LinkProgram(program);gl.GetProgramiv(program,0x8B82,out var linked);
                if(linked==0){var log=new System.Text.StringBuilder(8192);gl.GetProgramInfoLog(program,log.Capacity,out var length,log);throw new InvalidOperationException("Preview shader link: "+log);}
                return program;
            }
            catch{gl.DeleteProgram(program);throw;}
        }
        private void Int(uint program,string name,int value)=>gl.Uniform1i(gl.GetUniformLocation(program,name),value);
        private void Float(uint program,string name,float value)=>gl.Uniform1f(gl.GetUniformLocation(program,name),value);
        private void Common(uint program)
        {
            gl.UseProgram(program);Int(program,"n",Resolution);Float(program,"cell",cell);
            gl.Uniform3f(gl.GetUniformLocation(program,"low"),lowX,lowY,lowZ);
            gl.BindBufferBase(Storage,0,vertices);gl.BindBufferBase(Storage,3,faces);gl.BindBufferBase(Storage,4,draw);
            gl.BindBufferBase(Storage,5,lines);
        }
        private void CheckError(){uint error=gl.GetError();if(error!=0)throw new InvalidOperationException("GPU preview error 0x"+error.ToString("X"));}
        private async Task Fence(CancellationToken token)
        {
            IntPtr sync;
            using(gl.Current()){sync=gl.FenceSync(0x9117,0);gl.Flush();CheckError();}
            if(sync==IntPtr.Zero)throw new InvalidOperationException("Could not fence GPU preview work.");
            var clock=Stopwatch.StartNew();
            try
            {
                while(true)
                {
                    token.ThrowIfCancellationRequested();if(disposed)throw new OperationCanceledException();
                    uint result;using(gl.Current())result=gl.ClientWaitSync(sync,0,0);
                    if(result==0x911A||result==0x911C)return;
                    if(result==0x911D||clock.ElapsedMilliseconds>10000)throw new InvalidOperationException("GPU preview did not complete within its bounded update timeout.");
                    await Task.Delay(1,token);
                }
            }
            finally{if(gl!=null)using(gl.Current())gl.DeleteSync(sync);}
        }
        private async Task UploadSnapshot(Point3D[] source,HullOptions value,CancellationToken token)
        {
            // Only snapshot conversion/upload uses CPU. Slider changes reuse
            // the resident source and conservative seed volume.
            var data=await Task.Run(()=>{
                if(source.Length==0||source.Length%3!=0||source.Length/3>PreviewGeometry.MaxSourceTriangles)throw new InvalidDataException("Invalid preview snapshot size.");
                var matrix=AxisMapping.Matrix(value.Orientation);var points=new Point3D[source.Length];var bounds=Rect3D.Empty;
                for(int i=0;i<source.Length;i++)
                {
                    if(i%1024==0)token.ThrowIfCancellationRequested();var p=source[i];
                    points[i]=new Point3D(matrix[0][0]*p.X+matrix[0][1]*p.Y+matrix[0][2]*p.Z,matrix[1][0]*p.X+matrix[1][1]*p.Y+matrix[1][2]*p.Z,matrix[2][0]*p.X+matrix[2][1]*p.Y+matrix[2][2]*p.Z);
                    var q=points[i];if(double.IsNaN(q.X+q.Y+q.Z)||double.IsInfinity(q.X)||double.IsInfinity(q.Y)||double.IsInfinity(q.Z))throw new InvalidDataException("Non-finite GPU source coordinate.");bounds.Union(q);
                }
                double extent=Math.Sqrt(bounds.SizeX*bounds.SizeX+bounds.SizeY*bounds.SizeY+bounds.SizeZ*bounds.SizeZ);
                if(extent<1e-12||double.IsInfinity(extent))throw new InvalidDataException("Preview geometry has no usable extent.");
                var center=new Point3D(bounds.X+bounds.SizeX/2,bounds.Y+bounds.SizeY/2,bounds.Z+bounds.SizeZ/2);
                var packed=new float[points.Length*4];
                for(int i=0;i<points.Length;i++)
                {
                    if(i%1024==0)token.ThrowIfCancellationRequested();
                    packed[i*4]=(float)((points[i].X-center.X)/extent);packed[i*4+1]=(float)((points[i].Y-center.Y)/extent);packed[i*4+2]=(float)((points[i].Z-center.Z)/extent);
                }
                return Tuple.Create(packed,extent,(float)(Math.Max(bounds.SizeX,Math.Max(bounds.SizeY,bounds.SizeZ))/extent/(Resolution-2*(MaxRadius*2+1))),new PreviewHull(packed,token));
            },token);
            token.ThrowIfCancellationRequested();if(disposed)throw new OperationCanceledException();
            cached=null;proxyCache.Clear();diagonal=data.Item2;cell=data.Item3;hull=data.Item4;lowX=lowY=lowZ=-Resolution*cell/2;
            sourceCount=source.Length;
            using(gl.Current())
            {
                gl.Upload(vertices,data.Item1,data.Item1.Length*4,0x88E4);
                gl.Upload(seeds,new uint[Resolution*Resolution*Resolution],Resolution*Resolution*Resolution*4);
            }
            // Bound individual dispatches. Await each chunk without blocking the
            // WinForms message loop; Stop/settings edits cancel subsequent chunks.
            for(int first=0;first<sourceCount/3;first+=128)
            {
                token.ThrowIfCancellationRequested();
                using(gl.Current())
                {
                    Common(compute);Int(compute,"mode",0);Int(compute,"startTriangle",first);
                    Int(compute,"triangleCount",Math.Min(128,sourceCount/3-first));
                    gl.BindBufferBase(Storage,2,seeds);gl.DispatchCompute(2,1,1);gl.MemoryBarrier(Barrier);
                }
                await Fence(token);
            }
            cached=source;orientation=value.Orientation;
        }
        private void Morph(uint input,uint output,int radius,int axis,bool erode,CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            using(gl.Current())
            {
                Common(compute);Int(compute,"mode",2);Int(compute,"radius",radius);Int(compute,"axis",axis);Int(compute,"erode",erode?1:0);
                gl.BindBufferBase(Storage,1,input);gl.BindBufferBase(Storage,2,output);
                gl.DispatchCompute(Resolution*Resolution*Resolution/64,1,1);gl.MemoryBarrier(Barrier);
            }
        }
        internal Task<string> UpdateAsync(Point3D[] source,HullOptions value,CancellationToken token)
            =>PreviewUiThread.Run(this,()=>UpdateCoreAsync(source,value,token));
        private async Task<string> UpdateCoreAsync(Point3D[] source,HullOptions value,CancellationToken token)
        {
            token.ThrowIfCancellationRequested();if(disposed)throw new OperationCanceledException();
            value.Validate();Initialize();if(!evaluating)InvalidateResult();
            bool upload=!ReferenceEquals(source,cached)||orientation!=value.Orientation;
            if(upload)await UploadSnapshot(source,value,token);
            var clock=Stopwatch.StartNew();
            int requestedClosing=(int)Math.Min(int.MaxValue,Math.Ceiling(1/value.ProxyDivisor/2/cell));
            int requestedOffset=(int)Math.Min(int.MaxValue,Math.Ceiling((1/value.ProxyDivisor/value.ProxyOffsetRatio)/cell));
            int closing=Math.Min(MaxRadius,requestedClosing),offset=Math.Min(MaxRadius,requestedOffset);
            uint[] volume=null;
            var proxyKey=ProxyKey(value);
            bool reused=evaluating&&proxyCache.TryGetValue(proxyKey,out volume);
            if(!reused)
            {
            using(gl.Current())
            {
                // Production symmetry is applied AFTER projection, never to the proxy.
                Common(compute);Int(compute,"mode",1);Int(compute,"symmetry",0);Int(compute,"flip",0);
                gl.BindBufferBase(Storage,1,seeds);gl.BindBufferBase(Storage,2,scratchA);
                gl.DispatchCompute(Resolution*Resolution*Resolution/64,1,1);gl.MemoryBarrier(Barrier);
            }
            uint input=scratchA,output=scratchB;
            foreach(bool erosion in new[]{false,true})for(int axis=0;axis<3;axis++)
            {
                Morph(input,output,closing,axis,erosion,token);var swap=input;input=output;output=swap;
            }
            for(int axis=0;axis<3;axis++)
            {
                Morph(input,output,offset,axis,false,token);var swap=input;input=output;output=swap;
            }
            if(!evaluating)using(gl.Current())
            {
                gl.Upload(draw,new uint[]{0,1,0,0},16);
                Common(compute);Int(compute,"mode",3);gl.BindBufferBase(Storage,1,input);
                gl.DispatchCompute(Resolution*Resolution*Resolution/64,1,1);gl.MemoryBarrier(Barrier);
            }
            await Fence(token);token.ThrowIfCancellationRequested();
            volume=new uint[Resolution*Resolution*Resolution];var pin=GCHandle.Alloc(volume,GCHandleType.Pinned);
            try{using(gl.Current()){gl.BindBuffer(Storage,input);gl.GetBufferSubData(Storage,IntPtr.Zero,new IntPtr(volume.Length*4),pin.AddrOfPinnedObject());CheckError();}}
            finally{pin.Free();}
            if(proxyCache.Count<49)proxyCache[proxyKey]=volume;
            }
            // A bounded volume readback feeds CPU lattice pruning/BVH projection and
            // topology operations. CAD and the acceleration tree stay cached.
            var result=await Task.Run(()=>hull.Evaluate(volume,Resolution,lowX,cell,diagonal,value,token),token);
            result.PruningVolume=volume;
            token.ThrowIfCancellationRequested();if(disposed)throw new OperationCanceledException();
            if(evaluating){evaluated=result;return "Candidate evaluated.";}
            using(gl.Current()){gl.Upload(lines,result.Lines,result.Lines.Length*4);CheckError();}
            projected=result;hasResult=true;volumeReady=true;LastUpdateMilliseconds=clock.Elapsed.TotalMilliseconds;Invalidate();
            var message=string.Format(CultureInfo.InvariantCulture,
                "GPU approximation + projected grid: {0:0.0} ms after snapshot upload; {1}³ proxy voxels, {2:G3} m/cell. Closing radius {3}; proxy offset {4} cells.{5} Grid {6} × {7} × {8} (X/Y/Z).",
                LastUpdateMilliseconds,Resolution,cell*diagonal,closing,offset,
                requestedClosing>MaxRadius||requestedOffset>MaxRadius?" Preview radius capped; use full preparation to inspect these settings.":"",
                value.Width,value.Length,value.Height);
            message+=" Preview: "+result.Points.Length+" vertices, "+result.Lines.Length/8+" edges after projection, symmetry and weld. CPU topology included; CGAL/Blender result may differ.";
            if(result.Lines.Length==0)message+=" No drawable faces survive; reduce weld distance or inspect these settings with Prepare actual hull.";
            Timing?.Invoke(message+(upload?" Source voxelization/upload performed this update.":" Reused resident GPU snapshot."));return message;
        }
        internal void InvalidateResult(){hasResult=false;Invalidate();}
        internal void ClearSnapshot(){hasResult=false;sourceCount=0;cached=null;projected=null;hull=null;proxyCache.Clear();Invalidate();}
        internal void ResetView(){yaw=-.7f;pitch=.45f;distance=2;Invalidate();}
        protected override void OnPaintBackground(PaintEventArgs e){}
        protected override void OnPaint(PaintEventArgs e)
        {
            if(gl==null||disposed)return;
            try
            {
                using(gl.Current())
                {
                    gl.Viewport(0,0,Math.Max(1,Width),Math.Max(1,Height));gl.ClearColor(.09f,.11f,.14f,1);gl.Clear(0x4000|0x100);
                    if(sourceCount>0)
                    {
                        Common(render);gl.BindVertexArray(vao);gl.Enable(0x0B71);gl.Enable(0x0BE2);gl.BlendFunc(0x0302,0x0303);gl.Disable(0x0B44);
                        Float(render,"yaw",yaw);Float(render,"pitch",pitch);Float(render,"distance",distance);Float(render,"aspect",Width/(float)Math.Max(1,Height));
                        if(ShowSource){Int(render,"mode",0);gl.Uniform4f(gl.GetUniformLocation(render,"color"),.65f,.72f,.8f,1);gl.DrawArrays(4,0,sourceCount);}
                        if(ShowVolume&&HasPruningVolume){Int(render,"mode",1);gl.Uniform4f(gl.GetUniformLocation(render,"color"),1,.6f,.12f,.35f);gl.BindBuffer(0x8F3F,draw);gl.DrawArraysIndirect(4,IntPtr.Zero);}
                        if(ShowProxy&&hasResult&&projected!=null){Int(render,"mode",2);gl.Uniform4f(gl.GetUniformLocation(render,"color"),1,.65f,.15f,1);gl.DrawArrays(1,0,projected.Lines.Length/4);}
                    }
                    CheckError();gl.Swap();
                }
            }
            catch(Exception error){hasResult=false;Failed?.Invoke(error.Message);}
        }
        internal uint ReadVertexCountForTest()
        {
            var values=new uint[4];var pin=GCHandle.Alloc(values,GCHandleType.Pinned);
            try{using(gl.Current()){gl.BindBuffer(Storage,draw);gl.GetBufferSubData(Storage,IntPtr.Zero,new IntPtr(16),pin.AddrOfPinnedObject());CheckError();}return values[0];}
            finally{pin.Free();}
        }
        internal int ReadColoredPixelsForTest()
        {
            // Test-only framebuffer readback. Interactive updates never read geometry
            // or pixels back to the CPU.
            var pixels=new byte[Width*Height*4];var pin=GCHandle.Alloc(pixels,GCHandleType.Pinned);
            try
            {
                using(gl.Current()){gl.ReadBuffer(0x0404);gl.ReadPixels(0,0,Width,Height,0x1908,0x1401,pin.AddrOfPinnedObject());CheckError();}
                int count=0;for(int i=0;i<pixels.Length;i+=4)if(pixels[i]>70&&pixels[i]>pixels[i+2]*1.4)count++;
                return count;
            }
            finally{pin.Free();}
        }
        internal double ReadMeanFaceYForTest()
        {
            var values=new uint[ReadVertexCountForTest()/6];if(values.Length==0)throw new InvalidDataException("No GPU boundary faces.");
            var pin=GCHandle.Alloc(values,GCHandleType.Pinned);
            try
            {
                using(gl.Current()){gl.BindBuffer(Storage,faces);gl.GetBufferSubData(Storage,IntPtr.Zero,new IntPtr(values.Length*4),pin.AddrOfPinnedObject());CheckError();}
                return projected.Points.Average(p=>p.Y);
            }
            finally{pin.Free();}
        }
        protected override void OnMouseDown(MouseEventArgs e){base.OnMouseDown(e);if(e.Button==MouseButtons.Left){Focus();drag=e.Location;Capture=true;}}
        protected override void OnMouseUp(MouseEventArgs e){base.OnMouseUp(e);drag=null;Capture=false;}
        protected override void OnMouseCaptureChanged(EventArgs e){base.OnMouseCaptureChanged(e);if(!Capture)drag=null;}
        protected override void OnMouseMove(MouseEventArgs e){base.OnMouseMove(e);if(drag.HasValue){yaw-=(e.X-drag.Value.X)*.01f;pitch+=(e.Y-drag.Value.Y)*.01f;drag=e.Location;ClampView();}}
        protected override void OnMouseWheel(MouseEventArgs e){base.OnMouseWheel(e);distance*=(float)Math.Exp(-e.Delta/120.0*.12);ClampView();}
        protected override bool IsInputKey(Keys keyData)=>keyData==Keys.Left||keyData==Keys.Right||keyData==Keys.Up||keyData==Keys.Down||base.IsInputKey(keyData);
        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);switch(e.KeyCode){case Keys.Left:yaw-=.1f;break;case Keys.Right:yaw+=.1f;break;case Keys.Up:pitch+=.1f;break;case Keys.Down:pitch-=.1f;break;
                case Keys.Add:case Keys.Oemplus:distance*=.85f;break;case Keys.Subtract:case Keys.OemMinus:distance/=.85f;break;case Keys.Home:ResetView();break;default:return;}
            ClampView();e.Handled=true;
        }
        private void ClampView(){pitch=Math.Max(-1.45f,Math.Min(1.45f,pitch));distance=Math.Max(.15f,Math.Min(20,distance));Invalidate();}
        protected override void OnResize(EventArgs e){base.OnResize(e);Invalidate();}
        private void Release()
        {
            if(gl==null)return;
            // The HWND may already have been destroyed by Form.WmClose. Making
            // its DC current here fails. This context has no sharing partners:
            // deleting it releases all of its buffers, programs and VAOs.
            try {gl.Dispose();}
            finally{gl=null;cached=null;hull=null;projected=null;}
        }
        protected override void Dispose(bool disposing)
        {
            if(disposing&&!disposed){disposed=true;hasResult=false;Release();}
            base.Dispose(disposing);
        }
    }
}
