using System;
using System.Drawing;
using System.IO;

namespace BeamNG.Cad.Properties
{
    internal static class CommandIcons
    {
        private static readonly Lazy<Bitmap> ExportIcon = new Lazy<Bitmap>(() => Load("box-icon.png"));
        private static readonly Lazy<Bitmap> AboutIcon = new Lazy<Bitmap>(() => Load("about-icon.png"));

        public static Bitmap Export => ExportIcon.Value;
        public static Bitmap About => AboutIcon.Value;

        private static Bitmap Load(string name)
        {
            var resourceName = "BeamNG.Cad.Resources." + name;
            using (var stream = typeof(CommandIcons).Assembly.GetManifestResourceStream(resourceName))
            {
                if (stream == null)
                    throw new InvalidOperationException("Missing command icon: " + resourceName);

                // Detach the bitmap from the stream before disposing the stream.
                using (var image = new Bitmap(stream))
                    return new Bitmap(image);
            }
        }
    }
}
