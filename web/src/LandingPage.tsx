import { ArrowRight, Brain, Check, ChevronRight, FileText, GitBranch, LockKeyhole, Menu, MessageSquareText, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { goTo } from "./routes";

const steps = [
  { number: "01", title: "Capture the original", copy: "Bring in a note, decision, interview, or research. The source remains intact and versioned.", icon: FileText },
  { number: "02", title: "Review the interpretation", copy: "Candidates wait in your inbox. A person checks each claim beside its evidence.", icon: ShieldCheck },
  { number: "03", title: "Reuse what you trust", copy: "Only approved knowledge becomes available to grounded answers and context packs.", icon: GitBranch },
];

export default function LandingPage() {
  const [menu, setMenu] = useState(false);
  return <div className="landing">
    <a className="skip-link" href="#landing-main">Skip to content</a>
    <header className="landing-nav">
      <a href="#/" className="landing-brand" aria-label="Open Brain home"><span className="landing-brand-icon"><Brain size={22}/></span><span>open<span className="brand-serif">brain</span></span></a>
      <button className="landing-menu" type="button" aria-label="Toggle navigation" aria-expanded={menu} onClick={() => setMenu(!menu)}><Menu size={22}/></button>
      <nav className={menu ? "landing-links is-open" : "landing-links"} aria-label="Site navigation">
        <a href="#how-it-works" onClick={() => setMenu(false)}>How it works</a><a href="#principles" onClick={() => setMenu(false)}>Principles</a><a href="#agents" onClick={() => setMenu(false)}>For agents</a>
      </nav>
      <button className="landing-nav-cta" onClick={() => goTo("login")}>Open Brain <ArrowRight size={16}/></button>
    </header>
    <main id="landing-main">
      <section className="landing-hero">
        <div className="landing-hero-copy"><span className="landing-kicker"><span className="pulse-dot"/> Intelligence with its evidence intact</span>
          <h1>Make what your team knows <em>usable.</em></h1>
          <p>Open Brain turns scattered source material into reviewed, reusable knowledge. Every answer can lead back to the original, and every change has a history.</p>
          <div className="landing-actions"><button className="landing-solid" onClick={() => goTo("login")}>Open Brain <ArrowRight size={18}/></button><button className="landing-outline" onClick={() => goTo("demo")}>Explore demo <ChevronRight size={18}/></button></div>
          <div className="landing-hero-note"><Check size={16}/> Human review before knowledge becomes canonical</div>
        </div>
        <div className="landing-art"><img src="/brain-hero.png" alt="Abstract network of source fragments connecting into a structured knowledge system"/><div className="landing-art-label"><span>Source</span><span className="flow-line"/><span>Review</span><span className="flow-line"/><strong>Knowledge</strong></div></div>
      </section>
      <section className="landing-preview-section" aria-labelledby="preview-title"><div className="landing-section-head"><div><span className="landing-kicker">A working space for knowledge</span><h2 id="preview-title">Clarity from capture to answer.</h2></div><p>Move between original evidence, a human review queue, and the knowledge you have chosen to trust.</p></div>
        <div className="landing-console-preview interactive-preview">
          <iframe src="/#/demo/overview" title="Interactive Open Brain console with synthetic data" loading="lazy" />
        </div><p className="preview-disclaimer">Interactive demo with synthetic data. Changes stay in this preview. <button className="landing-text-link" onClick={() => goTo("demo")}>Open full demo <ArrowRight size={14}/></button></p>
      </section>
      <section className="landing-process" id="how-it-works"><div className="landing-section-head"><div><span className="landing-kicker">A deliberate path to trust</span><h2>Knowledge is a decision,<br/><em>not an extraction.</em></h2></div><p>Capture is the beginning. Review and provenance make an idea safe to reuse.</p></div><div className="process-grid">{steps.map(({number,title,copy,icon:Icon})=><article key={number}><div className="process-top"><span>{number}</span><Icon size={22}/></div><h3>{title}</h3><p>{copy}</p></article>)}</div></section>
      <section className="landing-example" id="principles"><div className="example-copy"><span className="landing-kicker">The distinction that matters</span><h2>One idea.<br/><em>Three layers of truth.</em></h2><p>A research note is evidence. A working memory is a useful interpretation. An approved statement is a decision your team can rely on. Open Brain keeps these layers visible.</p><button className="landing-text-link" onClick={() => goTo("demo", "brain")}>Explore the Brain <ArrowRight size={18}/></button></div><div className="example-stack"><div className="example-card"><span>01 / SOURCE</span><p>“Our best launches had a single person who owned the first customer week.”</p><small>Research interview · original excerpt</small></div><div className="example-card"><span>02 / WORKING MEMORY</span><p>Clear ownership may improve early customer onboarding.</p><small>Interpretation · awaits review</small></div><div className="example-card approved"><span><Check size={14}/> 03 / APPROVED KNOWLEDGE</span><p>Assign one owner for a customer’s first week.</p><small>Approved · linked to original source</small></div></div></section>
      <section className="landing-agents" id="agents"><div><span className="landing-kicker">Context for the work ahead</span><h2>Give agents context<br/><em>you can inspect.</em></h2><p>Assemble approved knowledge into a cited context pack. Keep the source of each claim close, whether a person or agent uses it.</p><button className="landing-outline" onClick={() => goTo("demo", "activate")}>See context assembly <ArrowRight size={18}/></button></div><div className="agent-visual"><div className="agent-visual-head"><Sparkles size={17}/> Context pack <span>PREVIEW</span></div><div className="agent-line"><Check size={16}/><span>Approved knowledge only</span></div><div className="agent-line"><FileText size={16}/><span>Source citations included</span></div><div className="agent-line"><GitBranch size={16}/><span>Revision history retained</span></div><div className="agent-response"><MessageSquareText size={18}/><p>“Here is the answer, with the evidence that supports it.”</p></div></div></section>
      <section className="landing-principles"><div><LockKeyhole size={24}/><h3>Originals stay original.</h3><p>Source updates create new versions. Existing evidence remains traceable.</p></div><div><ShieldCheck size={24}/><h3>People decide what counts.</h3><p>Proposals do not become canonical knowledge without approval.</p></div><div><GitBranch size={24}/><h3>Changes leave a trail.</h3><p>Revisions and possible conflicts remain visible, with their source links.</p></div></section>
      <section className="landing-final"><span className="landing-kicker">Start with what you already know</span><h2>Build a Brain your team<br/><em>can trust.</em></h2><div className="landing-actions"><button className="landing-solid" onClick={() => goTo("login")}>Open Brain <ArrowRight size={18}/></button><button className="landing-outline" onClick={() => goTo("demo")}>Explore demo <ChevronRight size={18}/></button></div></section>
    </main><footer className="landing-footer"><span className="landing-brand"><Brain size={18}/> open<span className="brand-serif">brain</span></span><span>Knowledge with evidence, review, and memory.</span><a href="#landing-main">Back to top ↑</a></footer>
  </div>;
}
