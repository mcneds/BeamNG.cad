using System;
using System.Linq;
using System.Drawing;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed class CoiloverPanel : FlowLayoutPanel
    {
        private readonly ListBox pieces=new ListBox {Name="CoiloverPieces",Width=360,Height=80};
        private readonly ComboBox mount=new ComboBox {Name="CoiloverHousingMount",DropDownStyle=ComboBoxStyle.DropDownList,Width=360};
        private readonly Label summary=new Label {AutoSize=true,MaximumSize=new Size(480,0)};
        private readonly FlowLayoutPanel actions=new FlowLayoutPanel {AutoSize=true};
        private readonly FlowLayoutPanel springControls=new FlowLayoutPanel {AutoSize=true,FlowDirection=FlowDirection.TopDown,WrapContents=false};
        private readonly ComboBox springMode=new ComboBox {Name="CoiloverSpringMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=360};
        private readonly NumericUpDown mainRate=Number("MainSpringRate",30),tenderRate=Number("TenderSpringRate",15),crossover=Number("CrossoverCompression",10);
        private bool loading;
        public event Action AssignRequested,ShowRequested,ClearRequested,MountChanged;
        public event Action SpringChanged;
        public CoiloverSpring SpringSettings=>new CoiloverSpring {Mode=springMode.SelectedIndex==1?"dual_rate":"auto",MainRateNPerM=(double)mainRate.Value*1000,TenderRateNPerM=(double)tenderRate.Value*1000,CrossoverCompressionM=(double)crossover.Value/1000};
        public string Kind=>CoiloverAppearance.Kinds[Math.Max(0,pieces.SelectedIndex)];
        public string HousingMount=>mount.SelectedIndex==1?"bottom":"top";
        public CoiloverPanel()
        {
            Name="CoiloverAssignments";AutoSize=true;FlowDirection=FlowDirection.TopDown;WrapContents=false;Dock=DockStyle.Top;Padding=new Padding(8);
            Controls.Add(new Label {AutoSize=true,MaximumSize=new Size(480,0),Text="Select a coilover group, then assign its housing, shaft and coil spring separately. Include each mounting eye and spring seat with the rigid piece it follows. These are visual subdivisions; physical mass and tuning remain with the parent group."});
            mount.Items.AddRange(new object[]{"Housing at chassis mount (top)","Housing at suspension mount (bottom)"});mount.SelectedIndex=0;
            Controls.Add(mount);Controls.Add(pieces);Controls.Add(actions);Controls.Add(summary);
            Add("Assign selected bodies",()=>AssignRequested?.Invoke());Add("Show piece in SolidWorks",()=>ShowRequested?.Invoke());Add("Clear piece",()=>ClearRequested?.Invoke());
            mount.SelectedIndexChanged+=(s,e)=>{if(!loading)MountChanged?.Invoke();};
            Controls.Add(springControls);
            springControls.Controls.Add(new Label {Text="Spring physics (requires Regenerate physics / package)",AutoSize=true});
            springMode.Items.AddRange(new object[]{"Automatic single-rate spring","Two-stage springs with crossover"});springMode.SelectedIndex=0;springControls.Controls.Add(springMode);
            Field("Main spring rate (N/mm)",mainRate);Field("Tender spring rate (N/mm)",tenderRate);Field("Crossover bump from CAD ride position (mm)",crossover);
            springControls.Controls.Add(new Label {AutoSize=true,MaximumSize=new Size(480,0),Text="Enter your hardware values; the displayed starting values are examples. Both coils may share the Spring mesh slot. Individual tender lockup/crossover-collar animation is not yet modeled."});
            springControls.Controls.Add(new Label {Text="Apply spring edits with Apply component changes below.",AutoSize=true});
            foreach(var number in new[]{mainRate,tenderRate,crossover})number.ValueChanged+=(s,e)=>{if(!loading)SpringChanged?.Invoke();};
            springMode.SelectedIndexChanged+=(s,e)=>{mainRate.Enabled=tenderRate.Enabled=crossover.Enabled=springMode.SelectedIndex==1;if(!loading)SpringChanged?.Invoke();};
        }
        private static NumericUpDown Number(string name,decimal value)=>new NumericUpDown {Name=name,Minimum=.001m,Maximum=100000,DecimalPlaces=3,Value=value,Width=100};
        private void Field(string text,Control value){var row=new FlowLayoutPanel {AutoSize=true,WrapContents=false};row.Controls.Add(new Label {Text=text,Width=290,Height=26});row.Controls.Add(value);springControls.Controls.Add(row);}
        private void Add(string title,Action action){var button=new Button {Text=title,AutoSize=true};button.Click+=(s,e)=>action();actions.Controls.Add(button);}
        public void SetComponent(ComponentDefinition c)
        {
            loading=true;
            try
            {
                var selected=Math.Max(0,pieces.SelectedIndex);pieces.Items.Clear();
                foreach(var kind in CoiloverAppearance.Kinds)
                {
                    var piece=c?.AppearanceCoilover?.Pieces?.FirstOrDefault(p=>p.Kind==kind);
                    pieces.Items.Add(char.ToUpper(kind[0])+kind.Substring(1)+": "+(piece?.Selections?.Count>0?piece.BodyIds.Count+" bodies saved":"not assigned"));
                }
                pieces.SelectedIndex=selected;mount.SelectedIndex=c?.AppearanceCoilover?.HousingMount=="bottom"?1:0;
                var supported=CoiloverAppearance.Supported(c);pieces.Enabled=mount.Enabled=actions.Enabled=springControls.Enabled=supported;
                var settings=c?.CoiloverSpring??new CoiloverSpring();springMode.SelectedIndex=settings.Mode=="dual_rate"?1:0;
                mainRate.Value=Math.Max(mainRate.Minimum,Math.Min(mainRate.Maximum,(decimal)(settings.MainRateNPerM/1000)));
                tenderRate.Value=Math.Max(tenderRate.Minimum,Math.Min(tenderRate.Maximum,(decimal)(settings.TenderRateNPerM/1000)));
                crossover.Value=Math.Max(crossover.Minimum,Math.Min(crossover.Maximum,(decimal)(settings.CrossoverCompressionM*1000)));
                mainRate.Enabled=tenderRate.Enabled=crossover.Enabled=springMode.SelectedIndex==1;
                summary.Text=!supported?"Select an FL, FR, RL or RR spring/damper group.":CoiloverAppearance.Active(c)?"All three slots are required for telescoping visuals. Package saved appearances applies them to the existing physics.":"No split assigned yet: the existing combined mesh is retained. Assign all three pieces to enable telescoping visuals.";
            }
            finally{loading=false;}
        }
    }
}
