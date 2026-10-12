using System;
using System.IO;
using System.Linq;
namespace BeamNG.Cad.Preparation
{
    internal static class AxisMapping
    {
        public const string Standard = "X-ZY";
        public const string Convention = "solidworks-y-up-to-beamng-z-up-v1";
        public static readonly string[] Axes={"+X","-X","+Y","-Y","+Z","-Z"};
        public static double[] Axis(string value)
        {
            if(!Axes.Contains(value))throw new InvalidDataException("Select a signed CAD axis.");
            var v=new double[3];v["XYZ".IndexOf(value[1])]=value[0]=='-'?-1:1;return v;
        }
        public static string Canonical(string mapping) => mapping=="XYZ"?"+Z,-Y":mapping=="X-ZY"?"+Y,+Z":mapping=="-ZYX"?"+X,-Y":mapping;
        public static double[][] Matrix(string mapping)
        {
            var axes=Canonical(mapping).Split(',');
            if(axes.Length!=2)throw new InvalidDataException("Choose CAD up and forward axes.");
            var z=Axis(axes[0]);var y=Axis(axes[1]).Select(v=>-v).ToArray();
            if(z.Zip(y,(a,b)=>a*b).Sum()!=0)throw new InvalidDataException("CAD up and forward must use different axes.");
            var x=new[]{y[1]*z[2]-y[2]*z[1],y[2]*z[0]-y[0]*z[2],y[0]*z[1]-y[1]*z[0]};
            return new[]{x,y,z};
        }
        public static double[] ToCad(double[] p,string mapping)
        {var m=Matrix(mapping);return Enumerable.Range(0,3).Select(i=>m[0][i]*p[0]+m[1][i]*p[1]+m[2][i]*p[2]).ToArray();}
    }
}
