using System;
using System.Windows.Forms;
using BeamNG.Cad.Properties;
using Xarial.XCad.Base.Attributes;

namespace BeamNG.Cad.UI
{
    [Title("Vehicle project")]
    [Icon(typeof(CommandIcons), nameof(CommandIcons.Export))]
    internal sealed class DockedProjectHost : UserControl
    {
        private bool repaintQueued;

        public DockedProjectHost()
        {
            Dock=DockStyle.Fill;
            ResizeRedraw=true;
        }

        internal void RefreshAfterDocking()
        {
            if(repaintQueued||!IsHandleCreated||IsDisposed||Disposing)return;
            repaintQueued=true;
            // Let the native Task Pane finish positioning before repainting its children.
            BeginInvoke(new Action(()=>
            {
                repaintQueued=false;
                if(IsDisposed||Disposing||!Visible)return;
                PerformLayout();
                Invalidate(true);
            }));
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            RefreshAfterDocking();
        }

        protected override void OnVisibleChanged(EventArgs e)
        {
            base.OnVisibleChanged(e);
            if(Visible)RefreshAfterDocking();
        }

        protected override void OnHandleDestroyed(EventArgs e)
        {
            repaintQueued=false;
            base.OnHandleDestroyed(e);
        }
    }
}
