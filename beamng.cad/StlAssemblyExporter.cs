using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using IOFile = System.IO.File;
using SysEnv = System.Environment;

namespace BeamNG.Cad
{
    internal static class StlAssemblyExporter
    {
        // Bulk graphics capture for diagnostic vehicle intake. Physical moments
        // must come from native CAD, not from this display tessellation.
        internal static List<Preparation.AppearanceRange> ExportDisplayBodyWithAppearance(ISldWorks app,Component2 component,Body2 body,string path,MathTransform transform)
            =>ExportDisplayBodyWithAppearance(app,component,body,path,transform,new Preparation.SolidWorksAppearances.Scene(app.ActiveDoc as ModelDoc2));
        internal static List<Preparation.AppearanceRange> ExportDisplayBodyWithAppearance(ISldWorks app,Component2 component,Body2 body,string path,MathTransform transform,Preparation.SolidWorksAppearances.Scene scene)
        {
            var appearance=new Preparation.SolidWorksAppearances(app,component,body,scene);
            var ranges=new List<Preparation.AppearanceRange>();var math=(MathUtility)app.GetMathUtility();
            Func<double[],double[]> map=p=>{var v=(MathPoint)math.CreatePoint(p);if(transform!=null)v=(MathPoint)v.MultiplyTransform(transform);return (double[])v.ArrayData;};
            var origin=map(new double[3]);var basis=Enumerable.Range(0,3).Select(i=>{var p=new double[3];p[i]=1;var q=map(p);return q.Zip(origin,(a,b)=>a-b).ToArray();}).ToArray();
            using(var stream=IOFile.Create(path))using(var writer=new BinaryWriter(stream)){
                writer.Write(new byte[80]);writer.Write((uint)0);uint count=0;
                foreach(Face2 face in body.GetFaces() as object[]??Array.Empty<object>()){
                    var data=face.GetTessTriangles(true) as float[];
                    if(data==null||data.Length==0||data.Length%9!=0)throw new InvalidOperationException("Display tessellation unavailable for "+body.Name);
                    var color=appearance.Read(face);uint start=count;
                    for(int at=0;at<data.Length;at+=9){var points=new double[3][];
                        for(int v=0;v<3;v++){points[v]=(double[])origin.Clone();for(int i=0;i<3;i++)for(int j=0;j<3;j++)points[v][j]+=data[at+3*v+i]*basis[i][j];}
                        var normal=ComputeNormal(points[0],points[1],points[2]);foreach(var n in normal)writer.Write((float)n);
                        foreach(var p in points)foreach(var n in p)writer.Write((float)n);writer.Write((ushort)0);count++;
                    }
                    var prior=ranges.LastOrDefault();if(prior!=null&&Preparation.SolidWorksAppearances.Same(prior.Appearance,color))prior.TriangleCount+=count-start;
                    else ranges.Add(new Preparation.AppearanceRange{StartTriangle=start,TriangleCount=count-start,Appearance=color});
                }
                stream.Position=80;writer.Write(count);
            }
            return ranges;
        }
        internal static void ExportSelectedBody(ISldWorks app, Body2 body, string path, MathTransform transform)
        {
            ExportSingleBodyToStl_FastTessellation(app, body, path, transform, false);
        }
        internal static List<Preparation.AppearanceRange> ExportSelectedBodyWithAppearance(ISldWorks app,Component2 component,Body2 body,string path,MathTransform transform)
            =>ExportSelectedBodyWithAppearance(app,component,body,path,transform,new Preparation.SolidWorksAppearances.Scene(app.ActiveDoc as ModelDoc2));
        internal static List<Preparation.AppearanceRange> ExportSelectedBodyWithAppearance(ISldWorks app,Component2 component,Body2 body,string path,MathTransform transform,Preparation.SolidWorksAppearances.Scene scene)
        {
            var appearance=new Preparation.SolidWorksAppearances(app,component,body,scene);
            var ranges=new List<Preparation.AppearanceRange>();
            var copy=(Body2)body.Copy();
            // Resolve copied faces in part coordinates before transforming the temporary
            // body. Never assume Copy preserves face enumeration order.
            var sourceFaces=(body.GetFaces() as object[]??Array.Empty<object>()).Cast<Face2>().GroupBy(AppearanceFaceKey).ToDictionary(g=>g.Key,g=>g.ToArray());
            var copiedAppearances=new Dictionary<Face2,Preparation.VisualAppearance>();
            foreach(Face2 face in copy.GetFaces() as object[]??Array.Empty<object>())
            {
                if(!sourceFaces.TryGetValue(AppearanceFaceKey(face),out var matches)||matches.Length!=1)
                    throw new InvalidOperationException("Cannot uniquely map a copied CAD face to its appearance: "+body.Name);
                copiedAppearances.Add(face,appearance.Read(matches[0]));
            }
            if(transform!=null&&!copy.ApplyTransform(transform))throw new InvalidOperationException("Body appearance transform failed.");
            var tess=(Tessellation)copy.GetTessellation(null);
            tess.NeedFaceFacetMap=true;tess.NeedVertexNormal=false;tess.NeedVertexParams=false;tess.ImprovedQuality=true;
            tess.MatchType=(int)swTesselationMatchType_e.swTesselationMatchFacetTopology;
            if(!tess.Tessellate())throw new InvalidOperationException("Appearance mesh tessellation failed.");
            uint start=0;
            WriteBinaryStlFromTessellation(copy,tess,path,(face,end)=>{
                if(end==start)return;
                if(!copiedAppearances.TryGetValue(face,out var value))value=copiedAppearances.Single(p=>app.IsSame(p.Key,face)==(int)swObjectEquality.swObjectSame).Value;
                var previous=ranges.LastOrDefault();
                if(previous!=null&&Preparation.SolidWorksAppearances.Same(previous.Appearance,value))previous.TriangleCount+=end-start;
                else ranges.Add(new Preparation.AppearanceRange {StartTriangle=start,TriangleCount=end-start,Appearance=value});
                start=end;
            });
            return ranges;
        }
        private static string AppearanceFaceKey(Face2 face)
        {
            var points=((double[])face.GetBox()).Concat(new[]{face.GetArea()});
            return ((Surface)face.GetSurface()).Identity()+"|"+face.FaceInSurfaceSense()+"|"+
                string.Join(",",points.Select(v=>v.ToString("G12",System.Globalization.CultureInfo.InvariantCulture)));
        }
        private const int MAX_PARTNAME = 50;
        private const int MAX_CFGNAME = 40;
        private const int MAX_BODYNAME = 60;

