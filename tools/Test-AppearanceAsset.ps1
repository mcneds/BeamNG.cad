param([Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
[void][IO.Directory]::CreateDirectory($Destination)
Add-Type -ReferencedAssemblies 'System.Core' -TypeDefinition @'
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections.Generic;
using System.Security.Cryptography;
public static class AppearanceAssetTest {
 public static void Run(string dll,string folder){
  var code=Assembly.LoadFrom(dll);var method=code.GetType("BeamNG.Cad.Preparation.NativeAppearance").GetMethod("Asset",BindingFlags.NonPublic|BindingFlags.Static);
  var source=Path.Combine(folder,"shared-material.p2m");var bytes=System.Text.Encoding.UTF8.GetBytes("owned material snapshot");File.WriteAllBytes(source,bytes);
  using(var native=new FileStream(source,FileMode.Open,FileAccess.ReadWrite,FileShare.Read)){
   bool rejected=false;try{using(var old=File.OpenRead(source)){} }catch(IOException){rejected=true;}
   if(!rejected)throw new Exception("Fixture must reproduce the old sharing conflict");
   var copied=(string)method.Invoke(null,new object[]{source,folder,new List<string>()});
   if(!File.ReadAllBytes(copied).SequenceEqual(bytes))throw new Exception("Appearance bytes changed");
   using(var sha=SHA256.Create())if(!Path.GetFileName(copied).StartsWith(BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant().Substring(0,16)))throw new Exception("Snapshot hash mismatch");
   if(Directory.GetFiles(Path.Combine(folder,"appearances"),"*.tmp").Length!=0)throw new Exception("Temporary appearance snapshot leaked");
  }
  Console.WriteLine("PASS native-style shared material handle, exact bytes, content hash and cleanup");
 }
}
'@
[AppearanceAssetTest]::Run((Join-Path $OutputDirectory 'beamng.cad.dll'),$Destination)
