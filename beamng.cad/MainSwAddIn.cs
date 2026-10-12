using SolidWorks.Interop.sldworks;
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using BeamNG.Cad.Properties;
using BeamNG.Cad.UI;
using BeamNG.Cad.Preparation;
using BeamNG.Cad.FramePipeline;
using System.Diagnostics;
using Xarial.XCad.Base.Attributes;
using Xarial.XCad.Base.Enums;
using Xarial.XCad.SolidWorks;
using Xarial.XCad.UI.Commands;                
using Xarial.XCad.UI.Commands.Attributes;
using Xarial.XCad.UI.Commands.Enums;

namespace BeamNG.Cad
{
    [ComVisible(true)]
    [Guid("CC0A1EB8-E2C8-435C-BFFE-A3A0DCBC4A60")]
    [Title("beamng.cad")]
    [Description("Prepare CAD selections and generate BeamNG static frame mods")]
    public class MainSwAddIn : SwAddInEx
    {
        [Title("beamng.cad")]
        [CommandGroupInfo(1, "beamng.cad")]
        private enum Commands_e
        {
            [Icon(typeof(CommandIcons), nameof(CommandIcons.Export))]
            [Title("Settings")]
            [CommandItemInfo(true, true, WorkspaceTypes_e.All, true)]
            Settings = 20
        }
        [Title("Frame")]
        [CommandGroupInfo(2, "beamng.cad")]
        [CommandGroupParent(typeof(Commands_e))]
        private enum FrameCommands
        {
            [Icon(typeof(CommandIcons), nameof(CommandIcons.Export))]
            [Title("Define Frame")]
            [CommandItemInfo(true,true,WorkspaceTypes_e.Assembly,true)]
            Define = 10,
            [Icon(typeof(CommandIcons), nameof(CommandIcons.Export))]
            [Title("Show Frame Selection")]
            [CommandItemInfo(true,true,WorkspaceTypes_e.Assembly,true)]
            Show = 11,
            [Icon(typeof(CommandIcons), nameof(CommandIcons.Export))]
            [Title("Generate Frame Mod")]
            [CommandItemInfo(true,true,WorkspaceTypes_e.Assembly,true)]
            Generate = 12
        }
        [Title("Mod")]
        [CommandGroupInfo(3, "beamng.cad")]
        [CommandGroupParent(typeof(Commands_e))]
        private enum ModCommands
        {
            [Icon(typeof(CommandIcons), nameof(CommandIcons.Export))]
            [Title("Manage Mod")]
            [CommandItemInfo(true,true,WorkspaceTypes_e.All,true)]
            Install = 30,
            [Icon(typeof(CommandIcons), nameof(CommandIcons.Export))]
            [Title("Open Build Folder")]
            [CommandItemInfo(true,true,WorkspaceTypes_e.All,true)]
            Open = 31
        }
        private FrameWorkflow frameWindow;
        private bool installing;
        public override void OnConnect()
        {
            CommandManager.AddCommandGroup<Commands_e>().CommandClick += OnButtonClick;
            CommandManager.AddCommandGroup<FrameCommands>().CommandClick += cmd => Guard(() => {
                var model = Application.Documents.Active?.Model as ModelDoc2;
                if(model == null) throw new InvalidOperationException("Open an assembly first.");
                if(cmd == FrameCommands.Show) {
                    var selection = new FrameSelection(Application.Sw, model);
                    selection.Show(PreparationFile.Load(selection.Document).Frame(selection.Configuration));
                } else {
                    if(frameWindow != null && !frameWindow.IsDisposed) { frameWindow.Activate(); return; }
                    frameWindow = new FrameWorkflow(Application.Sw, model);
                    CreatePopupWindow(frameWindow).Show();
                }
            });
            CommandManager.AddCommandGroup<ModCommands>().CommandClick += cmd => Guard(() => {
                if(cmd == ModCommands.Install) {
                    var current=new ExporterSettings(null);var model=Application.Documents.Active?.Model as ModelDoc2;
                    var document=model?.GetPathName();
                    var project=!string.IsNullOrEmpty(document)?current.ProjectForDocument(document):
                        File.Exists(current.LastProjectPath)?VehicleProject.Load(current.LastProjectPath):null;
                    CreatePopupWindow(new ModManager(current,null,project) {SolidWorksApplication=Application.Sw}).Show();
                }
                else {
                    var settings = new ExporterSettings(null);
                    if(!File.Exists(settings.LastBuildReceipt)) throw new InvalidOperationException("Generate a mod first, or select a completed build in Manage Mod.");
                    Process.Start(new ProcessStartInfo(Path.GetDirectoryName(settings.LastBuildReceipt)) { UseShellExecute=true });
                }
            });
        }
        private void Guard(Action action) { try { action(); } catch(Exception e) { Application.ShowMessageBox(e.Message, MessageBoxIcon_e.Error); } }
        private void OnButtonClick(Commands_e cmd)
        {
            Guard(() => {
                using(var form = new Form { Text="beamng.cad - Settings", Width=800, Height=710, ShowInTaskbar=false }) {
                    form.Controls.Add(new SettingsPanel(new ExporterSettings(null)) { AutoScroll=true });
                    form.Controls.Add(new Label { Dock=DockStyle.Bottom, Height=50,
                        Text="beamng.cad - SolidWorks frame preparation and static mod generation. Built with xCAD.NET.\r\nVersion " + typeof(MainSwAddIn).Assembly.GetName().Version });
                    CreatePopupWindow(form).ShowDialog();
                }
            });
        }
        private async void Install()
        {
            if(installing) return;
            installing=true;
            var form=new Form { Text="beamng.cad - Install Mod", Width=750, Height=350, ShowInTaskbar=false };
            var log=new TextBox { Multiline=true, ReadOnly=true, Dock=DockStyle.Fill, ScrollBars=ScrollBars.Vertical };
            form.Controls.Add(log);
            FormClosingEventHandler preventClose=(s,e)=>e.Cancel=installing;
            form.FormClosing+=preventClose;
            CreatePopupWindow(form).Show();
            try {
                var settings=new ExporterSettings(null);
                var installed=await StaticFrameBuilder.InstallAsync(settings.PythonExecutable,settings.LastBuildReceipt,
                    settings.GameDirectory,settings.ModsDirectory,new Progress<string>(line=>log.AppendText(line+System.Environment.NewLine)));
                log.AppendText("Installed: "+installed+System.Environment.NewLine);
            } catch(Exception e) { log.AppendText(e.Message); }
            finally { installing=false;form.FormClosing-=preventClose; }
        }
    }
}