        // Leave false unless you absolutely need it (some installs beep-spam / throw a lot)
        private const bool DO_RESOLVE_LIGHTWEIGHT = false;

        // SOLIDWORKS internal length is meters. STL is unitless.
        // 1.0 = meters, 1000.0 = mm, 39.37007874 = inches.
        private const double STL_SCALE = 1.0;

        public static void ExportAll(
            ISldWorks swApp,
            ModelDoc2 asmModel,
            string outRoot,
            bool resumeSkipExisting,
            bool useInverseXform)
        {
            Directory.CreateDirectory(outRoot);
            var logPath = Path.Combine(outRoot, "export_log.txt");

            StreamWriter log = null;

            int visited = 0, exported = 0, failed = 0, skipped = 0, suppressed = 0, hidden = 0, openFail = 0, noBodies = 0, notPart = 0;

            Action<string> Log = s =>
            {
                if (log != null)
                    log.WriteLine(string.Format("{0:yyyy-MM-dd HH:mm:ss} | {1}", DateTime.Now, s));
            };

            string asmTitle = Safe(() => asmModel.GetTitle(), Log, "asmModel.GetTitle()", "(unknown)");

            try
            {
                log = new StreamWriter(logPath, true, Encoding.UTF8);
                log.AutoFlush = true;

                Log("START " + DateTime.Now);
                Log("Doc: " + asmTitle);

                TrySetCommandInProgress(swApp, true, Log);

                var swAsm = asmModel as AssemblyDoc;
                if (swAsm == null)
                {
                    Log("FATAL Active doc is not an AssemblyDoc");
                    return;
                }

                if (DO_RESOLVE_LIGHTWEIGHT)
                    TryResolveLightweightOnce(swAsm, asmModel, Log);
                else
                    Log("INFO Resolve lightweight skipped (DO_RESOLVE_LIGHTWEIGHT=false)");

                object rawComps = Safe(() => swAsm.GetComponents(false), Log, "swAsm.GetComponents(false)", null);
                var comps = AsComArray<Component2>(rawComps).ToList();
                Log("Components returned: " + comps.Count);

                foreach (var comp in comps)
                {
                    visited++;

                    if (comp == null) { failed++; continue; }

                    bool isSupp = Safe(() => comp.IsSuppressed(), Log, "comp.IsSuppressed()", false);
                    if (isSupp) { suppressed++; continue; }

                    // ===== SKIP HIDDEN / NOT VISIBLE COMPONENTS =====
                    if (IsComponentHiddenInAssembly(comp, Log))
                    {
                        hidden++;
                        Log("HIDDEN_SKIP " + SafeName(comp));
                        continue;
                    }
                    // ===============================================

                    try
                    {
                        string path = Safe(() => comp.GetPathName(), Log, "comp.GetPathName()", "") ?? "";
                        string cfg = "";
                        try { cfg = comp.ReferencedConfiguration ?? ""; } catch { cfg = ""; }

                        var compModel = Safe(() => comp.GetModelDoc2() as ModelDoc2, Log, "comp.GetModelDoc2()", null);

                        if (compModel == null)
                        {
                            if (string.IsNullOrWhiteSpace(path))
                            {
                                openFail++;
                                Log("OPEN_FAIL " + SafeName(comp) + " | (virtual/no path) and GetModelDoc2 returned null");
                                continue;
                            }

                            int errs = 0, warns = 0;
                            int docType = GuessDocTypeFromPath(path);

                            compModel = Safe(() =>
                                swApp.OpenDoc6(
                                    path,
                                    docType,
                                    (int)(swOpenDocOptions_e.swOpenDocOptions_Silent | swOpenDocOptions_e.swOpenDocOptions_ReadOnly),
                                    "",
                                    ref errs,
                                    ref warns
                                ) as ModelDoc2,
                                Log,
                                "swApp.OpenDoc6(" + path + ")",
                                null);

                            if (compModel == null)
                            {
                                openFail++;
                                Log("OPEN_FAIL " + SafeName(comp) + " | path=" + path + " | errs=" + errs + " warns=" + warns);
                                continue;
                            }
                        }

                        int type = Safe(() => compModel.GetType(), Log, "compModel.GetType()", -1);
                        if (type != (int)swDocumentTypes_e.swDocPART)
                        {
                            notPart++;
                            continue;
                        }

                        if (!string.IsNullOrWhiteSpace(cfg))
                        {
                            try { compModel.ShowConfiguration2(cfg); }
                            catch (Exception e) { Log("WARN ShowConfiguration2 failed for " + SafeName(comp) + " : " + e.Message); }
                        }

                        var partDoc = compModel as PartDoc;
                        if (partDoc == null)
                        {
                            failed++;
                            Log("PART_FAIL " + SafeName(comp) + " | ModelDoc2 is swDocPART but PartDoc cast failed");
                            continue;
                        }

                        // Macro-style transform (this is what you said was “the working macro”)
                        MathTransform xform = GetTransform_MacroStyle(comp);

                        string partBase = Path.GetFileNameWithoutExtension(path);
                        if (string.IsNullOrWhiteSpace(partBase)) partBase = SafeName(comp);
                        partBase = Trunc(Sanitize(partBase), MAX_PARTNAME);

                        string cfgSafe = Trunc(Sanitize(string.IsNullOrWhiteSpace(cfg) ? "Default" : cfg), MAX_CFGNAME);

                        string instKey = SafeName(comp) + "|" + path + "|" + cfg;
                        string instHash = SmallHash8(instKey);

                        string compFolder = Path.Combine(outRoot, partBase + "__" + cfgSafe + "__" + instHash);
                        Directory.CreateDirectory(compFolder);

                        Log("PART_COMP " + SafeName(comp) + " | cfg=" + cfg + " | out=" + compFolder);

                        ExportBodiesOfPart_InAsmSpace(
                            swApp,
                            partDoc,
                            compFolder,
                            partBase,
                            cfgSafe,
                            instHash,
                            xform,
                            resumeSkipExisting,
                            useInverseXform,
                            Log,
                            ref exported,
                            ref failed,
                            ref skipped,
                            ref noBodies);
                    }
                    catch (COMException ex)
                    {
                        failed++;
                        Log("COMP_COM_FAIL " + SafeName(comp) + " | 0x" + ex.ErrorCode.ToString("X8") + " | " + ex.Message);
                    }
                    catch (Exception ex)
                    {
                        failed++;
                        Log("COMP_FAIL " + SafeName(comp) + " | " + ex.GetType().Name + " | " + ex.Message);
                    }
                }

                Log("DONE " + DateTime.Now +
                    " | Visited=" + visited +
                    " Suppressed=" + suppressed +
                    " Hidden=" + hidden +
                    " OpenFail=" + openFail +
                    " NoBodies=" + noBodies +
                    " NotPart=" + notPart +
                    " | Exported=" + exported +
                    " Failed=" + failed +
                    " Skipped=" + skipped);

                IOFile.WriteAllText(
                    Path.Combine(outRoot, "_EXPORT_DONE.txt"),
                    "DONE " + DateTime.Now + SysEnv.NewLine +
                    "Visited=" + visited + SysEnv.NewLine +
                    "Suppressed=" + suppressed + SysEnv.NewLine +
                    "Hidden=" + hidden + SysEnv.NewLine +
                    "OpenFail=" + openFail + SysEnv.NewLine +
                    "NoBodies=" + noBodies + SysEnv.NewLine +
                    "NotPart=" + notPart + SysEnv.NewLine +
                    "Exported=" + exported + SysEnv.NewLine +
                    "Failed=" + failed + SysEnv.NewLine +
                    "Skipped=" + skipped
                );
            }
            finally
            {
                TrySetCommandInProgress(swApp, false, Log);
                if (log != null) log.Dispose();
            }
        }

