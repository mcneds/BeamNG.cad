using System;
using System.Drawing;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    internal sealed class WorkflowNextStep : GroupBox
    {
        private readonly FlowLayoutPanel body=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true,FlowDirection=FlowDirection.TopDown,WrapContents=false};
        private readonly Label title=new Label {Name="WorkflowNextTitle",AutoSize=true};
        private readonly Label detail=new Label {Name="WorkflowNextDetail",AutoSize=true};
        private readonly Button next=new Button {Name="WorkflowNextAction",AutoSize=false,Padding=new Padding(8,4,8,4)};
        internal event Action FollowRequested;
        public WorkflowNextStep()
        {
            Name="WorkflowNextStep";Text="Next step";Dock=DockStyle.Top;AutoSize=true;Padding=new Padding(6,16,6,6);
            title.Font=new Font(Font,FontStyle.Bold);body.Controls.Add(title);body.Controls.Add(detail);body.Controls.Add(next);Controls.Add(body);
            next.Click+=(s,e)=>FollowRequested?.Invoke();SizeChanged+=(s,e)=>Fit();
        }
        internal void ShowState(VehicleReadiness state,string previewStatus,bool busy)
        {
            Visible=state!=null;
            if(state==null)return;
            var heading=string.IsNullOrEmpty(previewStatus)?state.Title:previewStatus+". "+state.Title;
            if(title.Text!=heading||detail.Text!=state.Detail||next.Text!=state.ActionText)
            {
                title.Text=heading;detail.Text=state.Detail;next.Text=state.ActionText;next.AccessibleName=state.ActionText;Fit();
            }
            next.Enabled=!busy;
        }
        private void Fit()
        {
            var width=Math.Max(1,ClientSize.Width-Padding.Horizontal-8);
            body.MaximumSize=new Size(width,0);title.MaximumSize=detail.MaximumSize=new Size(width,0);
            next.Width=Math.Min(width,TextRenderer.MeasureText(next.Text,next.Font).Width+next.Padding.Horizontal+8);
            var text=TextRenderer.MeasureText(next.Text,next.Font,new Size(Math.Max(1,next.Width-next.Padding.Horizontal-8),int.MaxValue),TextFormatFlags.WordBreak|TextFormatFlags.NoPrefix);
            next.Height=Math.Max((int)Math.Ceiling(32*next.DeviceDpi/96.0),text.Height+next.Padding.Vertical+8);
        }
    }
}
