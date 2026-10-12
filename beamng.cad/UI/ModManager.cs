using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using BeamNG.Cad.FramePipeline;
using BeamNG.Cad.Preparation;
using ISldWorks = SolidWorks.Interop.sldworks.ISldWorks;

namespace BeamNG.Cad.UI
{
    internal sealed class ModManager : Form
    {
        private readonly ExporterSettings settings;
        private string profilePath;
        private VehicleProject project;
        private bool explicitBuild;
        private Button applyButton,installButton;
        private readonly TextBox receipt=new TextBox {Name="ModReceipt",Dock=DockStyle.Fill,ReadOnly=true};
        private readonly TextBox name=new TextBox {Name="ModName",Dock=DockStyle.Fill};
        private readonly TextBox brand=new TextBox {Name="ModBrand",Dock=DockStyle.Fill};
        private readonly TextBox author=new TextBox {Name="ModAuthor",Dock=DockStyle.Fill};
        private readonly TextBox description=new TextBox {Name="ModDescription",Dock=DockStyle.Fill};
        private readonly TextBox configuration=new TextBox {Name="ModConfiguration",Dock=DockStyle.Fill};
        private readonly Label selector=new Label {AutoSize=true,Dock=DockStyle.Top};
        private readonly Label status=new Label {Name="ModStatus",AutoSize=true,Dock=DockStyle.Top};
        private readonly PictureBox picture=new PictureBox {Name="ModPreview",SizeMode=PictureBoxSizeMode.Zoom,Height=180,Dock=DockStyle.Top,BackColor=Color.FromArgb(35,40,46)};
        private readonly TextBox log=new TextBox {Name="ModLog",Dock=DockStyle.Fill,Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical};
        private readonly Panel inputs=new Panel {Dock=DockStyle.Top,AutoSize=true};
        private readonly CheckBox reinstall=new CheckBox {Name="ReinstallMod",Text="Reinstall / overwrite the installed ZIP, even if this build already matches (backup kept)",AutoSize=true};
        private string imagePath="";
        private bool busy;
        private bool unappliedEdits;
        public ISldWorks SolidWorksApplication { get; set; }
        public ModManager(ExporterSettings settings,string profilePath)
            :this(settings,profilePath,null) {}
        public ModManager(ExporterSettings settings,string profilePath,VehicleProject project)
        {
            this.settings=settings;this.project=project;this.profilePath=project?.ProfilePath??profilePath??ModProfile.DefaultPath;
            Text="beamng.cad - Manage Mod";Width=820;Height=850;MinimumSize=new Size(650,700);ShowInTaskbar=false;
            var layout=new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=1,RowCount=4,Padding=new Padding(12)};
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));Controls.Add(layout);
            var fields=new TableLayoutPanel {Dock=DockStyle.Top,AutoSize=true,ColumnCount=2};
            fields.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,135));fields.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            AddField(fields,"Selected build",receipt);AddField(fields,"Vehicle name",name);AddField(fields,"Brand (optional)",brand);
            AddField(fields,"Author",author);AddField(fields,"Description",description);AddField(fields,"Configuration",configuration);
            var actions=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
            Button(actions,"Choose build...",()=> {using(var picker=new OpenFileDialog {Filter="Build receipt|static_frame_build.json",InitialDirectory=settings.FrameOutput})if(picker.ShowDialog(this)==DialogResult.OK){ValidateProjectBuild(picker.FileName);receipt.Text=picker.FileName;explicitBuild=true;RememberBuild();RefreshStatus();}});
            Button(actions,"Follow latest package",()=>{explicitBuild=false;RefreshStatus();});
            Button(actions,"Create independent mod copy...",()=>{
                if(this.project==null)throw new InvalidOperationException("Open a saved assembly's vehicle project first.");
                using(var picker=new SaveFileDialog {Filter="Vehicle project|*.beamng-project.json",FileName="vehicle-copy.beamng-project.json"})
                    if(picker.ShowDialog(this)==DialogResult.OK){SaveProfile();this.project=this.project.Fork(picker.FileName);this.profilePath=this.project.ProfilePath;settings.SelectProject(this.project);settings.Save();receipt.Clear();explicitBuild=false;RefreshStatus();}
            });
            Button(actions,"Choose image...",()=> {using(var picker=new OpenFileDialog {Filter="Images|*.jpg;*.jpeg;*.png;*.bmp"})if(picker.ShowDialog(this)==DialogResult.OK)SetImage(ModPackage.ImportImage(picker.FileName,this.profilePath));});
            Button(actions,"Use hull image",()=>SetImage(ModPackage.HullImage(receipt.Text,this.profilePath)));
            Button(actions,"Capture SolidWorks viewport",CaptureViewport);
            Button(actions,"Remove image",()=>SetImage(""));
            var edit=new TableLayoutPanel {Dock=DockStyle.Top,AutoSize=true,ColumnCount=1};edit.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            edit.Controls.Add(fields);edit.Controls.Add(selector);edit.Controls.Add(picture);edit.Controls.Add(actions);
            var buttons=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true};
            Button(buttons,"Save for future builds",()=> {SaveProfile();status.Text="Name and image saved for future builds. Apply to update the selected build.";});
            applyButton=Button(buttons,"Apply to selected build",()=>Run(Apply));
            installButton=Button(buttons,"Install selected build",()=>Run(Install));
            Button(buttons,"Refresh status",RefreshStatus);
            Button(buttons,"Open build folder",()=>Open(Path.GetDirectoryName(receipt.Text)));
            Button(buttons,"Open mods folder",()=>Open(settings.ModsDirectory));
            Button(buttons,"Open calibration report",()=>Process.Start(new ProcessStartInfo(ModPackage.CalibrationReport(receipt.Text)){UseShellExecute=true}));
            edit.Controls.Add(reinstall);edit.Controls.Add(buttons);inputs.Controls.Add(edit);layout.Controls.Add(inputs,0,0);
            layout.Controls.Add(new Label {AutoSize=true,Text="Package the generated mod before applying edits. Apply creates a new revision; Install replaces only this project's package.\r\nDisplay names can change. The package identity stays stable across rebuilds. Installation checks compare files on disk."},0,1);
            layout.Controls.Add(status,0,2);layout.Controls.Add(log,0,3);
            var profile=ModProfile.Load(this.profilePath);name.Text=profile.Name;brand.Text=profile.Brand;author.Text=profile.Author;
            description.Text=profile.Description;configuration.Text=profile.Configuration;receipt.Text=project?.LastBuildReceipt??settings.LastBuildReceipt;
            try {SetImage(profile.PreviewImage??"");}catch(Exception e){WriteLog("Saved preview unavailable: "+e.Message);}
            unappliedEdits=false;
            foreach(var input in new[]{name,brand,author,description,configuration})input.TextChanged+=(s,e)=>{unappliedEdits=true;UpdateTitle();};
            UpdateTitle();
            Shown+=(s,e)=>Guard(RefreshStatus);
            Activated+=(s,e)=>{if(!busy)Guard(RefreshStatus);};
            FormClosing+=(s,e)=> {if(busy)e.Cancel=true;};
            FormClosed+=(s,e)=>picture.Image?.Dispose();
        }
        private void UpdateTitle()=>selector.Text="Vehicle selector label: "+(brand.Text.Trim()+" "+name.Text.Trim()).Trim();
        private void CaptureViewport()
        {
            // Keep the manager itself out of the captured graphics area.
            Hide();
            try
            {
                SetImage(ViewportThumbnail.Capture(SolidWorksApplication,profilePath));
                status.Text="Current SolidWorks view captured. Apply to selected build, then install to update the thumbnail.";
            }
            finally { Show(); Activate(); }
        }
        private void SetImage(string file)
        {
            Image next=null;
            if(!string.IsNullOrEmpty(file))using(var original=Image.FromFile(file))next=new Bitmap(original);
            var previous=picture.Image;picture.Image=next;previous?.Dispose();imagePath=file;unappliedEdits=true;
        }
        private void SaveProfile()=>new ModProfile {Name=name.Text.Trim(),Brand=brand.Text.Trim(),Author=author.Text.Trim(),Description=description.Text.Trim(),Configuration=configuration.Text.Trim(),PreviewImage=imagePath}.Save(profilePath);
        private async Task Apply()
        {
            RefreshStatus();ValidateProjectBuild(receipt.Text);
            SaveProfile();
            receipt.Text=await ModPackage.CustomizeForProjectAsync(settings.PythonExecutable,receipt.Text,profilePath,new Progress<string>(WriteLog),CancellationToken.None,string.IsNullOrWhiteSpace(settings.FrameOutput)?null:settings.FrameOutput,project?.FilePath);
            unappliedEdits=false;
            RememberBuild();RefreshStatus();
        }
        private async Task Install()
        {
            RefreshStatus();ValidateProjectBuild(receipt.Text);
            if(unappliedEdits)throw new InvalidOperationException("Apply the edited name/image to the selected build before installing it.");
            await StaticFrameBuilder.InstallAsync(settings.PythonExecutable,receipt.Text,settings.GameDirectory,settings.ModsDirectory,new Progress<string>(WriteLog),reinstall.Checked);
            RememberBuild();RefreshStatus();
            WriteLog("Installed ZIP verified. Reopen the vehicle selector; if it still shows the previous entry, reload the mod in BeamNG's Mod Manager or restart BeamNG.");
        }
        private async void Run(Func<Task> work)
        {
            if(busy)return;busy=true;inputs.Enabled=false;
            try{await work();}catch(Exception e){status.Text=e.Message;WriteLog(e.Message);}finally{busy=false;inputs.Enabled=true;}
        }
        private void RememberBuild()
        {
            project?.SelectBuild(receipt.Text);settings.LastBuildReceipt=receipt.Text;
            if(project!=null)settings.LastProjectPath=project.FilePath;
            settings.Save();
        }
        private void ValidateProjectBuild(string path)
        {
            ModPackage.ArchivePath(path);
            var record=JsonFile.Read<ModBuildRecord>(path);
            if(project!=null && record.identity!=null && record.identity.Id!=project.Identity.Id)
                throw new InvalidDataException("This build belongs to a different vehicle project.");
        }
        private void RefreshStatus()
        {
            if(!explicitBuild && project!=null){project=VehicleProject.Load(project.FilePath);receipt.Text=project.LastBuildReceipt??"";}
            applyButton.Enabled=installButton.Enabled=false;
            if(!File.Exists(receipt.Text)){status.Text="No package available. Use Package calibrated mod, or choose an existing build receipt.";return;}
            ValidateProjectBuild(receipt.Text);
            status.Text=ModPackage.Describe(receipt.Text,settings.ModsDirectory);
            applyButton.Enabled=installButton.Enabled=true;
        }
        private void WriteLog(string message)=>log.AppendText(message+Environment.NewLine);
        private void Guard(Action action){try{action();}catch(Exception e){status.Text=e.Message;WriteLog(e.Message);}}
        private Button Button(Control parent,string text,Action action)
        {var button=new Button {Text=text,AutoSize=true};button.Click+=(s,e)=>Guard(action);parent.Controls.Add(button);return button;}
        private static void AddField(TableLayoutPanel fields,string label,Control input)
        {var row=fields.RowCount++;fields.RowStyles.Add(new RowStyle(SizeType.AutoSize));fields.Controls.Add(new Label {Text=label,AutoSize=true,Margin=new Padding(3,6,3,6)},0,row);fields.Controls.Add(input,1,row);}
        private static void Open(string folder)
        {if(!Directory.Exists(folder))throw new DirectoryNotFoundException("Select an existing folder first.");Process.Start(new ProcessStartInfo(folder){UseShellExecute=true});}
    }
}
