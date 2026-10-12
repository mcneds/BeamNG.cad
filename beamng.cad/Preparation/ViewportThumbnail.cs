using System;
using System.IO;
using System.Runtime.InteropServices;
using BeamNG.Cad.FramePipeline;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.Preparation
{
    internal static class ViewportThumbnail
    {
        public static string Capture(ISldWorks application, string profilePath)
        {
            if (application == null)
            {
                try { application = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application"); }
                catch (COMException e) { throw new InvalidOperationException("Open SolidWorks and activate the model view to capture.", e); }
            }
            var model = application.ActiveDoc as ModelDoc2;
            if (model == null || model.ActiveView == null)
                throw new InvalidOperationException("Activate a model view in SolidWorks before capturing a thumbnail.");
            var temporary = Path.Combine(Path.GetTempPath(), "beamng-viewport-" + Guid.NewGuid().ToString("N") + ".bmp");
            try
            {
                model.GraphicsRedraw2();
                // Use the current viewport dimensions so the camera framing and
                // aspect ratio survive normalization to the selector image size.
                if (!model.SaveBMP(temporary, 0, 0) || !File.Exists(temporary))
                    throw new IOException("SolidWorks could not capture the current viewport. Make the model view visible and try again.");
                return ModPackage.ImportImage(temporary, profilePath);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
    }
}