        private static bool IsComponentHiddenInAssembly(Component2 comp, Action<string> Log)
        {
            // Visible is usually 0=hidden, 1=visible (enum-ish). This is fast and catches the common case.
            int vis = Safe(() => comp.Visible, Log, "comp.Visible", 1);
            if (vis == 0) return true;

            // IsHidden can reflect hide via display states / parent hidden, depending on flags.
            bool hTrue = Safe(() => comp.IsHidden(true), Log, "comp.IsHidden(true)", false);
            if (hTrue) return true;

            bool hFalse = Safe(() => comp.IsHidden(false), Log, "comp.IsHidden(false)", false);
            return hFalse;
        }

        private static void ExportBodiesOfPart_InAsmSpace(
            ISldWorks swApp,
            PartDoc part,
            string outFolder,
            string partBase,
            string cfgSafe,
            string instHash,
            MathTransform xform,
            bool resumeSkipExisting,
            bool useInverseXform,
            Action<string> Log,
            ref int exported,
            ref int failed,
            ref int skipped,
            ref int noBodies)
        {
            var bodies = new List<Body2>();

            object solid = Safe(() => part.GetBodies2((int)swBodyType_e.swSolidBody, false), Log, "part.GetBodies2(Solid)", null);
            object sheet = Safe(() => part.GetBodies2((int)swBodyType_e.swSheetBody, false), Log, "part.GetBodies2(Sheet)", null);

            bodies.AddRange(AsComArray<Body2>(solid));
            bodies.AddRange(AsComArray<Body2>(sheet));

            string title = Safe(() => ((ModelDoc2)part).GetTitle(), Log, "part.GetTitle()", "(part)");

            if (bodies.Count == 0)
            {
                noBodies++;
                Log("NO_BODIES " + title);
                return;
            }

            Log("PART " + title + " | bodies=" + bodies.Count);

            for (int i = 0; i < bodies.Count; i++)
            {
                Body2 body = bodies[i];
                if (body == null) { failed++; continue; }

                string bodyName = "";
                try { bodyName = body.Name; } catch { bodyName = ""; }
                if (string.IsNullOrWhiteSpace(bodyName)) bodyName = "Body";

                string bodySafe = Trunc(Sanitize(bodyName), MAX_BODYNAME);

                string outPath = Path.Combine(
                    outFolder,
                    partBase + "__" + cfgSafe + "__" + instHash + "__B" + (i + 1).ToString("00000") + "__" + bodySafe + ".stl"
                );

                if (resumeSkipExisting && IOFile.Exists(outPath))
                {
                    skipped++;
                    Log("SKIP " + outPath);
                    continue;
                }

                try
                {
                    Log("START " + outPath);
                    ExportSingleBodyToStl_FastTessellation(swApp, body, outPath, xform, useInverseXform);
                    exported++;
                    Log("OK " + outPath + " | size=" + new FileInfo(outPath).Length);
                }
                catch (COMException ex)
                {
                    failed++;
                    Log("BODY_COM_FAIL idx=" + (i + 1) + " | 0x" + ex.ErrorCode.ToString("X8") + " | " + ex.Message);
                }
                catch (Exception ex)
                {
                    failed++;
                    Log("BODY_FAIL idx=" + (i + 1) + " | " + ex.GetType().Name + " | " + ex.Message);
                }
            }
        }

