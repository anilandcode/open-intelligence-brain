import { ArrowRight, ArrowUpRight, Brain, Check, ChevronRight, Copy, FileText, GitBranch, Layers, Link, Menu, MessageSquare, Search, ShieldCheck, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { EvidenceCitation } from "./Evidence";
import { goTo, openConsole } from "./routes";

const excerpt = "Our best launches had a single person who owned the first customer week.";
const statement = "Assign one named owner for a customer’s first week.";
const samplePack = `# Customer onboarding\n\n${statement} [1]\n\n[1] Sample research interview, v1: ${excerpt}\n\nSynthetic example. Not connected to your workspace.`;
const sections = [["product", "Inside the console"], ["how-it-works", "How it works"], ["provenance", "Our principles"]] as const;
const recallExamples = [
  {label:"Context", title:"One owner. A better first week.", statement, source:"Customer research · v1", excerpt},
  {label:"Evidence", title:"Keep the reason with the decision.", statement:"Record the rationale behind each product decision.", source:"Product decisions · v1", excerpt:"We saved the decision, but not why we made it. The next team had to ask again."},
  {label:"History", title:"A change with a traceable history.", statement:"Send a written recap after every customer interview.", source:"Research practice · v2", excerpt:"A written recap helps the whole team check what they heard before making a decision."},
];
const stages = [
  {label:"Capture", status:"Original source · v1", title:"Original evidence ready", body:excerpt},
  {label:"Review", status:"Proposed lesson · awaiting approval", title:"A proposal to review", body:statement},
  {label:"Reuse", status:"Approved knowledge · source linked", title:"Approved context ready", body:statement},
];

function Wordmark() {
  return <a href="#/" className="site-wordmark" aria-label="Open Brain home"><span>Open Brain</span></a>;
}

/** Source hierarchy: outer band → patterned gutter → 1024px feature column. */
function SectionFrame({id, pattern, marker, category, children}: {id:string; pattern:"slash"|"dot"|"arrow"; marker?:string; category?:string; children:ReactNode}) {
  return <section className="site-frame" id={id}>
    {marker&&<div className="site-section-marker site-inner"><span>{marker}</span><span>/ {category}</span></div>}
    <div className={`site-pattern-gutter pattern-${pattern}`}><div className="site-inner">{children}</div></div>
  </section>;
}

function Wallpaper({kind, eager=false}: {kind:"hero"|"hills"|"pastel"|"goldblue"; eager?:boolean}) {
  const square=kind==="hills";
  const widths=square?[480,768,1024]:[640,960,1440];
  const srcset=(format:string)=>widths.map(w=>`/website/caret-${kind}-${w}.${format} ${w}w`).join(", ");
  return <picture className={`site-wallpaper wallpaper-${kind}`} aria-hidden="true">
    <source type="image/avif" srcSet={srcset("avif")} sizes={kind==="hero"?"(max-width: 768px) 100vw, calc(100vw - 64px)":"(max-width: 767px) calc(100vw - 48px), 512px"}/>
    <img src={`/website/caret-${kind}-${square?1024:1440}.webp`} srcSet={srcset("webp")} sizes={kind==="hero"?"(max-width: 768px) 100vw, calc(100vw - 64px)":"(max-width: 767px) calc(100vw - 48px), 512px"} alt="" width={square?1024:1440} height={square?1024:810} loading={eager?"eager":"lazy"} fetchPriority={eager?"high":undefined}/>
  </picture>;
}
function GraphicStage({className="", children}: {className?:string; children:ReactNode}) {
  return <div className={`site-graphic-stage ${className}`}>{children}</div>;
}
function GlassPill({children, className=""}: {children:ReactNode; className?:string}) {
  return <div className={`site-glass-pill ${className}`}>{children}</div>;
}
function AppWindow({title, view, children, className=""}: {title:string; view:"Sources"|"Activate"; children:ReactNode; className?:string}) {
  return <div className={`site-app-window site-console-preview ${className}`}>
    <header><span className="site-preview-brand">Open Brain</span><div className="site-preview-header"><span className="site-preview-workspace"><span>S</span>Sample Brain <small>Demo</small></span><ChevronRight size={10} aria-hidden="true"/><span>{view}</span></div></header>
    <div className="site-window-layout"><nav className="site-window-nav" aria-label={`${view} sample console navigation`}><span className="site-preview-search"><Search size={10}/> Search…</span>{[{route:"brain",label:"Brain",Icon:Brain},{route:"ask",label:"Playground",Icon:MessageSquare},{route:"sources",label:"Sources",Icon:FileText},{route:"activate",label:"Activate",Icon:Layers}].map(({route,label,Icon})=><a key={route} href={`#/demo/${route}`} aria-label={`Open ${label} demo`} className={label===view?"is-active":""}><Icon size={11}/>{label}</a>)}<small>Synthetic workspace</small></nav><div className="site-window-body"><span className="site-sample-label">Sample console · {view}</span><h4>{title}</h4>{children}</div></div>
  </div>;
}
function RecallAnswer() {
  return <GraphicStage className="answer-stage">
    <div className="site-source-ghost" aria-hidden="true"><span><ArrowRight size={10}/><FileText size={11}/> Customer research</span><strong>Learning from the first week</strong><p>Our best launches had a single person who owned the first customer week…</p></div>
    <div className="site-answer-float site-console-preview"><div className="site-float-label"><Brain size={16}/><span>How should we onboard a customer?</span></div><small>From approved knowledge</small><p>{statement}</p><EvidenceCitation index={1} title="Research interview · v1" excerpt={excerpt}/><span className="site-sample-label">Synthetic answer · approved knowledge only</span></div>
  </GraphicStage>;
}
function RelatedKnowledge() {
  return <GraphicStage className="related-stage">
    <div className="site-related-map" aria-hidden="true"><span className="map-core"><Brain size={18}/></span><span className="map-chip chip-one">Written recap</span><span className="map-chip chip-two">Customer onboarding</span><span className="map-chip chip-three">Product decisions</span><svg viewBox="0 0 480 220"><path d="M240 42L78 114M240 42L374 98M78 114L257 155M374 98L257 155"/></svg></div>
    <div className="site-answer-float related-answer site-console-preview"><div className="site-float-label"><GitBranch size={15}/><span>A decision has a history.</span></div><p>Record the reasoning. Keep the original source. Give the next team a starting point.</p><div className="site-citation-row"><FileText size={12}/><span>Product decision notes</span><span className="site-citation-count">v1</span></div></div>
  </GraphicStage>;
}
function RecallScene() {
  const [selected,setSelected]=useState(0); const sample=recallExamples[selected]; const id=useId();
  return <div className="site-two-grid recall-second-row">
    <div className="site-feature-cell recall-controls"><div className="site-feature-copy"><h3>Find the thread<br/>worth following.</h3><p>Bring approved knowledge and its evidence into view. Keep the context that makes an answer useful.</p></div>
      <div className="site-chip-tabs" role="tablist" aria-label="Recall examples">{recallExamples.map((s,i)=><button key={s.label} role="tab" id={`${id}-tab-${i}`} aria-selected={selected===i} aria-controls={`${id}-panel`} tabIndex={selected===i?0:-1} onClick={()=>setSelected(i)} onKeyDown={e=>{const next=e.key==="ArrowRight"?(i+1)%3:e.key==="ArrowLeft"?(i+2)%3:e.key==="Home"?0:e.key==="End"?2:null;if(next!==null){e.preventDefault();setSelected(next);document.getElementById(`${id}-tab-${next}`)?.focus();}}}>{i===0?<Layers size={12}/>:i===1?<FileText size={12}/>:<GitBranch size={12}/>} {s.label}</button>)}</div>
    </div>
    <GraphicStage className="evidence-scene"><Wallpaper kind="hills"/><div className="site-evidence-float site-console-preview" id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-tab-${selected}`} tabIndex={0}><span className="site-float-label"><Search size={15}/> Recall</span><h4>{sample.title}</h4><p>{sample.statement}</p><EvidenceCitation index={1} title={sample.source} excerpt={sample.excerpt}/><span className="site-sample-label">Synthetic example</span></div></GraphicStage>
  </div>;
}
function CaptureWindow() {
  return <GraphicStage className="capture-stage"><Wallpaper kind="goldblue"/><AppWindow title="Original source" view="Sources" className="capture-window"><p className="window-description">Keep what was said before deciding what it means.</p><dl className="site-source-metadata"><div><dt>Source</dt><dd>Customer research</dd></div><div><dt>Type</dt><dd>Interview</dd></div><div><dt>Version</dt><dd>Original · v1</dd></div><div><dt>Status</dt><dd>Captured</dd></div></dl><div className="site-original-excerpt"><small>EXACT EXCERPT</small><blockquote>“{excerpt}”</blockquote></div><div className="site-window-rule"/><h5>Proposed interpretation</h5><p>{statement}</p><span className="site-sample-label">Synthetic example · original preserved</span></AppWindow></GraphicStage>;
}
function ReviewScene() {
  const [stage,setStage]=useState(0); const sample=stages[stage];
  return <div className="site-split-row">
    <div className="site-feature-cell review-copy"><div className="site-feature-copy"><h3>Give good knowledge<br/>a second look.</h3><p>Sources, proposals and approved knowledge have different jobs. A person decides what belongs in the Brain.</p></div><div className="site-chip-tabs" role="tablist" aria-label="Capture review reuse">{stages.map((s,i)=><button key={s.label} role="tab" id={`workflow-tab-${i}`} aria-selected={stage===i} aria-controls="workflow-example" tabIndex={stage===i?0:-1} onClick={()=>setStage(i)} onKeyDown={e=>{const next=e.key==="ArrowRight"?(i+1)%3:e.key==="ArrowLeft"?(i+2)%3:e.key==="Home"?0:e.key==="End"?2:null;if(next!==null){e.preventDefault();setStage(next);document.getElementById(`workflow-tab-${next}`)?.focus();}}}>{String(i+1).padStart(2,"0")} {s.label}</button>)}</div><span className="site-sample-label">Demonstration · no live approval</span></div>
    <GraphicStage className="review-stage"><Wallpaper kind="pastel"/><div id="workflow-example" role="tabpanel" aria-labelledby={`workflow-tab-${stage}`} tabIndex={0}><GlassPill className="review-pill"><span className="site-brain-orb"><Brain size={22}/></span><span><strong>{sample.title}</strong><small>{sample.status}</small></span><span className="site-pill-state">{stage===2?<Check size={14}/>:<ArrowRight size={14}/>}</span></GlassPill><div className="site-review-caption"><p>{sample.body}</p></div></div><GlassPill className="site-knowledge-dock"><div className={stage===0?"dock-selected":""}><span><FileText/></span><small>Sources</small></div><ChevronRight size={12}/><div className={stage===1?"dock-selected":""}><span><Layers/></span><small>Proposals</small></div><ChevronRight size={12}/><div className={stage===2?"dock-selected":""}><span><ShieldCheck/></span><small>Knowledge</small></div></GlassPill></GraphicStage>
  </div>;
}
function ContextWindow() {
  return <GraphicStage className="context-stage"><Wallpaper kind="goldblue"/><AppWindow title="Customer onboarding" view="Activate" className="context-window"><p className="window-description">Approved context, ready for your next project.</p><small>KNOWLEDGE / 01</small><blockquote>{statement} <sup>[1]</sup></blockquote><div className="site-source-reference"><FileText size={12}/><div><strong>Customer research interview</strong><p>“{excerpt}”</p></div></div><small>KNOWLEDGE / 02</small><p>Keep the reasoning alongside the decision.</p><div className="site-window-rule"/><span className="site-sample-label">Citations stay attached</span></AppWindow></GraphicStage>;
}
function ExportScene() {
  const [copied,setCopied]=useState("");
  async function copy(){try{await navigator.clipboard.writeText(samplePack);setCopied("Sample context copied.");}catch{setCopied("Copy is unavailable here. Select the sample text below to copy it.");}}
  return <GraphicStage className="export-stage"><div className="site-export-route" aria-hidden="true"><div className="export-source"><Brain size={26}/></div><svg viewBox="0 0 480 110"><path d="M240 10V40M240 40H72V76M240 40V76M240 40H408V76"/></svg><div className="site-export-dock"><span><FileText size={30}/><small>Markdown</small></span><span><Copy size={30}/><small>Clipboard</small></span><span><Layers size={30}/><small>Context pack</small></span></div></div><div className="site-export-actions"><button className="site-mini-button" aria-label="Copy sample context" onClick={copy}><Copy size={12}/> Copy sample</button><a href="#/demo/activate"><ArrowUpRight size={12}/> Open builder</a></div><div className="site-copy-status" role="status">{copied}</div><details className="site-pack-details"><summary>Inspect sample Markdown</summary><pre>{samplePack}</pre></details></GraphicStage>;
}
function RevisionScene() {
  return <GraphicStage className="revision-stage"><Wallpaper kind="goldblue"/><div className="site-revision-stack"><div className="revision-card old-revision site-console-preview"><span><GitBranch size={12}/> v1 · approved</span><p>Assign one named owner for onboarding.</p></div><span className="site-revision-step"><GitBranch size={11}/> Wording revised</span><div className="revision-card site-console-preview"><span><ShieldCheck size={12}/> v2 · approved</span><p>{statement}</p><small>Original v1 wording remains in revision history.</small></div></div></GraphicStage>;
}
function TrustDiagram({kind}: {kind:"approval"|"evidence"|"versions"|"history"}) {
  return <div className={`site-trust-diagram diagram-${kind}`} aria-hidden="true">{kind==="approval"?<><span>PROPOSED</span><i/><ShieldCheck size={33}/><i/><span>APPROVED</span></>:kind==="evidence"?<><FileText size={32}/><svg viewBox="0 0 200 30"><path d="M2 15H198"/><circle cx="98" cy="15" r="3"/></svg><Link size={28}/></>:kind==="versions"?<><span>v1</span><span>v2</span><span>v3</span></>:<><span>Initial approval</span><GitBranch size={36}/><span>Revision recorded</span></>}</div>;
}
export default function LandingPage() {
  const [menu,setMenu]=useState(false); const dialogRef=useRef<HTMLDialogElement>(null); const menuRef=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if(!menu)return;const dialog=dialogRef.current;const opener=menuRef.current;if(!dialog)return;
    dialog.setAttribute("closedby","any");if(typeof dialog.showModal==="function")dialog.showModal();else dialog.setAttribute("open","");
    function fallback(e:MouseEvent){if(e.target!==dialog||!dialog)return;const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)setMenu(false);}
    if(!("closedBy" in HTMLDialogElement.prototype))dialog.addEventListener("click",fallback);
    return()=>{dialog.removeEventListener("click",fallback);if(dialog.open&&typeof dialog.close==="function")dialog.close();opener?.focus();};
  },[menu]);
  const links=()=>sections.map(([id,label])=><a key={id} href={`#${id}`} onClick={()=>setMenu(false)}>{label}</a>);
  return <div className="brain-site">
    <a className="skip-link" href="#landing-main">Skip to content</a>
    <header className="site-nav"><Wordmark/><nav aria-label="Website navigation">{links()}</nav><button className="site-primary site-nav-cta" onClick={()=>openConsole()}>Open Brain <ArrowUpRight size={13}/></button><button className="site-menu" ref={menuRef} aria-label="Open website navigation" aria-expanded={menu} aria-controls="site-mobile-navigation" onClick={()=>setMenu(true)}><Menu size={20}/></button></header>
    {menu&&<dialog ref={dialogRef} id="site-mobile-navigation" className="site-mobile-dialog" aria-label="Website navigation" onClose={()=>setMenu(false)} onCancel={e=>{e.preventDefault();setMenu(false);}}><div className="site-dialog-head"><Wordmark/><button aria-label="Close website navigation" onClick={()=>setMenu(false)}><X size={20}/></button></div><nav aria-label="Mobile website navigation">{links()}</nav><button className="site-primary" onClick={()=>openConsole()}>Open your Brain <ArrowUpRight size={14}/></button></dialog>}
    <main id="landing-main">
      <section className="site-hero-section"><div className="site-hero"><h1>A shared brain for<br/>people and agents.</h1><p>Turn original sources into reviewed knowledge.<br/>Keep the evidence. Reuse what you trust.</p><div className="site-hero-note"><ShieldCheck size={12}/> Human reviewed <span>·</span> Open source</div><div className="site-actions"><button className="site-secondary" onClick={()=>goTo("demo","brain")}>Explore the demo <ArrowRight size={13}/></button><button className="site-primary" onClick={()=>openConsole()}>Open your Brain <ArrowUpRight size={13}/></button></div></div>
        <div className="site-hero-desktop" id="product"><Wallpaper kind="hero" eager/><div className="site-hero-menubar"><span>Open Brain</span><span>Sources → review → knowledge</span><span className="hero-web-label">Workflow illustration · synthetic data</span></div><GlassPill className="site-hero-pill"><span className="site-brain-orb"><Brain size={20}/></span><span><strong>Approved context ready</strong><small>Customer onboarding · 2 sources</small></span><button aria-label="Explore approved context demo" onClick={()=>goTo("demo","brain")}><ArrowUpRight size={16}/></button></GlassPill><span className="site-hero-caption">Your best thinking, within reach.</span></div>
      </section>
      <SectionFrame id="recall" pattern="slash" marker="[01] RECALL" category="KNOWLEDGE"><h2 className="site-feature-intro">The answer you need.<br/>The <em>evidence</em> behind it.</h2><div className="site-two-grid"><article className="site-feature-cell"><div className="site-feature-copy"><h3>Answers from knowledge<br/>you have approved.</h3><p>Start with a reviewed statement. Follow the citation back to what was actually said.</p></div><RecallAnswer/></article><article className="site-feature-cell"><div className="site-feature-copy"><h3>Connect what you know<br/>to what comes next.</h3><p>Bring decisions, lessons and their original context into the same conversation.</p></div><RelatedKnowledge/></article></div><RecallScene/></SectionFrame>
      <SectionFrame id="how-it-works" pattern="dot" marker="[02] CAPTURE & REVIEW" category="EVIDENCE"><div className="site-split-row"><div className="site-feature-cell capture-copy"><div className="site-feature-copy"><h3>Keep the original.<br/>Review the meaning.</h3><p>Capture notes, interviews and decisions. Keep each source intact as knowledge takes shape.</p></div><div className="site-source-types"><FileText size={15}/><span>Notes</span><span>Interviews</span><span>Decisions</span></div></div><CaptureWindow/></div><ReviewScene/><span id="principles" className="site-anchor"/></SectionFrame>
      <SectionFrame id="agents" pattern="arrow" marker="[03] REUSE" category="CONTEXT"><div className="site-two-grid"><article className="site-feature-cell"><div className="site-feature-copy"><h3>Give your next project<br/>a better starting point.</h3><p>Assemble approved knowledge with its citations. Keep useful context close.</p></div><ContextWindow/></article><article className="site-feature-cell"><div className="site-feature-copy"><h3>Take your thinking<br/>into your workflow.</h3><p>Copy cited context or export Markdown. Use it with your existing tools and agents.</p></div><ExportScene/></article></div><div className="site-two-grid reuse-second-row"><div className="site-feature-cell"><div className="site-feature-copy"><h3>Good knowledge evolves.<br/>Its history stays.</h3><p>Refine the wording as you learn. See earlier versions and the evidence behind every change.</p><a className="site-inline-link" href="#/demo/brain">Inspect revision history <ArrowUpRight size={12}/></a></div></div><RevisionScene/></div></SectionFrame>
      <SectionFrame id="provenance" pattern="dot"><div className="site-human-wrap"><div className="site-human-card"><h2><strong>Your knowledge. Your final say.</strong> People approve. Sources stay intact. Changes leave a trail.</h2><div className="site-trust-grid">{[
        {kind:"approval" as const,title:"Human approval",text:"Only approval makes a proposal canonical."},
        {kind:"evidence" as const,title:"Evidence you can inspect",text:"Citations point to exact original excerpts."},
        {kind:"versions" as const,title:"Original versions preserved",text:"Source updates create a new version."},
        {kind:"history" as const,title:"A history of every change",text:"Revisions preserve earlier approved wording."},
      ].map(s=><article key={s.kind}><h3>{s.title}</h3><p>{s.text}</p><TrustDiagram kind={s.kind}/></article>)}</div></div></div></SectionFrame>
      <section className="site-final-section"><div className="site-inner"><div className="site-final-card"><h2>Build on what you know.</h2><p>A little less lost context. A clearer place to think.</p><div className="site-actions"><button className="site-primary" onClick={()=>openConsole()}>Open your Brain <ArrowUpRight size={13}/></button><button className="site-secondary" onClick={()=>goTo("demo","brain")}>Explore the demo <ArrowRight size={13}/></button></div></div><div className="site-footer-word" aria-hidden="true">Open Brain</div></div></section>
    </main>
    <footer className="site-footer"><div className="site-inner"><p>Open Brain<br/>Sources → review → approved knowledge</p><div className="site-footer-bottom"><span>© 2026 Open Brain</span><a href="https://github.com/anilandcode/open-intelligence-brain">Source code <ArrowUpRight size={12}/></a><a href="#landing-main">Back to top ↑</a></div></div></footer>
  </div>;
}
