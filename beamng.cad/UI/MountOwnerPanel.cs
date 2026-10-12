using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Forms;
using BeamNG.Cad.Preparation;

namespace BeamNG.Cad.UI
{
    internal sealed class MountOwnerPanel : UserControl
    {
        private readonly ComboBox owner=new ComboBox {Name="MountOwner",Width=410,DropDownStyle=ComboBoxStyle.DropDownList,DisplayMember="Label",AutoCompleteSource=AutoCompleteSource.ListItems,AutoCompleteMode=AutoCompleteMode.SuggestAppend};
        private bool updating;
        public ComponentDefinition SelectedOwner=>owner.SelectedItem as ComponentDefinition;
        public event Action<ComponentDefinition> OwnerChanged;
        public MountOwnerPanel()
        {
            Name="MountOwnerPanel";AutoSize=true;AutoSizeMode=AutoSizeMode.GrowAndShrink;
            var body=new FlowLayoutPanel {AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,WrapContents=false};
            body.Controls.Add(new Label {AutoSize=true,Text="Component",Margin=new Padding(3,7,3,3)});body.Controls.Add(owner);Controls.Add(body);
            owner.SelectedIndexChanged+=(s,e)=>{if(!updating)OwnerChanged?.Invoke(SelectedOwner);};
        }
        public void SetComponents(IEnumerable<ComponentDefinition> components,string selectedId)
        {
            updating=true;
            try
            {
                var items=components.ToList();owner.DataSource=null;owner.DisplayMember="Label";owner.DataSource=items;
                owner.SelectedItem=items.FirstOrDefault(c=>c.Id==selectedId)??items.FirstOrDefault();
                owner.Enabled=items.Count>0;
            }
            finally {updating=false;}
        }
        public void SelectOwner(string id)
        {
            updating=true;
            try {owner.SelectedItem=owner.Items.Cast<ComponentDefinition>().FirstOrDefault(c=>c.Id==id);}
            finally {updating=false;}
        }
    }
}
