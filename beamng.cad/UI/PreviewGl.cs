using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace BeamNG.Cad.UI
{
    // Small Windows OpenGL 4.3 binding for the preview only. Every entry restores
    // the host's current context; no SolidWorks graphics state is shared.
    internal sealed class PreviewGl : IDisposable
    {
        [StructLayout(LayoutKind.Sequential)] private struct PixelFormat
        {
            public ushort Size,Version;public uint Flags;
            public byte PixelType,ColorBits,RedBits,RedShift,GreenBits,GreenShift,BlueBits,BlueShift,AlphaBits,AlphaShift,
                AccumBits,AccumRedBits,AccumGreenBits,AccumBlueBits,AccumAlphaBits,DepthBits,StencilBits,AuxBuffers,LayerType,Reserved;
            public uint LayerMask,VisibleMask,DamageMask;
        }
        [DllImport("user32.dll")] private static extern IntPtr GetDC(IntPtr window);
        [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr window,IntPtr dc);
        [DllImport("gdi32.dll")] private static extern int ChoosePixelFormat(IntPtr dc,ref PixelFormat format);
        [DllImport("gdi32.dll")] private static extern bool SetPixelFormat(IntPtr dc,int number,ref PixelFormat format);
        [DllImport("gdi32.dll")] private static extern bool SwapBuffers(IntPtr dc);
        [DllImport("opengl32.dll")] private static extern IntPtr wglCreateContext(IntPtr dc);
        [DllImport("opengl32.dll")] private static extern bool wglDeleteContext(IntPtr context);
        [DllImport("opengl32.dll")] private static extern bool wglMakeCurrent(IntPtr dc,IntPtr context);
        [DllImport("opengl32.dll")] private static extern IntPtr wglGetCurrentContext();
        [DllImport("opengl32.dll")] private static extern IntPtr wglGetCurrentDC();
        [DllImport("opengl32.dll",CharSet=CharSet.Ansi)] private static extern IntPtr wglGetProcAddress(string name);
        [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] private static extern IntPtr GetModuleHandle(string name);
        [DllImport("kernel32.dll",CharSet=CharSet.Ansi)] private static extern IntPtr GetProcAddress(IntPtr module,string name);
        [UnmanagedFunctionPointer(CallingConvention.Winapi)] private delegate IntPtr CreateContext(IntPtr dc,IntPtr share,int[] attributes);
        internal delegate void Generate(int count,out uint value);
        internal delegate void Delete(int count,ref uint value);
        internal delegate void Bind(uint target,uint value);
        internal delegate void BufferDataCall(uint target,IntPtr size,IntPtr data,uint usage);
        internal delegate void BufferSubDataCall(uint target,IntPtr offset,IntPtr size,IntPtr data);
        internal delegate void BindBaseCall(uint target,uint binding,uint value);
        internal delegate uint CreateShaderCall(uint type);
        internal delegate void ShaderSourceCall(uint shader,int count,[MarshalAs(UnmanagedType.LPArray,ArraySubType=UnmanagedType.LPStr)] string[] text,int[] lengths);
        internal delegate void ObjectCall(uint value);
        internal delegate void GetIntegerCall(uint value,uint parameter,out int result);
        internal delegate void InfoLogCall(uint value,int size,out int length,System.Text.StringBuilder text);
        internal delegate uint CreateProgramCall();
        internal delegate void AttachCall(uint program,uint shader);
        internal delegate int LocationCall(uint program,[MarshalAs(UnmanagedType.LPStr)] string name);
        internal delegate void IntCall(int location,int value);
        internal delegate void FloatCall(int location,float value);
        internal delegate void Vec3Call(int location,float x,float y,float z);
        internal delegate void Vec4Call(int location,float x,float y,float z,float w);
        internal delegate void DispatchCall(uint x,uint y,uint z);
        internal delegate IntPtr FenceCall(uint condition,uint flags);
        internal delegate uint WaitCall(IntPtr sync,uint flags,ulong timeout);
        internal delegate void DeleteSyncCall(IntPtr sync);
        internal delegate void ViewportCall(int x,int y,int width,int height);
        internal delegate void ClearColorCall(float r,float g,float b,float a);
        internal delegate void DrawCall(uint mode,int first,int count);
        internal delegate void DrawIndirectCall(uint mode,IntPtr offset);
        internal delegate IntPtr StringCall(uint name);
        internal delegate void VoidCall();
        internal delegate uint ErrorCall();
        internal delegate void PixelsCall(int x,int y,int width,int height,uint format,uint type,IntPtr data);
        internal readonly Generate GenBuffers,GenVertexArrays;
        internal readonly Delete DeleteBuffers,DeleteVertexArrays;
        internal readonly Bind BindBuffer,BlendFunc;
        internal readonly BufferDataCall BufferData;
        internal readonly BufferSubDataCall GetBufferSubData;
        internal readonly BindBaseCall BindBufferBase;
        internal readonly CreateShaderCall CreateShader;
        internal readonly ShaderSourceCall ShaderSource;
        internal readonly ObjectCall CompileShader,DeleteShader,DeleteProgram,UseProgram,BindVertexArray,MemoryBarrier,Clear,Enable,Disable,LinkProgram;
        internal readonly GetIntegerCall GetShaderiv,GetProgramiv;
        internal readonly InfoLogCall GetShaderInfoLog,GetProgramInfoLog;
        internal readonly CreateProgramCall CreateProgram;
        internal readonly AttachCall AttachShader;
        internal readonly LocationCall GetUniformLocation;
        internal readonly IntCall Uniform1i;
        internal readonly FloatCall Uniform1f;
        internal readonly Vec3Call Uniform3f;
        internal readonly Vec4Call Uniform4f;
        internal readonly DispatchCall DispatchCompute;
        internal readonly FenceCall FenceSync;
        internal readonly WaitCall ClientWaitSync;
        internal readonly DeleteSyncCall DeleteSync;
        internal readonly ViewportCall Viewport;
        internal readonly ClearColorCall ClearColor;
        internal readonly DrawCall DrawArrays;
        internal readonly DrawIndirectCall DrawArraysIndirect;
        internal readonly StringCall GetString;
        internal readonly VoidCall Flush;
        internal readonly ErrorCall GetError;
        internal readonly ObjectCall ReadBuffer;
        internal readonly PixelsCall ReadPixels;
        private IntPtr window,dc,context;
        private static T Load<T>(string name) where T:Delegate
        {
            var pointer=wglGetProcAddress(name);
            if(pointer==IntPtr.Zero||pointer==new IntPtr(1)||pointer==new IntPtr(2)||pointer==new IntPtr(3)||pointer==new IntPtr(-1))pointer=GetProcAddress(GetModuleHandle("opengl32.dll"),name);
            if(pointer==IntPtr.Zero)throw new NotSupportedException("GPU preview requires OpenGL 4.3: "+name+" unavailable.");
            return (T)Marshal.GetDelegateForFunctionPointer(pointer,typeof(T));
        }
        public PreviewGl(IntPtr window)
        {
            this.window=window;var previousDc=wglGetCurrentDC();var previous=wglGetCurrentContext();
            try
            {
                dc=GetDC(window);if(dc==IntPtr.Zero)throw new Win32Exception();
                var format=new PixelFormat {Size=(ushort)Marshal.SizeOf(typeof(PixelFormat)),Version=1,Flags=0x25,ColorBits=32,DepthBits=24,StencilBits=8};
                int chosen=ChoosePixelFormat(dc,ref format);
                if(chosen==0||!SetPixelFormat(dc,chosen,ref format))throw new Win32Exception();
                context=wglCreateContext(dc);if(context==IntPtr.Zero||!wglMakeCurrent(dc,context))throw new Win32Exception();
                var create=Load<CreateContext>("wglCreateContextAttribsARB");
                var modern=create(dc,IntPtr.Zero,new[]{0x2091,4,0x2092,3,0x9126,1,0});
                if(modern==IntPtr.Zero)throw new NotSupportedException("OpenGL 4.3 compute shaders unavailable.");
                wglMakeCurrent(IntPtr.Zero,IntPtr.Zero);wglDeleteContext(context);context=modern;
                if(!wglMakeCurrent(dc,context))throw new Win32Exception();
                GenBuffers=Load<Generate>("glGenBuffers");GenVertexArrays=Load<Generate>("glGenVertexArrays");
                DeleteBuffers=Load<Delete>("glDeleteBuffers");DeleteVertexArrays=Load<Delete>("glDeleteVertexArrays");
                BindBuffer=Load<Bind>("glBindBuffer");BlendFunc=Load<Bind>("glBlendFunc");BufferData=Load<BufferDataCall>("glBufferData");
                GetBufferSubData=Load<BufferSubDataCall>("glGetBufferSubData");BindBufferBase=Load<BindBaseCall>("glBindBufferBase");
                CreateShader=Load<CreateShaderCall>("glCreateShader");ShaderSource=Load<ShaderSourceCall>("glShaderSource");CompileShader=Load<ObjectCall>("glCompileShader");
                DeleteShader=Load<ObjectCall>("glDeleteShader");DeleteProgram=Load<ObjectCall>("glDeleteProgram");UseProgram=Load<ObjectCall>("glUseProgram");
                BindVertexArray=Load<ObjectCall>("glBindVertexArray");MemoryBarrier=Load<ObjectCall>("glMemoryBarrier");Clear=Load<ObjectCall>("glClear");
                Enable=Load<ObjectCall>("glEnable");Disable=Load<ObjectCall>("glDisable");LinkProgram=Load<ObjectCall>("glLinkProgram");
                GetShaderiv=Load<GetIntegerCall>("glGetShaderiv");GetProgramiv=Load<GetIntegerCall>("glGetProgramiv");
                GetShaderInfoLog=Load<InfoLogCall>("glGetShaderInfoLog");GetProgramInfoLog=Load<InfoLogCall>("glGetProgramInfoLog");
                CreateProgram=Load<CreateProgramCall>("glCreateProgram");AttachShader=Load<AttachCall>("glAttachShader");GetUniformLocation=Load<LocationCall>("glGetUniformLocation");
                Uniform1i=Load<IntCall>("glUniform1i");Uniform1f=Load<FloatCall>("glUniform1f");Uniform3f=Load<Vec3Call>("glUniform3f");Uniform4f=Load<Vec4Call>("glUniform4f");
                DispatchCompute=Load<DispatchCall>("glDispatchCompute");FenceSync=Load<FenceCall>("glFenceSync");ClientWaitSync=Load<WaitCall>("glClientWaitSync");DeleteSync=Load<DeleteSyncCall>("glDeleteSync");
                Viewport=Load<ViewportCall>("glViewport");ClearColor=Load<ClearColorCall>("glClearColor");DrawArrays=Load<DrawCall>("glDrawArrays");DrawArraysIndirect=Load<DrawIndirectCall>("glDrawArraysIndirect");
                GetString=Load<StringCall>("glGetString");Flush=Load<VoidCall>("glFlush");GetError=Load<ErrorCall>("glGetError");
                ReadBuffer=Load<ObjectCall>("glReadBuffer");ReadPixels=Load<PixelsCall>("glReadPixels");
            }
            catch{Dispose();throw;}
            finally{wglMakeCurrent(previousDc,previous);}
        }
        internal IDisposable Current()=>new Scope(dc,context);
        private sealed class Scope:IDisposable
        {
            private readonly IntPtr oldDc=wglGetCurrentDC(),oldContext=wglGetCurrentContext();
            public Scope(IntPtr dc,IntPtr context){if(!wglMakeCurrent(dc,context))throw new Win32Exception();}
            public void Dispose(){wglMakeCurrent(oldDc,oldContext);}
        }
        internal void Upload(uint buffer,Array data,int bytes,uint usage=0x88E8)
        {
            var pin=GCHandle.Alloc(data,GCHandleType.Pinned);
            try{BindBuffer(0x90D2,buffer);BufferData(0x90D2,new IntPtr(bytes),pin.AddrOfPinnedObject(),usage);}
            finally{pin.Free();}
        }
        internal void Allocate(uint buffer,int bytes)
        {BindBuffer(0x90D2,buffer);BufferData(0x90D2,new IntPtr(bytes),IntPtr.Zero,0x88E8);}
        internal void Swap(){if(!SwapBuffers(dc))throw new Win32Exception();}
        public void Dispose()
        {
            if(context!=IntPtr.Zero){if(wglGetCurrentContext()==context)wglMakeCurrent(IntPtr.Zero,IntPtr.Zero);wglDeleteContext(context);context=IntPtr.Zero;}
            if(dc!=IntPtr.Zero){ReleaseDC(window,dc);dc=IntPtr.Zero;}
        }
    }
}
