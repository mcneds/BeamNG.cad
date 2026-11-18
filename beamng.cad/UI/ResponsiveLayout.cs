using System;
using System.Drawing;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    internal static class ResponsiveLayout
    {
        public static void Split(TableLayoutPanel table,Control list,Control editor,bool narrow,int listHeight)
        {
            if((table.ColumnCount==1)==narrow)return;
            table.SuspendLayout();
            try
            {
                table.Controls.Remove(list);table.Controls.Remove(editor);table.ColumnStyles.Clear();table.RowStyles.Clear();
                table.ColumnCount=narrow?1:2;table.RowCount=narrow?2:1;
                table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,narrow?100:34));
                if(!narrow)table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,66));
                if(narrow)table.RowStyles.Add(new RowStyle(SizeType.Absolute,listHeight));
                table.RowStyles.Add(new RowStyle(SizeType.Percent,100));
                table.Controls.Add(list,0,0);table.Controls.Add(editor,narrow?0:1,narrow?1:0);
            }
            finally {table.ResumeLayout(true);}
        }
        public static void FlowSection(GroupBox group,FlowLayoutPanel body)
        {
            var fitting=false;
            group.SizeChanged+=(s,e)=>
            {
                if(fitting)return;fitting=true;
                try
                {
                    var width=Math.Max(180,group.ClientSize.Width-group.Padding.Horizontal-8);
                    body.MaximumSize=new Size(width,0);
                    Fit(body,width);
                }
                finally {fitting=false;}
            };
        }
        private static void Fit(Control parent,int width)
        {
            foreach(Control child in parent.Controls)
            {
                if(child is Label label&&label.AutoSize)label.MaximumSize=new Size(width,0);
                if(child is FlowLayoutPanel flow)
                {flow.MaximumSize=new Size(width,0);if(flow.FlowDirection==FlowDirection.LeftToRight)flow.WrapContents=true;Fit(flow,width);}
                else if(child is ComboBox||child is TextBox)child.Width=Math.Min(child.Width,width-8);
                else if(child is UserControl)child.MaximumSize=new Size(width,0);
            }
        }
    }
}