        // =========================
        // FAST EXPORT (NO TEMP DOCS)
        // =========================
        private static void ExportSingleBodyToStl_FastTessellation(
            ISldWorks swApp,
            Body2 swBody,
            string outStlPath,
            MathTransform xform,
            bool useInverseXform)
        {
            Body2 bodyCopy = swBody.Copy() as Body2;
            if (bodyCopy == null) throw new Exception("Body copy failed.");

            if (xform != null)
            {
                MathTransform tUse = xform;
                if (useInverseXform)
                {
                    try { tUse = (MathTransform)tUse.Inverse(); } catch { /* ignore */ }
                }

                bodyCopy.ApplyTransform(tUse);
            }

            Tessellation tess = bodyCopy.GetTessellation(null) as Tessellation;
            if (tess == null) throw new Exception("GetTessellation returned null.");

            tess.NeedFaceFacetMap = true;
            tess.NeedVertexNormal = false;
            tess.NeedVertexParams = false;
            tess.ImprovedQuality = true;
            tess.MatchType = (int)swTesselationMatchType_e.swTesselationMatchFacetTopology;

            if (!tess.Tessellate())
                throw new Exception("Tessellate() failed.");

            WriteBinaryStlFromTessellation(bodyCopy, tess, outStlPath);
        }

