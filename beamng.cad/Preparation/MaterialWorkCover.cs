using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace BeamNG.Cad.Preparation
{
    // ActivateDoc3 temporarily releases SolidWorks' own redraw lock. An owned,
    // nonactivating cover keeps those intermediate document views off screen.
    internal sealed class MaterialWorkCover : Form
    {
        private sealed class OwnerWindow : IWin32Window
        {
            public IntPtr Handle { get; }
            public OwnerWindow(IntPtr handle) { Handle=handle; }
        }
        [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left,Top,Right,Bottom; }
        private delegate bool WindowCallback(IntPtr window,IntPtr data);
        [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr window,out Rect rectangle);
        [DllImport("user32.dll")] private static extern bool ClientToScreen(IntPtr window,ref Point point);
        [DllImport("user32.dll")] private static extern bool EnumWindows(WindowCallback callback,IntPtr data);
        [DllImport("user32.dll")] private static extern IntPtr GetWindow(IntPtr window,uint command);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr window,IntPtr after,int x,int y,int width,int height,uint flags);
        private readonly Label message=new Label {Dock=DockStyle.Fill,TextAlign=ContentAlignment.MiddleCenter,Text="Updating selected materials...",ForeColor=SystemColors.ControlText};
        protected override bool ShowWithoutActivation => true;
        protected override CreateParams CreateParams
        {
            get { var value=base.CreateParams;value.ExStyle|=0x08000000|0x00000080;return value; }
        }
        public MaterialWorkCover(IntPtr frame)
        {
            FormBorderStyle=FormBorderStyle.None;ShowInTaskbar=false;StartPosition=FormStartPosition.Manual;
            AutoScaleMode=AutoScaleMode.None;BackColor=SystemColors.Control;Text="beamng.cad material update";
            Controls.Add(message);
            Rect rectangle;var origin=Point.Empty;
            if(!GetClientRect(frame,out rectangle) || !ClientToScreen(frame,ref origin))
                throw new InvalidOperationException("Cannot locate the SolidWorks workspace for material updates.");
            Bounds=new Rectangle(origin.X,origin.Y,rectangle.Right-rectangle.Left,rectangle.Bottom-rectangle.Top);
            // Preserve existing owned popup order, especially the workflow's
            // progress and Stop controls. Never use a desktop-wide topmost window.
            var popups=new List<IntPtr>();
            EnumWindows((window,data)=>{if(GetWindow(window,4)==frame && IsWindowVisible(window))popups.Add(window);return true;},IntPtr.Zero);
            try
            {
                Show(new OwnerWindow(frame));
                if(popups.Count>0 && !SetWindowPos(Handle,popups[popups.Count-1],0,0,0,0,0x0001|0x0002|0x0010))
                    throw new InvalidOperationException("Cannot keep the material progress window above the workspace cover.");
                Refresh();
            }
            catch { Dispose();throw; }
        }
        public void SetStatus(string text) { message.Text=text;message.Refresh(); }
    }
}
