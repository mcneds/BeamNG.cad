using System;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using System.Collections.Generic;
using BeamNG.Cad.Preparation;
namespace BeamNG.Cad.UI
{
    internal sealed class SelectedProjectUnavailableException : IOException
    {
        public string ProjectPath {get;}
        public SelectedProjectUnavailableException(string path,Exception error)
            :base("The saved project selected for this assembly could not be opened: "+path+". "+error.Message+" No other project was substituted.",error){ProjectPath=path;}
    }
    internal sealed class ExporterSettings
    {
        private readonly string m_Path;
        private Dictionary<string,string> loaded;
        private readonly Dictionary<string,string> changedProjects=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        private string ProjectsPath=>m_Path+".projects.xml";
        public string GameDirectory { get; set; } = "";
        public string ModsDirectory { get; set; } = "";
        public string PythonExecutable { get; set; } = "";
        public string CalibrationPythonExecutable { get; set; } = "";
        public string HarnessProfile { get; set; } = "";
        public string LastCalibrationGeneration { get; set; } = "";
        public string BlenderExecutable { get; set; } = "";
        public string CgalPythonExecutable { get; set; } = "";
        public string FrameSource { get; set; } = "";
        public string FrameOutput { get; set; } = "";
        public string SaveBuildReports { get; set; } = "false";
        public string VerificationMode { get; set; } = "quick";
        public string LastBuildReceipt { get; set; } = "";
        public string LastProjectPath { get; set; } = "";
        public string LoadError { get; private set; }
        public ExporterSettings(string path)
        {
            var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            m_Path = path ?? Path.Combine(local, "beamng.cad", "settings.xml");
            var source = m_Path;
            if (path == null && !File.Exists(source)) source = Path.Combine(local, "TrueMeshExporter", "settings.xml");
            if (File.Exists(source)) try
            {
                var root = XDocument.Load(source).Root;
                if (root == null || (root.Name != "TrueMeshExporterSettings" && root.Name != "BeamNGCadSettings")
                    || !new[] { "1", "2" }.Contains((string)root.Attribute("version")))
                    throw new InvalidDataException("Unsupported settings format.");
                foreach (var p in Values()) p.SetValue(this, (string)root.Element(p.Name) ?? (string)p.GetValue(this));
            }
            catch (Exception e) when (e is IOException || e is System.Xml.XmlException || e is UnauthorizedAccessException)
            { LoadError = "Could not load settings: " + e.Message; }
            if (path == null) PopulateDefaults(local);
            loaded=Values().ToDictionary(p=>p.Name,p=>(string)p.GetValue(this));
        }
        private static System.Reflection.PropertyInfo[] Values() => typeof(ExporterSettings).GetProperties()
            .Where(p => p.PropertyType == typeof(string) && p.Name != nameof(LoadError)).ToArray();
        public ExporterSettings Reload()=>new ExporterSettings(m_Path);
        private static Dictionary<string,string> ReadProjects(XElement root)
        {
            if(root==null||root.Name!="BeamNGCadProjects"||(string)root.Attribute("version")!="1")throw new InvalidDataException("Unsupported saved project selection format.");
            var result=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            foreach(var item in root.Element("SelectedProjects")?.Elements("Project")??Enumerable.Empty<XElement>())
            {
                var document=(string)item.Attribute("document");var path=(string)item.Attribute("path");
                if(string.IsNullOrWhiteSpace(document)||string.IsNullOrWhiteSpace(path))throw new InvalidDataException("Incomplete saved project selection.");
                result[Path.GetFullPath(document)]=path;
            }
            return result;
        }
        private Dictionary<string,string> ReadProjects()=>File.Exists(ProjectsPath)?ReadProjects(XDocument.Load(ProjectsPath).Root):new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        public void SelectProject(VehicleProject project)
        {
            // Only explicit project choices belong here. Saving a build from an
            // older modeless window must not replace the assembly's active choice.
            changedProjects[Path.GetFullPath(project.SourceDocument)]=project.FilePath;
            LastProjectPath=project.FilePath;
        }
        public VehicleProject ProjectForDocument(string document)
        {
            document=Path.GetFullPath(document);
            // Frame/mod windows can outlive a project switch in Components.
            var latest=ReadProjects();
            if(changedProjects.TryGetValue(document,out var path)||latest.TryGetValue(document,out path))
            {
                try
                {
                    var project=VehicleProject.Load(path);
                    if(!ComponentAssignments.SameDocument(project.SourceDocument,document))throw new InvalidDataException("It belongs to a different CAD document.");
                    return project;
                }
                catch(Exception e) when(e is IOException||e is InvalidDataException||e is UnauthorizedAccessException||e is System.Runtime.Serialization.SerializationException||e is ArgumentException)
                {throw new SelectedProjectUnavailableException(path,e);}
            }
            // Migrate the former global selection once for each document. The
            // default adjacent project remains available as an explicit choice.
            var selected=VehicleProject.ForDocument(document,LastProjectPath);
            SelectProject(selected);Save();return selected;
        }
        private void PopulateDefaults(string local)
        {
            if(CalibrationPythonExecutable.Length==0){var known=@"H:\beamng project programs\BeamNG.cad\.venv\Scripts\python.exe";CalibrationPythonExecutable=File.Exists(known)?known:PythonExecutable;}
            if(HarnessProfile.Length==0)HarnessProfile=@"H:\BeamNGCadHarness\drive";
            if (GameDirectory.Length == 0) GameDirectory = new[] { @"D:\SteamLibrary\steamapps\common\BeamNG.drive",
                @"C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive" }
                .FirstOrDefault(p => File.Exists(Path.Combine(p, "BeamNG.drive.exe"))) ?? "";
            var mods = Path.Combine(local, "BeamNG", "BeamNG.drive", "current", "mods");
            if (ModsDirectory.Length == 0 && Directory.Exists(mods)) ModsDirectory = mods;
            if (PythonExecutable.Length == 0) PythonExecutable = FindExecutable(Path.Combine(local, "Python"), "python.exe");
            if (PythonExecutable.Length == 0) PythonExecutable = FindExecutable(Path.Combine(local, "Programs", "Python"), "python.exe");
            if (BlenderExecutable.Length == 0) BlenderExecutable = FindExecutable(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Blender Foundation"), "blender.exe");
            var cgal = Path.Combine(local, "Microsoft", "WindowsApps", "PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0", "python.exe");
            if (CgalPythonExecutable.Length == 0 && File.Exists(cgal)) CgalPythonExecutable = cgal;
            if (FrameSource.Length == 0 && File.Exists(@"H:\beamng project programs\Test Programs\material.json")) FrameSource = @"H:\beamng project programs\Test Programs";
            if (FrameOutput.Length == 0) FrameOutput = Path.Combine(local, "beamng.cad", "builds");
        }
        private static string FindExecutable(string root, string file) => !Directory.Exists(root) ? "" : Directory.GetDirectories(root)
            .OrderByDescending(p => p).Select(p => Path.Combine(p, file)).FirstOrDefault(File.Exists) ?? "";
        public void Save()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(m_Path)));
            // Modeless windows hold independent settings snapshots. Preserve fields
            // changed by another window when this instance did not edit them.
            if(File.Exists(m_Path))
            {
                var latest=XDocument.Load(m_Path).Root;
                foreach(var property in Values())
                    if(loaded.TryGetValue(property.Name,out var previous) && previous==(string)property.GetValue(this) && latest.Element(property.Name)!=null)
                        property.SetValue(this,(string)latest.Element(property.Name));
            }
            // Keep per-document choices separately so an already-running older
            // add-in cannot erase them when saving its legacy settings format.
            if(changedProjects.Count>0)
            {
                var projects=ReadProjects();
                foreach(var choice in changedProjects)projects[choice.Key]=choice.Value;
                var selection=new XElement("BeamNGCadProjects",new XAttribute("version","1"),
                    new XElement("SelectedProjects",projects.OrderBy(p=>p.Key,StringComparer.OrdinalIgnoreCase)
                        .Select(p=>new XElement("Project",new XAttribute("document",p.Key),new XAttribute("path",p.Value)))));
                new XDocument(selection).Save(ProjectsPath+".tmp");
                if(File.Exists(ProjectsPath))File.Replace(ProjectsPath+".tmp",ProjectsPath,ProjectsPath+".bak");
                else File.Move(ProjectsPath+".tmp",ProjectsPath);
            }
            var temporary = m_Path + ".tmp";
            var root = new XElement("BeamNGCadSettings", new XAttribute("version", "2"),
                Values().Select(p => new XElement(p.Name, (string)p.GetValue(this) ?? "")));
            new XDocument(root).Save(temporary);
            if (File.Exists(m_Path)) File.Replace(temporary, m_Path, m_Path + ".bak");
            else File.Move(temporary, m_Path);
            LoadError = null;
            loaded=Values().ToDictionary(p=>p.Name,p=>(string)p.GetValue(this));
            changedProjects.Clear();
        }
    }
}
