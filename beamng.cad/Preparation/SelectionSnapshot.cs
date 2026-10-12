using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;

namespace BeamNG.Cad.Preparation
{
    // Loading a lightweight component clears SolidWorks' current selection.
    // Keep persistent identities before loading, then reacquire the exact items.
    internal sealed class SelectionSnapshot : IDisposable
    {
        private readonly ModelDoc2 document;
        private readonly List<Tuple<byte[],int>> items=new List<Tuple<byte[],int>>();
        public SelectionSnapshot(ModelDoc2 document)
        {
            this.document=document;
            var manager=(SelectionMgr)document.SelectionManager;
            for(var i=1;i<=manager.GetSelectedObjectCount2(-1);i++)
            {
                var reference=document.Extension.GetPersistReference3(manager.GetSelectedObject6(i,-1)) as byte[];
                if(reference==null || reference.Length==0)throw new InvalidOperationException("Cannot preserve the current selection while loading component data. Resolve the component and reselect its geometry.");
                items.Add(Tuple.Create(reference,manager.GetSelectedObjectMark(i)));
            }
        }
        public void Dispose()
        {
            var manager=(SelectionMgr)document.SelectionManager;
            // Most actions need no selection writes at all.
            if(manager.GetSelectedObjectCount2(-1)==items.Count && items.Select((item,index)=>
                item.Item2==manager.GetSelectedObjectMark(index+1) &&
                item.Item1.SequenceEqual(document.Extension.GetPersistReference3(manager.GetSelectedObject6(index+1,-1)) as byte[] ?? new byte[0])).All(same=>same))return;
            var resolved=new List<object>();
            foreach(var item in items)
            {
                int error;
                var value=document.Extension.GetObjectByPersistReference3(item.Item1,out error);
                if(value==null || error!=0)throw new InvalidOperationException("An original selection is unavailable after loading its component. Reselect the affected geometry.");
                resolved.Add(value);
            }
            document.ClearSelection2(true);
            for(var i=0;i<items.Count;i++)
            {
                var data=manager.CreateSelectData();data.Mark=items[i].Item2;
                var obj=resolved[i];
                var selected=obj is Body2 body ? body.Select2(true,data)
                    : obj is Component2 component ? component.Select4(true,data,false)
                    : obj is SketchPoint point ? point.Select4(true,data)
                    : obj is Entity entity ? entity.Select4(true,data)
                    : obj is Feature feature ? feature.Select2(true,data.Mark)
                    : manager.AddSelectionListObject(obj,data);
                if(!selected)throw new InvalidOperationException("SolidWorks could not restore an original selection after loading its component. Reselect the affected geometry.");
            }
        }
    }
}
