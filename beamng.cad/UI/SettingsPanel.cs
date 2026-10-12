using System;
using System.IO;
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
            var save = new Button { Name = "SaveSettings", Text = "Save settings", AutoSize = true };
            var status = new Label { Name = "SettingsStatus", AutoSize = true, Dock = DockStyle.Top, Text = settings.LoadError ?? "" };
            save.Click += (sender, args) =>
            {
                try
                {
                    var gamePath = game.Text.Trim();
                    var modsPath = mods.Text.Trim();
                    if (!Path.IsPathRooted(gamePath) || !File.Exists(Path.Combine(gamePath, "BeamNG.drive.exe")))
                        throw new ArgumentException("Select the installation folder containing BeamNG.drive.exe.");
                    if (!Path.IsPathRooted(modsPath) || !Directory.Exists(modsPath)
                        || !string.Equals(new DirectoryInfo(modsPath).Name, "mods", StringComparison.OrdinalIgnoreCase))
                        throw new ArgumentException("Select an existing mods folder in your BeamNG user folder.");
                    gamePath = Path.GetFullPath(gamePath).TrimEnd(Path.DirectorySeparatorChar);
                    modsPath = Path.GetFullPath(modsPath).TrimEnd(Path.DirectorySeparatorChar);
                    if (modsPath.StartsWith(gamePath + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                        throw new ArgumentException("The mods folder must be outside the game installation.");
                    settings.GameDirectory = gamePath;
                    settings.ModsDirectory = modsPath;
                    settings.Save();
                    status.Text = "Settings saved";
                }
                catch (Exception error) { status.Text = error.Message; }
            };
            Action persist = () => {
                try { settings.Save(); status.Text = "Settings saved"; }
                catch (Exception e) { status.Text = "Could not save settings: " + e.Message; }
            };
            var dirty = false;
            var timer = new Timer { Interval = 500 };
            timer.Tick += (s, e) => { timer.Stop(); if (dirty) { persist(); dirty = false; } };
            // Update only the field that was edited. Other panels share this settings
            // object and may have newer values than this panel's inactive controls.
            Action<TextBox, Action<string>> bind = (input, update) =>
                input.TextChanged += (s, e) => {
                    update(input.Text.Trim()); dirty = true; timer.Stop(); timer.Start();
                };
            bind(game, value => settings.GameDirectory = value);
            bind(mods, value => settings.ModsDirectory = value);
            bind(python, value => settings.PythonExecutable = value);
            bind(calibrationPython, value => settings.CalibrationPythonExecutable = value);
            bind(harnessProfile, value => settings.HarnessProfile = value);
            bind(blender, value => settings.BlenderExecutable = value);
            bind(cgal, value => settings.CgalPythonExecutable = value);
            bind(material, value => settings.FrameSource = value);
            bind(output, value => settings.FrameOutput = value);
            var reports=new CheckBox {Name="SettingsSaveBuildReports",AutoSize=true,Text="Save full build report (failures are always kept)",Checked=settings.SaveBuildReports=="true"};
            reports.CheckedChanged+=(s,e)=>{settings.SaveBuildReports=reports.Checked?"true":"false";persist();};
            layout.Controls.Add(reports);
            Disposed += (s, e) => { timer.Dispose(); if (dirty) persist(); };
            layout.Controls.Add(save);
            layout.Controls.Add(status);
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
