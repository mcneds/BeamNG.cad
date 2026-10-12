public static partial class MirrorFrontSuspension {
 static void RearHalfshaftInventory(){
  var donor=app.GetOpenDocumentByName(@"H:\beamng project programs\MOCHI SUS\!DYNAMIC ASSEMBLY.SLDASM") as ModelDoc2;if(donor==null)throw new Exception("Donor is not open");
  var dirty=donor.GetSaveFlag();var stamp=donor.GetUpdateStamp();var rows=new List<object>();
  foreach(Component2 c in ((AssemblyDoc)donor).GetComponents(false) as object[]??new object[0]){var name=c.Name2;var t=c.Transform2==null?null:(double[])c.Transform2.ArrayData;rows.Add(new{name=name,path=c.GetPathName(),transform=t,suppressed=c.IsSuppressed()});if(System.Text.RegularExpressions.Regex.IsMatch(name,"cv|axle|shaft|diff",System.Text.RegularExpressions.RegexOptions.IgnoreCase))Console.WriteLine(name+" position="+(t==null?"none":string.Join(",",t.Skip(9).Take(3))));}
  if(dirty!=donor.GetSaveFlag()||stamp!=donor.GetUpdateStamp())throw new Exception("Donor changed while reading");
  Write("rear-halfshaft-source-inventory.json",new{document=donor.GetPathName(),dirty=dirty,unchanged=true,components=rows});Console.WriteLine("Read "+rows.Count+" donor instances without changes");
 }
}