        private static void WriteBinaryStlFromTessellation(Body2 body, Tessellation tess, string outStlPath)
            =>WriteBinaryStlFromTessellation(body,tess,outStlPath,null);
        private static void WriteBinaryStlFromTessellation(Body2 body,Tessellation tess,string outStlPath,Action<Face2,uint> faceCompleted)
        {
            using (var fs = new FileStream(outStlPath, FileMode.Create, FileAccess.Write, FileShare.Read))
            using (var bw = new BinaryWriter(fs))
            {
                var header = new byte[80];
                var headerText = Encoding.ASCII.GetBytes("TrueMeshExporter tessellation");
                Array.Copy(headerText, header, Math.Min(headerText.Length, header.Length));
                bw.Write(header);

                long triCountPos = fs.Position;
                bw.Write((uint)0);

                uint triCountWritten = 0;
                var seenFacets = new HashSet<int>();

                Face2 face = body.GetFirstFace() as Face2;
                while (face != null)
                {
                    int[] facetIds = ToIntArray(tess.GetFaceFacets(face));
                    if (facetIds != null)
                    {
                        for (int fi = 0; fi < facetIds.Length; fi++)
                        {
                            int facetId = facetIds[fi];
                            if (!seenFacets.Add(facetId)) continue;

                            int[] finIds = ToIntArray(tess.GetFacetFins(facetId));
                            if (finIds == null || finIds.Length < 3) continue;

                            var edges = new List<Tuple<int, int>>(3);
                            for (int i = 0; i < 3; i++)
                            {
                                int[] vv = ToIntArray(tess.GetFinVertices(finIds[i]));
                                if (vv == null || vv.Length < 2) { edges.Clear(); break; }
                                edges.Add(Tuple.Create(vv[0], vv[1]));
                            }
                            if (edges.Count != 3) continue;

                            var uniq = edges.SelectMany(e => new[] { e.Item1, e.Item2 }).Distinct().ToArray();
                            if (uniq.Length != 3) continue;

                            int v0 = uniq[0];
                            int v1 = FindConnected(v0, uniq[1], uniq[2], edges);
                            int v2 = uniq.First(v => v != v0 && v != v1);

                            double[] p0 = ToDouble3(tess.GetVertexPoint(v0));
                            double[] p1 = ToDouble3(tess.GetVertexPoint(v1));
                            double[] p2 = ToDouble3(tess.GetVertexPoint(v2));
                            if (p0 == null || p1 == null || p2 == null) continue;

                            p0[0] *= STL_SCALE; p0[1] *= STL_SCALE; p0[2] *= STL_SCALE;
                            p1[0] *= STL_SCALE; p1[1] *= STL_SCALE; p1[2] *= STL_SCALE;
                            p2[0] *= STL_SCALE; p2[1] *= STL_SCALE; p2[2] *= STL_SCALE;

                            var n = ComputeNormal(p0, p1, p2);

                            bw.Write((float)n[0]); bw.Write((float)n[1]); bw.Write((float)n[2]);

                            bw.Write((float)p0[0]); bw.Write((float)p0[1]); bw.Write((float)p0[2]);
                            bw.Write((float)p1[0]); bw.Write((float)p1[1]); bw.Write((float)p1[2]);
                            bw.Write((float)p2[0]); bw.Write((float)p2[1]); bw.Write((float)p2[2]);

                            bw.Write((ushort)0);
                            triCountWritten++;
                        }
                    }

                    faceCompleted?.Invoke(face,triCountWritten);
                    face = face.GetNextFace() as Face2;
                }

                long endPos = fs.Position;
                fs.Position = triCountPos;
                bw.Write(triCountWritten);
                fs.Position = endPos;
            }
        }

