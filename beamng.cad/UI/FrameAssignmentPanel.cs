using System;
using System.Drawing;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed class FrameAssignmentPanel : UserControl
    {
        private readonly Label state=new Label {Name="SavedFrameState",AutoSize=true,MaximumSize=new Size(430,0),Margin=new Padding(3,6,3,6)};
        private readonly Button useSaved=new Button {Name="UseSavedFrame",Text="Use saved frame",AutoSize=true};
        public event Action DefineRequested;
        public event Action UseSavedRequested;

        public FrameAssignmentPanel()
        {
            Name="FrameAssignmentPanel";AutoSize=true;AutoSizeMode=AutoSizeMode.GrowAndShrink;
            var body=new FlowLayoutPanel {AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,FlowDirection=FlowDirection.TopDown,WrapContents=false};
            body.Controls.Add(new Label {AutoSize=true,MaximumSize=new Size(430,0),Text="Frame assignment: open Define / edit frame, select its CAD geometry and click Use current selection. Then return here and Use saved frame. Calibration is a separate step."});
            body.Controls.Add(state);
            var actions=new FlowLayoutPanel {AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,WrapContents=false};
            var define=new Button {Name="DefineFrame",Text="Define / edit frame...",AutoSize=true};
            define.Click+=(s,e)=>DefineRequested?.Invoke();useSaved.Click+=(s,e)=>UseSavedRequested?.Invoke();
            actions.Controls.Add(define);actions.Controls.Add(useSaved);body.Controls.Add(actions);Controls.Add(body);
        }
        public void SetState(bool frameSelected,string configuration,FrameAssignment saved,string projectState,string[] otherConfigurations,string error)
        {
            Visible=frameSelected;
            var available=saved?.Selections?.Count>0 && string.IsNullOrEmpty(error);
            useSaved.Enabled=available;
            state.Text=!string.IsNullOrEmpty(error)?"Could not read the saved frame: "+error:
                available?"Frame definition saved for configuration '"+configuration+"'. Its selection and hull settings reload after restarting SolidWorks.":
                "No frame definition saved for configuration '"+configuration+"'. Define it once using the button below.";
            if(!available && otherConfigurations?.Length>0)
                state.Text+="\r\nSaved definitions exist for: "+string.Join(", ",otherConfigurations)+". Activate the matching configuration to reuse one.";
            state.Text+="\r\n"+(projectState=="saved"?"The frame CAD assignment is also saved in this project.":
                projectState=="other assembly"?"This project's frame currently refers to another assembly.":
                projectState=="missing"?"Use saved frame links the definition to this project and saves the group immediately.":
                "The project frame assignment needs review: "+projectState+".");
        }
    }
}
