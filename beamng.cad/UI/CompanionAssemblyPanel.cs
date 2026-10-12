using System;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    internal sealed class CompanionAssemblyPanel : UserControl
    {
        private readonly Label status=new Label {Name="CompanionStatus",AutoSize=true,MaximumSize=new System.Drawing.Size(460,0)};
        private readonly Button open=new Button {Name="OpenCompanion",Text="Open companion",AutoSize=true};
        private readonly CheckBox geometry=new CheckBox {Name="RefreshCompanionGeometry",Text="Refresh assigned geometry too",AutoSize=true};
        public bool RefreshGeometry=>geometry.Checked;
        public event Action CreateRequested,UpdateRequested,OpenRequested,AppearanceRefreshRequested;
        public CompanionAssemblyPanel()
        {
            AutoSize=true;AutoSizeMode=AutoSizeMode.GrowAndShrink;
            var body=new FlowLayoutPanel {AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,FlowDirection=FlowDirection.TopDown,WrapContents=false};
            var buttons=new FlowLayoutPanel {AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,WrapContents=false};
            var create=new Button {Name="CreateCompanion",Text="Create working assembly...",AutoSize=true};
            var update=new Button {Name="UpdateCompanion",Text="Update companion assembly",AutoSize=true};
            var appearances=new Button {Name="RefreshCompanionAppearances",Text="Refresh selected appearances from source",AutoSize=true};
            appearances.Click+=(s,e)=>AppearanceRefreshRequested?.Invoke();
            create.Click+=(s,e)=>CreateRequested?.Invoke();update.Click+=(s,e)=>UpdateRequested?.Invoke();open.Click+=(s,e)=>OpenRequested?.Invoke();
            buttons.Controls.Add(create);buttons.Controls.Add(open);body.Controls.Add(buttons);body.Controls.Add(appearances);body.Controls.Add(update);body.Controls.Add(geometry);body.Controls.Add(status);Controls.Add(body);
            new ToolTip().SetToolTip(appearances,"Restore the selected group's original CAD finishes through its copy history. Keeps existing parts, folders and mates; geometry changes require the separate geometry refresh.");
            new ToolTip().SetToolTip(geometry,"Also recopy unchanged body assignments after CAD shape/material edits. Reviewed donor replacements remain owned by the companion and are retained. Other replaced parts need their mounting references repaired; old part files are retained.");
        }
        public void SetState(bool linked,string message){open.Enabled=linked;status.Text=message;}
    }
}
