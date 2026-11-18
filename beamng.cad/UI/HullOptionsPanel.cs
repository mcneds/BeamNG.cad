using System;
using System.Drawing;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    // Geometry settings only: reusable by future component assignment workflows.
    internal sealed class HullOptionsPanel : UserControl
    {
        private readonly NumericUpDown width=Number("HullWidth",2,100,3,0);
        private readonly NumericUpDown height=Number("HullHeight",2,100,5,0);
        private readonly NumericUpDown length=Number("HullLength",2,100,7,0);
        private readonly NumericUpDown offset=Number("HullOffset",0,1000,0.01m,4);
        private readonly NumericUpDown weld=Number("HullWeld",0,1000,0.15m,4);
        private readonly NumericUpDown divisor=Number("HullProxyDivisor",0.001m,1000000,7,3);
        private readonly NumericUpDown ratio=Number("HullProxyOffsetRatio",0.001m,1000000,100,3);
        private readonly NumericUpDown merge=Number("HullSymmetryMergeDistance",0,1000,0.0001m,5);
        private readonly CheckBox symmetry=new CheckBox { Name="HullSymmetry",Text="Enforce X symmetry",AutoSize=true };
        private readonly CheckBox flip=new CheckBox { Name="HullSymmetryBisectFlip",Text="Use opposite source half",AutoSize=true };
        private bool loading;
        public event EventHandler ValueChanged;

        public HullOptionsPanel()
        {
            AutoScroll=true; Dock=DockStyle.Fill; Padding=new Padding(10);
            var table=new TableLayoutPanel { Dock=DockStyle.Top,AutoSize=true,ColumnCount=2,Padding=new Padding(0,0,15,10) };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,115));
            Controls.Add(table);
            Section(table,"Coordinates");
            Row(table,"Automatic conversion",new Label {Text="Y-up → Z-up",AutoSize=true},
                "SolidWorks +Y up / +Z front → BeamNG +Z up / −Y front. Assembly origin is preserved.");
            Section(table,"Grid resolution");
            Row(table,"Width (X)",width,"Grid points across the width. Use an odd count for symmetry.");
            Row(table,"Height (Z)",height,"Grid points vertically. Higher counts can retain more detail.");
            Row(table,"Length (Y)",length,"Grid points along the length. Axes refer to the mapped output.");
            Section(table,"Surface fit");
            Row(table,"Surface offset (m)",offset,"Distance from the selected geometry after shrinkwrap.");
            Row(table,"Weld distance (m)",weld,"Merge nearby hull vertices. Lower this if corners collapse.");
            Section(table,"Pruning proxy");
            Row(table,"Alpha divisor",divisor,"Alpha = selection bounds diagonal / divisor. Larger values capture smaller details.");
            Row(table,"Offset ratio",ratio,"Proxy offset = alpha / ratio. This controls the closed volume used to prune the grid.");
            Section(table,"Symmetry");
            var symmetryRow=table.RowCount++;table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            table.Controls.Add(symmetry,0,symmetryRow);table.SetColumnSpan(symmetry,2);
            var flipRow=table.RowCount++;table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            table.Controls.Add(flip,0,flipRow);table.SetColumnSpan(flip,2);
            Row(table,"Seam merge (m)",merge,"Merge mirrored vertices at the X centre of the selection bounds.");
            var reset=new Button { Name="ResetHullDefaults",Text="Reset hull defaults",AutoSize=true };
            var resetRow=table.RowCount++;table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            table.Controls.Add(reset,0,resetRow);table.SetColumnSpan(reset,2);
            reset.Click+=(s,e)=> { Value=new HullOptions(); Changed(); };
            foreach(var number in new[]{width,height,length,offset,weld,divisor,ratio,merge}) number.ValueChanged+=(s,e)=>Changed();
            symmetry.CheckedChanged+=(s,e)=>Changed();flip.CheckedChanged+=(s,e)=>Changed();
            Value=new HullOptions();
        }
        private void Changed()
        {
            flip.Enabled=merge.Enabled=symmetry.Checked;
            if(!loading)ValueChanged?.Invoke(this,EventArgs.Empty);
        }
        public HullOptions Value
        {
            get => new HullOptions { Width=(int)width.Value,Height=(int)height.Value,Length=(int)length.Value,
                Offset=(double)offset.Value,Weld=(double)weld.Value,ProxyDivisor=(double)divisor.Value,
                ProxyOffsetRatio=(double)ratio.Value,Symmetry=symmetry.Checked,SymmetryBisectFlip=flip.Checked,
                SymmetryMergeDistance=(double)merge.Value,Orientation=AxisMapping.Standard };
            set
            {
                loading=true;
                try
                {
                    width.Value=value.Width;height.Value=value.Height;length.Value=value.Length;
                    offset.Value=(decimal)value.Offset;weld.Value=(decimal)value.Weld;divisor.Value=(decimal)value.ProxyDivisor;
                    ratio.Value=(decimal)value.ProxyOffsetRatio;merge.Value=(decimal)value.SymmetryMergeDistance;
                    symmetry.Checked=value.Symmetry;flip.Checked=value.SymmetryBisectFlip;
                }
                finally {loading=false;ChangedSilently();}
            }
        }
        private void ChangedSilently() {flip.Enabled=merge.Enabled=symmetry.Checked;}
        private static NumericUpDown Number(string name,decimal min,decimal max,decimal value,int decimals) =>
            new NumericUpDown { Name=name,Minimum=min,Maximum=max,Value=value,DecimalPlaces=decimals,
                Increment=decimals==0?1:decimals==5?0.0001m:0.001m,Width=105,Margin=new Padding(3,5,3,5) };
        private static void Section(TableLayoutPanel table,string title)
        {
            var row=table.RowCount++;table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            var label=new Label { Text=title,AutoSize=true,Font=new Font(SystemFonts.MessageBoxFont,FontStyle.Bold),Margin=new Padding(3,14,3,6) };
            table.Controls.Add(label,0,row);table.SetColumnSpan(label,2);
        }
        private static void Row(TableLayoutPanel table,string title,Control input,string help)
        {
            var row=table.RowCount++;table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            table.Controls.Add(new Label { Text=title,AutoSize=true,Margin=new Padding(3,8,3,5) },0,row);
            table.Controls.Add(input,1,row);
            var description=new Label { Text=help,AutoSize=true,Dock=DockStyle.Fill,Margin=new Padding(3,0,3,6) };
            var helpRow=table.RowCount++;table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            table.Controls.Add(description,0,helpRow);table.SetColumnSpan(description,2);
        }
    }
}
