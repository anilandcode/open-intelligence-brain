import { useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { Detail } from "./Detail";
const nodes = [
  { id: "interview", x: 120, y: 95, label: "Research interview", type: "Source", detail: "Original customer interview. Evidence remains distinct from interpretations." },
  { id: "proposal", x: 290, y: 205, label: "One named owner", type: "Proposal", detail: "Candidate interpretation awaiting review. It cannot be used as approved knowledge." },
  { id: "approved", x: 455, y: 112, label: "Approved ownership", type: "Approved", detail: "Approved sample statement linked to the original interview excerpt." },
  { id: "notes", x: 455, y: 320, label: "Support notes", type: "Source", detail: "Original support synthesis with a separate version history." },
  { id: "memory", x: 635, y: 215, label: "Setup handoff", type: "Working memory", detail: "Working interpretation, awaiting an explicit approval decision." },
];
const edges = [["interview", "proposal"], ["proposal", "approved"], ["proposal", "memory"], ["notes", "memory"]];
export default function GraphPreview() {
  const [filter,setFilter] = useState("All");
  const [list,setList] = useState(false);
  const [zoom,setZoom] = useState(1);
  const [pan,setPan] = useState({x:0,y:0});
  const [selected,setSelected] = useState<string|null>(null);
  const drag = useRef<{x:number;y:number;originX:number;originY:number}|null>(null);
  const visible=nodes.filter(n=>filter==="All"||n.type===filter);
  const selectedNode=nodes.find(n=>n.id===selected);
  const move=(x:number,y:number)=>setPan(p=>({x:p.x+x,y:p.y+y}));
  return <><div className="preview-toolbar"><div className="tabs" role="group" aria-label="Filter graph nodes">{["All","Source","Proposal","Working memory","Approved"].map(x=><button key={x} aria-pressed={filter===x} className={filter===x?"active":""} onClick={()=>setFilter(x)}>{x}</button>)}</div><button className="secondary-button" onClick={()=>setList(!list)}>{list?"Graph view":"Accessible list"}</button></div><div className="graph-canvas" onPointerDown={e=>{if((e.target as HTMLElement).closest("button"))return;drag.current={x:e.clientX,y:e.clientY,originX:pan.x,originY:pan.y};e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{if(drag.current)setPan({x:drag.current.originX+e.clientX-drag.current.x,y:drag.current.originY+e.clientY-drag.current.y});}} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
    <div className="graph-controls"><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(2,z+.15))}><ZoomIn size={17}/></button><button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(.5,z-.15))}><ZoomOut size={17}/></button><button aria-label="Reset graph" onClick={()=>{setZoom(1);setPan({x:0,y:0});}}><Maximize2 size={17}/></button><button aria-label="Pan left" onClick={()=>move(-40,0)}><ArrowLeft size={17}/></button><button aria-label="Pan right" onClick={()=>move(40,0)}><ArrowRight size={17}/></button><button aria-label="Pan up" onClick={()=>move(0,-40)}><ArrowUp size={17}/></button><button aria-label="Pan down" onClick={()=>move(0,40)}><ArrowDown size={17}/></button></div>
    {list?<div className="graph-list"><h2>Knowledge relationships</h2>{visible.map(n=><button className="preview-row" key={n.id} onClick={()=>setSelected(n.id)}><strong>{n.label}</strong><span>{n.type}</span><ArrowRight size={16}/></button>)}</div>:<div className="graph-inner" style={{transform:`translate(${pan.x}px,${pan.y}px) scale(${zoom})`}}><svg viewBox="0 0 760 430" preserveAspectRatio="none" aria-hidden="true">{edges.filter(([a,b])=>visible.some(n=>n.id===a)&&visible.some(n=>n.id===b)).map(([a,b])=>{const n=nodes.find(x=>x.id===a)!,m=nodes.find(x=>x.id===b)!;return <line key={a+b} x1={n.x} y1={n.y} x2={m.x} y2={m.y}/>;})}</svg>{visible.map(n=><button key={n.id} className={`graph-node node-${n.type.toLowerCase().replace(" ","-")}`} style={{left:`${n.x/760*100}%`,top:`${n.y/430*100}%`}} onClick={()=>setSelected(n.id)} aria-label={`${n.label}, ${n.type}`}>{n.label}</button>)}</div>}
    <div className="graph-legend"><strong>Legend</strong>{["Source","Proposal","Working memory","Approved"].map(x=><span key={x}><i/>{x}</span>)}</div>
  </div>{selectedNode&&<Detail title={selectedNode.label} onClose={()=>setSelected(null)}><span className="status-pill">{selectedNode.type} · Sample</span><p>{selectedNode.detail}</p><h3>Connected records</h3>{edges.filter(e=>e.includes(selectedNode.id)).map(e=>nodes.find(n=>n.id===e.find(x=>x!==selectedNode.id))!).map(n=><button key={n.id} className="preview-row" onClick={()=>setSelected(n.id)}><span>{n.label}</span><ArrowRight size={16}/></button>)}</Detail>}</>;
}
