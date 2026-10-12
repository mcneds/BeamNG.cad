using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace BeamNG.Cad.Preparation
{
    internal sealed partial class AssociationAssembly
    {
        internal static bool KeepsReplacement(Group group)=>group!=null&&
            (group.SourceOverride||(group.Members?.Any(KeepsReplacement)??false));

        internal static HashSet<string> ReplacementIds(Receipt receipt)=>
            new HashSet<string>(receipt.Groups.Where(KeepsReplacement).Select(g=>g.Id));

        internal static HashSet<string> RemovedSourceIds(Receipt receipt,IEnumerable<string> sourceIds)
        {
            var current=new HashSet<string>(sourceIds);var retained=ReplacementIds(receipt);
            return new HashSet<string>((receipt.SourceComponents?.Select(c=>c.Id)??receipt.Groups.Select(g=>g.Id))
                .Where(id=>!current.Contains(id)&&!retained.Contains(id)));
        }

        internal static Receipt AppearanceOrigin(Receipt receipt,Group group)
        {
            if(group.SourceOverride&&string.IsNullOrEmpty(group.SourceDocument))
                throw new InvalidDataException(group.Name+": replacement appearance source is missing.");
            return string.IsNullOrEmpty(group.SourceDocument)?receipt:new Receipt {
                SourceDocument=group.SourceDocument,SourceProject=group.SourceProject,
                Configuration=group.SourceConfiguration??receipt.Configuration};
        }

        private static void RetainReplacement(UpdateGroup item,VehicleProject current)
        {
            var target=current.Components.SingleOrDefault(c=>c.Id==item.Source.Id)
                ??throw new InvalidDataException(item.Source.Name+": reviewed replacement is missing from the companion project. Restore it before updating.");
            item.Source=CopyDefinition(target);
            item.Before=CopyDefinition(target);
            item.Scopes=item.Old.Scopes??new Dictionary<string,string[]>();
            item.Replace=item.Rebind=false;
        }
    }
}
