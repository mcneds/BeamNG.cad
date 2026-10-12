using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    internal sealed class JointParametersPanel : Form
    {
        private readonly DataGridView grid=new DataGridView {Dock=DockStyle.Fill,AllowUserToAddRows=true,AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill};
        public Dictionary<string,double> Values {get;private set;}
        public JointParametersPanel(Dictionary<string,double> values)
        {
            Text="Physical template parameters (SI units)";Width=700;Height=520;
            grid.Columns.Add("Key","Parameter");grid.Columns.Add("Value","Value (SI units)");
            foreach(var pair in values.OrderBy(v=>v.Key))grid.Rows.Add(pair.Key,pair.Value.ToString("R",CultureInfo.InvariantCulture));
            if(!values.ContainsKey("rack_half_travel_m"))grid.Rows.Add("rack_half_travel_m","0.04");
            if(!values.ContainsKey("rack_speed_m_s"))grid.Rows.Add("rack_speed_m_s","0.1");
            var help=new Label {Dock=DockStyle.Top,Height=110,Padding=new Padding(8),Text="Rack half travel is the distance from centre to either stop, in metres. Rack speed is metres per second (default 0.1); review both against your hardware. Other parameters retain their documented defaults. Shaft-section plunge uses shaft.<component ID>.plunge_m (default 0). Changes require a fresh generated package and verification."};
            var save=new Button {Text="Save parameters",Dock=DockStyle.Bottom,Height=32};save.Click+=(s,e)=>Save();
            Controls.Add(grid);Controls.Add(help);Controls.Add(save);
        }
        private void Save()
        {
            grid.EndEdit();var result=new Dictionary<string,double>();
            foreach(DataGridViewRow row in grid.Rows)
            {
                if(row.IsNewRow)continue;var key=Convert.ToString(row.Cells[0].Value).Trim();var text=Convert.ToString(row.Cells[1].Value).Trim();
                if(key.Length==0&&text.Length==0)continue;
                if(key.Length==0||result.ContainsKey(key)||!double.TryParse(text,NumberStyles.Float,CultureInfo.InvariantCulture,out var value)||double.IsNaN(value)||double.IsInfinity(value))
                {MessageBox.Show(this,"Each parameter needs a unique name and a finite number using a decimal point.");return;}
                result.Add(key,value);
            }
            if(result.TryGetValue("rack_half_travel_m",out var travel)&&(travel<.001||travel>.15)){MessageBox.Show(this,"Rack half travel must be between 0.001 and 0.15 metres.");return;}
            if(result.TryGetValue("rack_speed_m_s",out var speed)&&(speed<.005||speed>.5)){MessageBox.Show(this,"Rack speed must be between 0.005 and 0.5 metres per second.");return;}
            Values=result;DialogResult=DialogResult.OK;
        }
    }
}
