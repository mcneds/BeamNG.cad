using System;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed partial class ComponentWorkflow
    {
        private ComponentDefinition draftOwner;
        private string draftBaseline="";
        private bool loadingDraft;
        private readonly Label draftState=new Label {Name="ComponentDraftState",AutoSize=true};
        private readonly FlowLayoutPanel draftFooter=new FlowLayoutPanel {Dock=DockStyle.Bottom,AutoSize=true,WrapContents=true};
        private string DraftKey()=>new System.Web.Script.Serialization.JavaScriptSerializer().Serialize(new object[] {
            componentName.Text,(mvpRole.SelectedItem as MvpRole)?.Id,template.SelectedItem,method.SelectedItem,
            spacing.Value,alpha.Value,wrapOffset.Value,thickness.Value,surfaceMass.SelectedIndex,
            (visualParent.SelectedItem as AnchorItem)?.Id,representation.SelectedIndex,massPolicy.SelectedIndex,
            customMass.Value,(visualMember.SelectedItem as AnchorItem)?.Id,flipAutoNormal.Checked,
            CoiloverAppearance.Supported(draftOwner)?coiloverPanel.SpringSettings:null});
        internal bool HasPendingChanges=>!loadingDraft&&draftOwner!=null&&DraftKey()!=draftBaseline;
        internal bool IsBusy=>cancel!=null;
        internal string TaskMessage=>status.Text;
        internal string TaskLog=>log.Text;
        internal VehicleProject CurrentProject=>project;
        internal event Action ProjectChanged;
        internal event Action<string> NavigationRequested;
        internal event Action<VehicleProject,SolidWorks.Interop.sldworks.ModelDoc2> ContextChanged;
        internal event Action FreshProjectRequested;
        private bool routingStage,dockedNavigation;
        internal void StopTask()=>cancel?.Cancel();
        private void InitializeDrafts()
        {
            var apply=new Button {Name="ApplyComponentChanges",Text="Apply component changes",AutoSize=true};
            var discard=new Button {Name="DiscardComponentChanges",Text="Discard",AutoSize=true};
            apply.Click+=(s,e)=>{try{SaveParameters();}catch(Exception error){status.Text=error.Message;}};
            discard.Click+=(s,e)=>LoadParameters();
            draftFooter.Controls.Add(draftState);draftFooter.Controls.Add(apply);draftFooter.Controls.Add(discard);Controls.Add(draftFooter);editor.BringToFront();
            foreach(var input in new Control[] {componentName,mvpRole,template,method,surfaceMass,visualParent,representation,massPolicy,visualMember,customMass,thickness,spacing,alpha,wrapOffset,flipAutoNormal})
            {
                if(input is TextBox text)text.TextChanged+=(s,e)=>UpdateDraftState();
                else if(input is ComboBox combo)combo.SelectedIndexChanged+=(s,e)=>UpdateDraftState();
                else if(input is NumericUpDown number)number.ValueChanged+=(s,e)=>UpdateDraftState();
                else if(input is CheckBox check)check.CheckedChanged+=(s,e)=>UpdateDraftState();
            }
            coiloverPanel.SpringChanged+=UpdateDraftState;
            UpdateDraftState();
        }
        private void UpdateDraftState()
        {
            if(loadingDraft)return;
            draftState.Text=HasPendingChanges?"Changes pending: component fields / spring settings":"Component changes saved";
        }
        internal bool ResolveDraft()
        {
            if(!drivelinePanel.ResolveChanges())return false;
            if(!HasPendingChanges)return true;
            var answer=MessageBox.Show(this,"Apply changes to '"+draftOwner.Name+"' before continuing?\r\nYes applies all edited component fields and spring settings. No discards them.","Pending component changes",MessageBoxButtons.YesNoCancel,MessageBoxIcon.Question);
            if(answer==DialogResult.Cancel)return false;
            if(answer==DialogResult.No){LoadParameters();return true;}
            try{SaveParameters();return true;}catch(Exception error){status.Text=error.Message;return false;}
        }
        private void ComponentSelectionChanged()
        {
            if(refreshingComponents)return;
            var requested=Selected;
            if(draftOwner!=null&&requested?.Id!=draftOwner.Id&&HasPendingChanges)
            {
                refreshingComponents=true;components.SelectedItem=draftOwner;refreshingComponents=false;
                if(!ResolveDraft())return;
                refreshingComponents=true;components.SelectedItem=project.Components.FirstOrDefault(c=>c.Id==requested?.Id);refreshingComponents=false;
            }
            LoadParameters();
        }
        internal void ShowStage(string stage)
        {
            var tabs=(TabControl)Controls.Find("WorkflowPages",true).Single();
            string title=stage=="Project"?"Vehicle setup / MVP":stage=="Joints"?"Joints & mounts":stage;
            var page=tabs.TabPages.Cast<TabPage>().FirstOrDefault(p=>p.Text==title);
            routingStage=true;try{if(page!=null)tabs.SelectedTab=page;}finally{routingStage=false;}
        }
        internal void HideDockedTaskControls(){status.Visible=false;progress.Visible=false;stop.Visible=false;}
        internal void FocusComponent(string componentId)
        {
            if(!ResolveDraft())return;
            if(componentSearch.Text.Length>0)componentSearch.Clear();
            var component=components.Items.Cast<ComponentDefinition>().FirstOrDefault(c=>c.Id==componentId);
            if(component==null)return;
            components.SelectedItem=component;
            var details=(TabControl)Controls.Find("ComponentDetails",true).Single();
            details.SelectedIndex=0;
            components.Focus();
        }
        internal void UseDockedNavigation()
        {
            var tabs=(TabControl)Controls.Find("WorkflowPages",true).Single();
            if(!dockedNavigation){dockedNavigation=true;tabs.Selected+=(s,e)=>{if(!routingStage)NavigationRequested?.Invoke(e.TabPage.Text=="Joints & mounts"?"Joints":e.TabPage.Text=="Vehicle setup / MVP"?"Project":e.TabPage.Text);};}
            tabs.Appearance=TabAppearance.FlatButtons;tabs.SizeMode=TabSizeMode.Fixed;tabs.ItemSize=new System.Drawing.Size(0,1);
            activeProject.Visible=false;status.Visible=false;progress.Visible=false;stop.Visible=false;
        }
        internal void ReloadProject()
        {
            if(IsBusy||!ResolveDraft())return;
            project=VehicleProject.Load(project.FilePath);RefreshFrameDefinition();RefreshLists();ProjectChanged?.Invoke();
        }
    }
}
