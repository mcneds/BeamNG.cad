using System;
using System.Drawing;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed class ComponentAssignmentList : ListBox
    {
        private static readonly Lazy<Dictionary<string,string>> roleLabels=new Lazy<Dictionary<string,string>>(()=>MvpCatalog.Load().Roles.ToDictionary(r=>r.Id,r=>r.Label));
        private readonly ToolTip details=new ToolTip {AutoPopDelay=15000};
        private int hover=-1;
        public ComponentAssignmentList(){Name="Components";Dock=DockStyle.Fill;DisplayMember="AssignmentLabel";DrawMode=DrawMode.OwnerDrawFixed;IntegralHeight=false;UpdateHeight();}
        public void ShowComponents(IEnumerable<ComponentDefinition> components,string query,string selectedId)
        {
            var words=(query??"").Split((char[])null,StringSplitOptions.RemoveEmptyEntries);
            var matches=components.Where(c=>
            {
                roleLabels.Value.TryGetValue(c.MvpRole??"",out var roleLabel);
                var searchable=c.Name+" "+roleLabel+" "+c.MvpRole?.Replace('_',' ')+" "+c.Template;
                return words.All(w=>searchable.IndexOf(w,StringComparison.OrdinalIgnoreCase)>=0);
            }).ToList();
            BeginUpdate();
            try {DataSource=null;DisplayMember="AssignmentLabel";DataSource=matches;SelectedItem=matches.FirstOrDefault(c=>c.Id==selectedId)??matches.FirstOrDefault();}
            finally {EndUpdate();}
        }
        private void UpdateHeight(){ItemHeight=Font.Height*2+8;}
        protected override void OnFontChanged(EventArgs e){base.OnFontChanged(e);UpdateHeight();}
        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);var index=IndexFromPoint(e.Location);if(index==hover)return;hover=index;
            details.SetToolTip(this,index>=0&&Items[index] is ComponentDefinition c?c.Label+"\r\n"+c.AssignmentSummary:null);
        }
        protected override void Dispose(bool disposing){if(disposing)details.Dispose();base.Dispose(disposing);}
        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            e.DrawBackground();
            if(e.Index>=0&&e.Index<Items.Count && Items[e.Index] is ComponentDefinition c)
            {
                var flags=TextFormatFlags.SingleLine|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix;
                var bounds=new Rectangle(e.Bounds.X+3,e.Bounds.Y+3,e.Bounds.Width-6,Font.Height+1);
                TextRenderer.DrawText(e.Graphics,c.Label,Font,bounds,e.ForeColor,flags);
                bounds.Y+=Font.Height+2;
                TextRenderer.DrawText(e.Graphics,c.AssignmentSummary,Font,bounds,e.ForeColor,flags);
            }
            e.DrawFocusRectangle();
        }
    }
}