        private static int FindConnected(int start, int a, int b, List<Tuple<int, int>> edges)
        {
            bool connA = edges.Any(e => (e.Item1 == start && e.Item2 == a) || (e.Item1 == a && e.Item2 == start));
            return connA ? a : b;
        }

        private static double[] ComputeNormal(double[] p0, double[] p1, double[] p2)
        {
            double ux = p1[0] - p0[0], uy = p1[1] - p0[1], uz = p1[2] - p0[2];
            double vx = p2[0] - p0[0], vy = p2[1] - p0[1], vz = p2[2] - p0[2];

            double nx = uy * vz - uz * vy;
            double ny = uz * vx - ux * vz;
            double nz = ux * vy - uy * vx;

            double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);
            if (len < 1e-12) return new double[] { 0, 0, 0 };

            return new double[] { nx / len, ny / len, nz / len };
        }

        private static int[] ToIntArray(object v)
        {
            if (v == null) return null;
            var ii = v as int[];
            if (ii != null) return ii;

            var a = v as Array;
            if (a != null && a.Length > 0)
            {
                var outArr = new int[a.Length];
                for (int i = 0; i < a.Length; i++) outArr[i] = Convert.ToInt32(a.GetValue(i));
                return outArr;
            }
            return null;
        }

        private static double[] ToDouble3(object v)
        {
            if (v == null) return null;
            var dd = v as double[];
            if (dd != null && dd.Length >= 3) return new[] { dd[0], dd[1], dd[2] };

            var a = v as Array;
            if (a != null && a.Length >= 3)
            {
                return new[]
                {
                    Convert.ToDouble(a.GetValue(0)),
                    Convert.ToDouble(a.GetValue(1)),
                    Convert.ToDouble(a.GetValue(2))
                };
            }
            return null;
        }

