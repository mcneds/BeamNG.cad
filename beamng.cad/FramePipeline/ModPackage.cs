using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.FramePipeline
{
    [DataContract] internal sealed class ModProfile
    {
        [DataMember] public string Name="Frame";
        [DataMember] public string Brand="Mochi";
        [DataMember] public string Author="ak1di";
        [DataMember] public string Description="Generated static frame from CAD.";
        [DataMember] public string Configuration="CAD frame";
        [DataMember] public string PreviewImage="";
        public static string DefaultPath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"beamng.cad","mod-profile.json");
        public static ModProfile Load(string path) => File.Exists(path)?JsonFile.Read<ModProfile>(path):new ModProfile();
        public void Save(string path)
        {
            if(string.IsNullOrWhiteSpace(Name)||string.IsNullOrWhiteSpace(Configuration))throw new InvalidDataException("Enter a vehicle name and configuration name.");
            if(!string.IsNullOrEmpty(PreviewImage)&&!File.Exists(PreviewImage))throw new FileNotFoundException("Choose an existing preview image.",PreviewImage);
            JsonFile.Write(path,this);
        }
    }
    [DataContract] internal sealed class ModBuildRecord
    {
        [DataMember] public string format=null;
        [DataMember] public int version=0;
        [DataMember] public ProjectIdentity identity=null;
        [DataMember] public string status=null;
        [DataMember] public string zip_file=null;
        [DataMember] public string zip_sha256=null;
        [DataMember] public string parent_receipt=null;
        [DataMember] public string generation_status=null;
        [DataMember] public string recording_status=null;
        [DataMember] public string qualification_status=null;
        [DataMember] public ModCalibrationRecord calibration=null;
    }
    [DataContract] internal sealed class ModCalibrationRecord
    {
        [DataMember(Name="case")] public string MaterialCase=null;
        [DataMember] public string generation=null;
    }
    [DataContract] internal sealed class ModSelectorInfo
    {
        [DataMember] public string Name=null;
        [DataMember] public string Brand=null;
    }
    internal static class ModPackage
    {
        public static string Model(ModBuildRecord record)=>record.identity?.Namespace??"mochi";
        public static string ZipName(ModBuildRecord record)=>record.identity==null?"ak1di_mochi.zip":record.identity.Namespace+".zip";
        public static string ArchivePath(string receipt)
        {
            if(!File.Exists(receipt))throw new FileNotFoundException("Package the mod first, or choose an existing build receipt.",receipt);
            var record=JsonFile.Read<ModBuildRecord>(receipt);record.identity?.Validate();
            if(record.format!="truemesh-static-frame-build" || (record.version!=1 && record.version!=2) || record.status!="succeeded" || record.zip_file!="work/dist/"+ZipName(record))
                throw new InvalidDataException("Choose a successful, supported build receipt.");
            var archive=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(receipt)),"work","dist",ZipName(record));
            if(!File.Exists(archive)||Hash(archive)!=record.zip_sha256)throw new InvalidDataException("Selected build ZIP is missing or has changed since generation.");
            return archive;
        }
        public static string Hash(string file)
        {using(var stream=File.OpenRead(file))using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();}
        public static string Describe(string receipt,string mods)
        {
            if(!File.Exists(receipt))return "No completed build selected. Generate a mod or choose a build receipt.";
            var record=JsonFile.Read<ModBuildRecord>(receipt);
            var archive=ArchivePath(receipt);
            var prefix="vehicles/"+Model(record)+"/";
            string title;bool image;
            using(var zip=ZipFile.OpenRead(archive))
            {
                using(var stream=zip.GetEntry(prefix+"info.json").Open())
                {
                    var info=(ModSelectorInfo)new System.Runtime.Serialization.Json.DataContractJsonSerializer(typeof(ModSelectorInfo)).ReadObject(stream);
                    title=((info.Brand??"")+" "+info.Name).Trim();
                }
                image=zip.GetEntry(prefix+"default.jpg")!=null;
            }
            var installed=Path.Combine(mods??"",ZipName(record));
            var state=!File.Exists(installed)?"Not installed in the configured mods folder":Hash(installed)==record.zip_sha256?"Installed ZIP matches this build":"A different build is installed";
            var qualification=record.qualification_status==null?"Legacy build: no CAD calibration":
                record.calibration?.MaterialCase+" | Generation: "+record.generation_status+" | Recording: "+record.recording_status+" | Qualification: "+record.qualification_status;
            return "BeamNG vehicle: "+title+" | "+(image?"Preview included":"Missing preview")+Environment.NewLine+"Package: "+ZipName(record)+Environment.NewLine+qualification+Environment.NewLine+state+Environment.NewLine+installed;
        }
        public static string CalibrationReport(string receipt)
        {
            var record=JsonFile.Read<ModBuildRecord>(receipt);
            if(record.calibration==null)throw new InvalidOperationException("This legacy build has no CAD calibration report.");
            var path=Path.Combine(record.calibration.generation,"study","index.html");
            if(!File.Exists(path))path=Path.Combine(record.calibration.generation,"study","build-result.json");
            if(!File.Exists(path))throw new FileNotFoundException("The generation report is unavailable; calibration provenance remains beside the build receipt.",path);
            return path;
        }
        public static Task<string> CustomizeAsync(string python,string receipt,string profile,IProgress<string> progress,CancellationToken token)
            =>CustomizeForProjectAsync(python,receipt,profile,progress,token,null,null);
        public static Task<string> CustomizeForProjectAsync(string python,string receipt,string profile,IProgress<string> progress,CancellationToken token,string outputRoot,string project)
        {
            ArchivePath(receipt);
            var output=Path.Combine(outputRoot??Path.Combine(Path.GetDirectoryName(Path.GetFullPath(receipt)),".."),"mod-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,8));
            output=Path.GetFullPath(output);
            return Task.Run(()=>
            {
                if(!File.Exists(python))throw new FileNotFoundException("Configure Python in Settings.",python);
                var script=Path.Combine(Path.GetDirectoryName(typeof(ModPackage).Assembly.Location),"FramePipeline","build_static_frame.py");
                var start=new ProcessStartInfo(python,"-X utf8 -E -s -u "+StaticFrameBuilder.Quote(script)+" --customize "+StaticFrameBuilder.Quote(receipt)+" --profile "+StaticFrameBuilder.Quote(profile)+" --output "+StaticFrameBuilder.Quote(output)+(project==null?"":" --project "+StaticFrameBuilder.Quote(project)))
                {UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
                BuildStorage.ConfigureScratch(start,Path.GetDirectoryName(output));
                using(var process=new Process {StartInfo=start})
                {
                    process.OutputDataReceived+=(s,e)=> {if(e.Data!=null)progress?.Report(e.Data);};
                    process.ErrorDataReceived+=(s,e)=> {if(e.Data!=null)progress?.Report(e.Data);};
                    token.ThrowIfCancellationRequested();process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();
                    using(token.Register(()=> {try{if(!process.HasExited)process.Kill();}catch(InvalidOperationException){}}))process.WaitForExit();
                    token.ThrowIfCancellationRequested();if(process.ExitCode!=0)throw new InvalidOperationException("Could not update the mod package. See the log.");
                }
                return Path.Combine(output,"static_frame_build.json");
            },token);
        }
        public static string ImportImage(string source,string profilePath)
        {
            using(var original=Image.FromFile(source))using(var target=new Bitmap(1024,576))using(var graphics=Graphics.FromImage(target))
            {
                graphics.Clear(Color.FromArgb(35,40,46));graphics.InterpolationMode=InterpolationMode.HighQualityBicubic;
                var scale=Math.Min(1024d/original.Width,576d/original.Height);var w=(int)(original.Width*scale);var h=(int)(original.Height*scale);
                graphics.DrawImage(original,(1024-w)/2,(576-h)/2,w,h);return SaveImage(target,profilePath);
            }
        }
        private static string SaveImage(Bitmap image,string profilePath)
        {
            var assets=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(profilePath)),"mod-images");Directory.CreateDirectory(assets);
            var path=Path.Combine(assets,Guid.NewGuid().ToString("N")+".jpg");image.Save(path,ImageFormat.Jpeg);return path;
        }
        public static string HullImage(string receipt,string profilePath)
        {
            string hull=null;var current=receipt;
            for(var i=0;i<32 && File.Exists(current);i++)
            {
                var candidate=Path.Combine(Path.GetDirectoryName(current),"work","mochi_hull.off");
                if(File.Exists(candidate)){hull=candidate;break;}
                current=JsonFile.Read<ModBuildRecord>(current).parent_receipt;
            }
            if(hull==null)throw new FileNotFoundException("The source hull for this build is unavailable. Choose an image instead.");
            var lines=File.ReadAllLines(hull).Select(l=>l.Split('#')[0].Trim()).Where(l=>l.Length>0).ToArray();
            if(lines[0]!="OFF")throw new InvalidDataException("Unsupported hull preview.");
            Func<string,string[]> split=s=>s.Split((char[])null,StringSplitOptions.RemoveEmptyEntries);
            var counts=split(lines[1]).Select(int.Parse).ToArray();
            var points=lines.Skip(2).Take(counts[0]).Select(l=>split(l).Select(v=>double.Parse(v,CultureInfo.InvariantCulture)).ToArray())
                .Select(p=>new[]{p[0]-.65*p[2],p[1]+.25*p[2]+.15*p[0]}).ToArray();
            var minX=points.Min(p=>p[0]);var maxX=points.Max(p=>p[0]);var minY=points.Min(p=>p[1]);var maxY=points.Max(p=>p[1]);
            var scale=Math.Min(900/Math.Max(maxX-minX,.000001),460/Math.Max(maxY-minY,.000001));
            Func<int,PointF> project=i=>new PointF((float)(512+(points[i][0]-(minX+maxX)/2)*scale),(float)(278-(points[i][1]-(minY+maxY)/2)*scale));
            using(var image=new Bitmap(1024,576))using(var g=Graphics.FromImage(image))using(var pen=new Pen(Color.FromArgb(245,165,50),2))using(var font=new Font("Segoe UI",15))
            {
                g.Clear(Color.FromArgb(35,40,46));g.SmoothingMode=SmoothingMode.AntiAlias;
                foreach(var line in lines.Skip(2+counts[0]).Take(counts[1]))
                {var face=split(line).Select(int.Parse).ToArray();for(var i=1;i<=face[0];i++)g.DrawLine(pen,project(face[i]),project(face[i==face[0]?1:i+1]));}
                g.DrawString("CAD frame hull",font,Brushes.White,20,535);return SaveImage(image,profilePath);
            }
        }
    }
}
