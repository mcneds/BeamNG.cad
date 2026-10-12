import { groupFor, registry } from './doc-evidence.mjs';
/** Mark numeric claims, literal settings and images at the Markdown AST boundary. */
export default function evidenceTags(){
  return (tree,file)=>{
    const path=String(file.path??file.history?.[0]??'').replaceAll('\\','/');
    const slug=path.split('/src/content/docs/')[1]?.replace(/\.mdx?$/,'');if(!slug)return;
    const group=groupFor(slug),record=registry().groups[group];
    const text=node=>node.value??node.children?.map(text).join(' ')??'';
    const walk=(node)=>{
      const numeric=['paragraph','table','code'].includes(node.type)&&/\d/.test(text(node));
      if(numeric||node.type==='image'){
        node.data??={};node.data.hProperties??={};
        Object.assign(node.data.hProperties,{'data-doc-evidence':group,'data-reviewed':record?.reviewed??'unreviewed',
          title:`Implementation snapshot: ${group}. Reviewed ${record?.reviewed??'not yet'}. See documentation maintenance for sources.`});
      }
      node.children?.forEach(walk);
    };walk(tree);
  };
}
