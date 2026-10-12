using System;
using System.Drawing;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    // Keep the expected next action visible beside import, rather than turning
    // a successful import into an exception on the next click.
    internal sealed class TemplateImportPanel : UserControl
    {
        private readonly Label message=new Label {Name="TemplateImportState",AutoSize=true,MaximumSize=new Size(460,0),Margin=new Padding(3,4,3,8)};
        private readonly Button action=new Button {Name="ImportPhysicsTemplate",AutoSize=true};
        private readonly Button reset=new Button {Name="ResetPhysicsTemplate",Text="Reset to imported template",AutoSize=true};
        private bool imported;
        public event Action ImportRequested;
        public event Action ContinueRequested;
        public event Action ResetRequested;
        public event Action FreshRequested;
        public event Action OpenRequested;

        public TemplateImportPanel()
        {
            Name="TemplateImportPanel";AutoSize=true;AutoSizeMode=AutoSizeMode.GrowAndShrink;
            // A top-docked child contributes height but no preferred width to
            // an AutoSize UserControl inside another FlowLayoutPanel. Keep it
            // undocked so this panel measures both dimensions of its contents.
            var body=new FlowLayoutPanel {AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,FlowDirection=FlowDirection.TopDown,WrapContents=false};
            var fresh=new Button {Name="StartFreshCadProject",Text="Start fresh from CAD",AutoSize=true};
            var open=new Button {Name="OpenSavedProject",Text="Open saved project",AutoSize=true};
            fresh.Click+=(s,e)=>FreshRequested?.Invoke();open.Click+=(s,e)=>OpenRequested?.Invoke();
            body.Controls.Add(fresh);body.Controls.Add(open);body.Controls.Add(message);body.Controls.Add(action);body.Controls.Add(reset);Controls.Add(body);
            action.Click+=(s,e)=>{if(imported)ContinueRequested?.Invoke();else ImportRequested?.Invoke();};
            reset.Click+=(s,e)=>ResetRequested?.Invoke();
            SetState(0,"");
        }
        public void SetState(int componentCount,string receipt)
        {
            imported=componentCount>0&&!string.IsNullOrWhiteSpace(receipt);
            action.Text=imported?"Continue with imported template":"Import physics template";
            action.Enabled=imported||componentCount==0;
            reset.Visible=imported;reset.Enabled=imported;
            message.Text=imported?
                "Template already imported. Its hardpoints and physics are loaded. Continue to Components > Appearance to associate your CAD with an imported component.\r\nReset restores the original template groups, hardpoints and appearance, replacing current assignments and mounts. A project backup and all earlier builds are kept.\r\nSource: "+receipt:
                componentCount>0?
                "Import is unavailable because this project already has CAD groups. Existing assignments are preserved. A physics template needs an empty project; importing is not required for the fresh-CAD workflow.":
                "No physics template imported. Start fresh from CAD to create unassigned groups for your vehicle layout. Import is optional and reuses an existing package's physics.";
        }
    }
}
