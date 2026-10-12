using System;
using System.Drawing;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed class AssignmentInspectionPanel : FlowLayoutPanel
    {
        private readonly ComboBox source=new ComboBox {Name="AssignmentSource",DropDownStyle=ComboBoxStyle.DropDownList,Width=225};
        private readonly Button show=new Button {Name="ShowAssignedGeometry",Text="Show in SolidWorks",AutoSize=true};
        private readonly CheckBox zoom=new CheckBox {Name="ZoomToAssignedGeometry",Text="Zoom to group",Checked=true,AutoSize=true};
        private readonly Label summary=new Label {Name="AssignmentSummary",AutoSize=true,MaximumSize=new Size(225,0)};
        private ComponentDefinition component;
        private string selectedId;
        private bool hadAppearance;
        public event Action ShowRequested;
        public bool Appearance {get=>source.SelectedIndex==0;set=>source.SelectedIndex=value?0:1;}
        public bool Zoom=>zoom.Checked;
        public bool PreferAppearance {get;set;}

        public AssignmentInspectionPanel()
        {
            Name="AssignmentInspection";AutoSize=true;AutoSizeMode=AutoSizeMode.GrowAndShrink;
            Dock=DockStyle.Fill;FlowDirection=FlowDirection.TopDown;WrapContents=false;Padding=new Padding(5);
            source.Items.AddRange(new object[]{"Appearance CAD","Physical CAD"});source.SelectedIndex=0;
            Controls.Add(source);Controls.Add(show);Controls.Add(zoom);Controls.Add(summary);
            source.SelectedIndexChanged+=(s,e)=>RefreshState();show.Click+=(s,e)=>ShowCurrent();
            RefreshState();
        }

        public void SetComponent(ComponentDefinition value)
        {
            var hasAppearance=value?.AppearanceSelections?.Count>0;
            var preferAppearance=selectedId!=value?.Id || (!hadAppearance && hasAppearance);
            component=value;selectedId=value?.Id;hadAppearance=hasAppearance;
            if(preferAppearance)source.SelectedIndex=hasAppearance||PreferAppearance?0:1;
            RefreshState();
        }
        private void RefreshState()
        {
            var references=Appearance?component?.AppearanceSelections:component?.Selections;
            source.Enabled=component!=null;show.Enabled=references?.Count>0;zoom.Enabled=show.Enabled;
            summary.Text=component==null?"Select a group to inspect its saved CAD assignment.":
                references==null || references.Count==0?"No saved "+(Appearance?"appearance":"physical CAD")+" selection for this group.":
                references.Count+" saved selection"+(references.Count==1?"":"s")+". Highlighting replaces the current SolidWorks selection.";
            if(Appearance && references?.Count>0 && (component.AppearancePackageState=="pending"||component.AppearancePackageState=="failed"))
                summary.Text+="\r\n"+(component.AppearancePackageState=="failed"?"Saved; package update failed. See Log.":"Saved; package update pending.");
        }
        public void ShowCurrent(){if(show.Enabled && Enabled)ShowRequested?.Invoke();}
    }
}
