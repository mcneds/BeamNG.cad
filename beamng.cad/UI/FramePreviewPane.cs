using System;
using System.Drawing;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    // Keep the renderer parented for the lifetime of the frame editor. Focus changes,
    // tab changes and parameter edits must not recreate its HWND or GPU context.
    internal sealed class FramePreviewPane : UserControl
    {
        internal readonly FramePreviewWindow Preview=new FramePreviewWindow();
        internal readonly TabControl Editors=new TabControl {Dock=DockStyle.Fill};
        private readonly SplitContainer split=new SplitContainer {Dock=DockStyle.Fill,
            Orientation=Orientation.Horizontal,SplitterWidth=6,Size=new Size(400,650)};
        private bool arranging;
        private bool initialized;

        internal FramePreviewPane()
        {
            Dock=DockStyle.Fill;
            Preview.TopLevel=false;Preview.FormBorderStyle=FormBorderStyle.None;
            Preview.MinimumSize=Size.Empty;Preview.Dock=DockStyle.Fill;
            split.Panel1.Controls.Add(Preview);split.Panel2.Controls.Add(Editors);
            Controls.Add(split);
            TabPage suggestions=null;
            Preview.SearchOpened+=()=>{if(suggestions==null){suggestions=new TabPage("Hull suggestions");suggestions.Controls.Add(Preview.SearchControls);Editors.TabPages.Add(suggestions);}Editors.SelectedTab=suggestions;};
            SizeChanged+=(s,e)=>Arrange();
            VisibleChanged+=(s,e)=>{if(Visible){Arrange();Preview.Show();}};
        }
        private void Arrange()
        {
            if(arranging||ClientSize.Width==0||ClientSize.Height==0)return;
            arranging=true;
            try
            {
                var orientation=ClientSize.Width>=760?Orientation.Vertical:Orientation.Horizontal;
                var changed=!initialized||split.Orientation!=orientation;
                split.Panel1MinSize=split.Panel2MinSize=0;
                split.Orientation=orientation;
                var available=(orientation==Orientation.Vertical?split.Width:split.Height)-split.SplitterWidth;
                if(available<2)return;
                var minimum=Math.Min(orientation==Orientation.Vertical?280:180,available/2);
                var desired=changed?(int)(available*.5):split.SplitterDistance;
                split.SplitterDistance=Math.Max(minimum,Math.Min(available-minimum,desired));
                split.Panel1MinSize=split.Panel2MinSize=minimum;
                initialized=true;
            }
            finally{arranging=false;}
        }
    }
}
