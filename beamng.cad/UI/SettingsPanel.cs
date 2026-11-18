using System;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    internal sealed class SettingsPanel : UserControl
    {
        public SettingsPanel(ExporterSettings settings)
        {
            Dock = DockStyle.Fill; AutoScroll = true;
            var layout = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1, RowCount = 10 };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            Controls.Add(layout);
            layout.Controls.Add(new Label
            {
                Dock = DockStyle.Top, AutoSize = true,
                Text = "Choose your BeamNG installation and the mods folder for your active user profile.\r\n"
                    + "In the BeamNG launcher, use Manage User Folder → Open in Explorer to find it.\r\n"
                    + "Select its mods subfolder. Mods are installed as ZIPs; the game installation stays unchanged."
            });
            var game = AddFolder(layout, "BeamNG installation", "GameDirectory", settings.GameDirectory);
            var mods = AddFolder(layout, "BeamNG mods folder", "ModsDirectory", settings.ModsDirectory);
            layout.Controls.Add(new Label
            {
                AutoSize = true, Dock = DockStyle.Top,
                Text = "Replacing a generated mod keeps the old ZIP in TrueMeshExporter-backups\r\n"
                    + "beside the mods folder. Existing unpacked copies must be resolved first."
            });
            var python = AddFolder(layout, "Python executable", "PythonExecutable", settings.PythonExecutable);
            var calibrationPython = AddFolder(layout, "Calibration Python (3.11+, NumPy, SciPy, Matplotlib)", "CalibrationPythonExecutable", settings.CalibrationPythonExecutable);
            var harnessProfile = AddFolder(layout, "Isolated BeamNG verification profile", "HarnessProfile", settings.HarnessProfile);
            var blender = AddFolder(layout, "Blender executable", "BlenderExecutable", settings.BlenderExecutable);
            var cgal = AddFolder(layout, "CGAL Python executable", "CgalPythonExecutable", settings.CgalPythonExecutable);
            var material = AddFolder(layout, "Material/settings source folder", "SettingsFrameSource", settings.FrameSource);
            var output = AddFolder(layout, "Build directory (exports, calibration, packages and worker scratch)", "SettingsFrameOutput", settings.FrameOutput);
            var reports=new CheckBox {Name="SettingsSaveBuildReports",AutoSize=true,Text="Save full build report (failures are always kept)",Checked=settings.SaveBuildReports=="true"};
            layout.Controls.Add(reports);
            var fields=new System.Collections.Generic.Dictionary<string,TextBox> {
                {"GameDirectory",game},{"ModsDirectory",mods},{"PythonExecutable",python},
                {"CalibrationPythonExecutable",calibrationPython},{"HarnessProfile",harnessProfile},
                {"BlenderExecutable",blender},{"CgalPythonExecutable",cgal},{"FrameSource",material},{"FrameOutput",output}};
            var baseline=fields.ToDictionary(p=>p.Key,p=>p.Value.Text.Trim());
            var originalReports=reports.Checked;
            var status=new Label {Name="SettingsStatus",AutoSize=true,Dock=DockStyle.Top,Text=settings.LoadError??""};
            pending=()=>fields.Any(p=>p.Value.Text.Trim()!=baseline[p.Key])||reports.Checked!=originalReports;
            apply=()=>{
                try {
                    foreach(var pair in fields.Where(p=>p.Value.Text.Trim()!=baseline[p.Key])) {
                        var value=pair.Value.Text.Trim();
                        if(value.Length==0 && pair.Key!="GameDirectory" && pair.Key!="ModsDirectory")continue;
                        string error=null;
                        if(!Path.IsPathRooted(value))error="Choose an absolute path.";
                        else if(pair.Key=="GameDirectory"&&!File.Exists(Path.Combine(value,"BeamNG.drive.exe")))error="Choose the folder containing BeamNG.drive.exe.";
                        else if(pair.Key=="ModsDirectory"&&(!Directory.Exists(value)||!string.Equals(new DirectoryInfo(value).Name,"mods",StringComparison.OrdinalIgnoreCase)))error="Choose an existing BeamNG user mods folder.";
                        else if(pair.Key.EndsWith("Executable")&&!File.Exists(value))error="Choose an existing executable.";
                        else if((pair.Key=="FrameSource"||pair.Key=="HarnessProfile")&&!Directory.Exists(value))error="Choose an existing directory.";
                        if(error!=null){pair.Value.Focus();throw new ArgumentException(pair.Value.AccessibleName+": "+error);}
                    }
                    if((game.Text.Trim()!=baseline["GameDirectory"]||mods.Text.Trim()!=baseline["ModsDirectory"]) && game.Text.Trim().Length>0 && mods.Text.Trim().Length>0 && Path.GetFullPath(mods.Text.Trim()).StartsWith(Path.GetFullPath(game.Text.Trim()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))
                        throw new ArgumentException("The mods folder must be outside the game installation.");
                    // Reload before applying only changed fields, preserving edits from other panels.
                    var latest=settings.Reload();
                    foreach(var pair in fields.Where(p=>p.Value.Text.Trim()!=baseline[p.Key]))typeof(ExporterSettings).GetProperty(pair.Key).SetValue(latest,pair.Value.Text.Trim());
                    if(reports.Checked!=originalReports)latest.SaveBuildReports=reports.Checked?"true":"false";
                    latest.Save();
                    foreach(var pair in fields){var value=(string)typeof(ExporterSettings).GetProperty(pair.Key).GetValue(latest);typeof(ExporterSettings).GetProperty(pair.Key).SetValue(settings,value);pair.Value.Text=value;baseline[pair.Key]=value;}
                    settings.SaveBuildReports=latest.SaveBuildReports;reports.Checked=latest.SaveBuildReports=="true";originalReports=reports.Checked;
                    status.Text="Settings applied.";return true;
                } catch(Exception error){status.Text=error.Message;return false;}
            };
            discard=()=>{foreach(var pair in fields)pair.Value.Text=baseline[pair.Key];reports.Checked=originalReports;status.Text="Changes discarded.";};
            var buttons=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Top};
            var save=new Button {Name="SaveSettings",Text="Apply settings",AutoSize=true};save.Click+=(s,e)=>apply();buttons.Controls.Add(save);
            var cancel=new Button {Name="DiscardSettings",Text="Discard changes",AutoSize=true};cancel.Click+=(s,e)=>discard();buttons.Controls.Add(cancel);
            foreach(var input in fields.Values)input.TextChanged+=(s,e)=>status.Text=HasPendingChanges?"Settings changes pending. Apply or discard them.":"";
            reports.CheckedChanged+=(s,e)=>status.Text=HasPendingChanges?"Settings changes pending. Apply or discard them.":"";
            layout.Controls.Add(buttons);layout.Controls.Add(status);
        }
        private Func<bool> pending=()=>false;
        private Func<bool> apply=()=>true;
        private Action discard=()=>{};
        public bool HasPendingChanges=>pending();
        internal bool ApplyChanges()=>apply();
        internal bool ResolveChanges()
        {
            if(!HasPendingChanges)return true;
            var choice=MessageBox.Show(this,"Apply the pending settings changes?", "Settings changes",MessageBoxButtons.YesNoCancel,MessageBoxIcon.Question);
            if(choice==DialogResult.Cancel)return false;
            if(choice==DialogResult.Yes)return apply();
            discard();return true;
        }
        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);var host=FindForm();if(host!=null)host.FormClosing+=(s,args)=>{if(!ResolveChanges())args.Cancel=true;};
        }

        private static TextBox AddFolder(TableLayoutPanel parent, string label, string name, string value)
        {
            var row = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, RowCount = 2 };
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            var caption = new Label { Text = label, AutoSize = true };
            row.Controls.Add(caption, 0, 0);
            row.SetColumnSpan(caption, 2);
            var text = new TextBox { Name = name, Text = value, Dock = DockStyle.Fill, AccessibleName = label };
            var browse = new Button { Text = "Browse…", AutoSize = true };
            browse.Click += (sender, args) =>
            {
                if (name.EndsWith("Executable")) {
                    using (var picker = new OpenFileDialog { Filter = "Executables|*.exe", FileName = text.Text })
                        if (picker.ShowDialog(parent) == DialogResult.OK) text.Text = picker.FileName;
                    return;
                }
                using (var dialog = new FolderBrowserDialog { Description = label, SelectedPath = text.Text })
                    if (dialog.ShowDialog(parent) == DialogResult.OK) text.Text = dialog.SelectedPath;
            };
            row.Controls.Add(text, 0, 1);
            row.Controls.Add(browse, 1, 1);
            parent.Controls.Add(row);
            return text;
        }
    }
}