        // Macro-style: Transform2 first, then totals only if Transform2 is null
        private static MathTransform GetTransform_MacroStyle(Component2 comp)
        {
            try
            {
                var t = comp.Transform2 as MathTransform;
                if (t != null) return t;
            }
            catch { }

            try
            {
                var t = comp.GetTotalTransform(true) as MathTransform;
                if (t != null) return t;
            }
            catch { }

            try
            {
                return comp.GetTotalTransform(false) as MathTransform;
            }
            catch { }

            return null;
        }

        private static void TryResolveLightweightOnce(AssemblyDoc swAsm, ModelDoc2 asmModel, Action<string> Log)
        {
            try
            {
                swAsm.ResolveAllLightWeightComponents(true);
                try { asmModel.ForceRebuild3(false); } catch { }
                Log("Resolved lightweight (ResolveAllLightWeightComponents)");
            }
            catch (Exception ex)
            {
                Log("INFO Resolve lightweight failed | " + ex.GetType().Name + " | " + ex.Message);
            }
        }

        private static void TrySetCommandInProgress(ISldWorks swApp, bool value, Action<string> Log)
        {
            try { swApp.CommandInProgress = value; }
            catch (Exception ex) { Log("INFO CommandInProgress set failed | " + ex.GetType().Name + " | " + ex.Message); }
        }

        private static int GuessDocTypeFromPath(string fullPath)
        {
            string ext = (Path.GetExtension(fullPath) ?? "").ToLowerInvariant();
            return ext == ".sldasm"
                ? (int)swDocumentTypes_e.swDocASSEMBLY
                : (int)swDocumentTypes_e.swDocPART;
        }

        private static IEnumerable<T> AsComArray<T>(object comArray) where T : class
        {
            var arr = comArray as Array;
            if (arr == null) yield break;

            foreach (var o in arr)
            {
                var t = o as T;
                if (t != null) yield return t;
            }
        }

        private static string Sanitize(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return "Unnamed";
            char[] bad = { '\\', '/', ':', '*', '?', '"', '<', '>', '|' };
            foreach (var ch in bad) s = s.Replace(ch, '_');
            return s.Trim();
        }

        private static string Trunc(string s, int maxLen)
        {
            if (string.IsNullOrEmpty(s)) return "Unnamed";
            return s.Length <= maxLen ? s : s.Substring(0, maxLen);
        }

        private static string SmallHash8(string s)
        {
            using (var md5 = MD5.Create())
            {
                var bytes = md5.ComputeHash(Encoding.UTF8.GetBytes(s ?? ""));
                return BitConverter.ToString(bytes, 0, 4).Replace("-", "");
            }
        }

        private static string SafeName(Component2 c)
        {
            try
            {
                var n = c.Name2;
                if (!string.IsNullOrWhiteSpace(n)) return n;
            }
            catch { }
            return "(component)";
        }

        private static T Safe<T>(Func<T> func, Action<string> Log, string where, T fallback)
        {
            try { return func(); }
            catch (COMException ex)
            {
                Log("COM_FAIL " + where + " | 0x" + ex.ErrorCode.ToString("X8") + " | " + ex.Message);
                return fallback;
            }
            catch (Exception ex)
            {
                Log("FAIL " + where + " | " + ex.GetType().Name + " | " + ex.Message);
                return fallback;
            }
        }
    }
}
