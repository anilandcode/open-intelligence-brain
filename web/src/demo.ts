import type { BrainClient } from "./client";
import type { Source, Proposal, Knowledge, SourceVersion, KnowledgeRevision, InterviewSessionDetail, DraftDetail, DraftSection } from "./api";

/** An isolated, synthetic workspace. This adapter has no network or token access. */
export function createDemoClient(): BrainClient {
  const date = () => new Date().toISOString();
  let sequence = 10;
  const id = (kind: string) => `sample-${kind}-${++sequence}`;
  const copy = <T,>(value: T): T => structuredClone(value);
  const sources: Source[] = [
    { id: "sample-source-1", title: "Customer onboarding interview", kind: "interview", sensitivity: "internal", content: "Assign one named owner for the first customer week. Keep the handoff short and send a written recap after every setup call.", created_at: date(), proposal_count: 2, current_version: 1, content_hash: "sample-hash-onboarding" },
    { id: "sample-source-2", title: "Product decision notes", kind: "note", sensitivity: "private", content: "Record the rationale behind each product decision. Review proposed knowledge before agents reuse it. Source evidence must travel with the final context pack.", created_at: date(), proposal_count: 2, current_version: 1, content_hash: "sample-hash-decisions" },
  ];
  const proposals: Proposal[] = sources.map((s, i) => ({ id: `sample-proposal-${i+1}`, source_id: s.id, source_title: s.title, type: i ? "principle" : "lesson", statement: i ? "Review proposed knowledge before agents reuse it." : "Send a written recap after every setup call.", rationale: "A candidate interpretation of the original interview, awaiting human review.", source_excerpt: s.content, status: "proposed", critic_notes: "Synthetic extraction. Inspect the evidence before approving.", created_at: date() }));
  const knowledge: Knowledge[] = sources.map((s, i) => ({ id: `sample-knowledge-${i+1}`, proposal_id: `sample-approved-${i+1}`, source_id: s.id, source_title: s.title, type: i ? "decision" : "lesson", statement: i ? "Record the rationale behind each product decision." : "Assign one named owner for the first customer week.", rationale: "Approved sample knowledge with preserved original evidence.", source_excerpt: s.content, status: "canonical", version: 1, approved_at: date(), revision_count: 1, stale: false, conflict_ids: [] }));
  const versions = new Map<string, SourceVersion[]>(sources.map(s => [s.id, [{ id: `${s.id}-v1`, source_id: s.id, version: 1, content_hash: s.content_hash, content: s.content, parser_version: "sample", change_note: "Original sample", created_at: s.created_at, span_count: 1, proposal_count: s.proposal_count }]]));
  const proposalVersions = new Map(proposals.map(p => [p.id, `${p.source_id}-v1`]));
  const revisions = new Map<string, KnowledgeRevision[]>(knowledge.map(k => [k.id, [{ id: `${k.id}-r1`, knowledge_id: k.id, revision: 1, statement: k.statement, rationale: k.rationale, source_id: k.source_id, source_version_id: `${k.source_id}-v1`, source_span_id: null, source_excerpt: k.source_excerpt, change_note: "Sample approval", approved_at: k.approved_at }]]));
  const interviews: InterviewSessionDetail[] = [{ id: "sample-interview-1", workspace_id: "sample-workspace", title: "A better first customer week", topic: "Onboarding", person: "Sample product lead", audience: "Customer success", outcome: "Understand handoff decisions", status: "active", source_id: null, created_at: date(), completed_at: null, question_count: 1, response_count: 0, extracted_count: 0, questions: [{ id: "sample-question-1", session_id: "sample-interview-1", ordinal: 1, question_text: "What makes a customer handoff work well?", response_text: "", extracted: false, created_at: date() }] }];
  const drafts: DraftDetail[] = [];
  const events = [{ id: id("event"), action: "knowledge.approved", detail: "Synthetic onboarding knowledge approved for this demo", created_at: date() }];
  function event(action: string, detail: string) { events.unshift({ id: id("event"), action, detail, created_at: date() }); }
  function find<T extends {id: string}>(items: T[], key: string): T { const item = items.find(x => x.id === key); if (!item) throw new Error("Sample record not found."); return item; }
  function capture(payload: Pick<Source, "title" | "kind" | "sensitivity" | "content">) {
    const s: Source = { ...payload, id: id("source"), created_at: date(), proposal_count: 1, current_version: 1, content_hash: id("hash") };
    sources.unshift(s);
    versions.set(s.id, [{ id: `${s.id}-v1`, source_id: s.id, version: 1, content_hash: s.content_hash, content: s.content, parser_version: "sample", change_note: "Original sample capture", created_at: date(), span_count: 1, proposal_count: 1 }]);
    proposals.unshift({ id: id("proposal"), source_id: s.id, source_title: s.title, type: "lesson", statement: s.content.split(/[.!?]/)[0], rationale: "Sample extraction only; review before reuse.", source_excerpt: s.content, status: "proposed", critic_notes: "Demo extraction uses the opening sentence, without an AI service.", created_at: date() });
    proposalVersions.set(proposals[0].id, `${s.id}-v1`);
    event("source.captured", s.title); return copy(s);
  }
  function makeDraft(payload: {title: string; intent?: string; audience?: string}): DraftDetail {
    const d: DraftDetail = { ...payload, intent: payload.intent ?? "brief", audience: payload.audience ?? "Team", id: id("draft"), workspace_id: "sample-workspace", status: "draft", created_at: date(), updated_at: date(), section_count: 0, citation_count: 0, sections: [] }; drafts.unshift(d); return d;
  }
  function section(d: DraftDetail, payload: {title: string; content: string; knowledge_ids?: string[]}): DraftSection {
    const atoms = (payload.knowledge_ids ?? []).map(key => find(knowledge, key));
    const s: DraftSection = { id: id("section"), draft_id: d.id, ordinal: d.sections.length+1, title: payload.title, content: payload.content, created_at: date(), citations: atoms.map(k => ({ id: id("citation"), section_id: "", knowledge_id: k.id, created_at: date() })), knowledge_items: atoms.map(k => ({id: k.id, statement: k.statement, type: k.type, source_excerpt: k.source_excerpt})) };
    s.citations.forEach(c => c.section_id = s.id); d.sections.push(s); d.section_count = d.sections.length; d.citation_count += atoms.length; return s;
  }
  return {
    overview: async () => ({ sources: sources.length, proposals: proposals.length, canonical: knowledge.length, pending_reviews: proposals.filter(p => p.status === "proposed").length, recent_activity: copy(events), engine: { name: "Synthetic demo", available: false, detail: "Local examples only. No model or API is connected.", container_tag: "sample", degraded: false } }),
    sources: async () => copy(sources), proposals: async () => copy(proposals.filter(p => p.status === "proposed")), knowledge: async (q = "") => copy(knowledge.filter(k => k.statement.toLowerCase().includes(q.toLowerCase()))),
    integrity: async () => ({ stale_count: knowledge.filter(k => k.stale).length, conflict_count: 0, issues: knowledge.filter(k => k.stale).map(k => ({kind: "stale_source" as const, knowledge_id: k.id, related_id: null, detail: "Sample source has a newer version. Review its approved knowledge."})) }),
    createSource: async payload => capture(payload),
    sourceVersions: async key => copy(versions.get(key) ?? []),
    addSourceVersion: async (key, content, changeNote) => { const s = find(sources,key); const v: SourceVersion = {id: id("version"),source_id:key,version:++s.current_version,content_hash:id("hash"),content,parser_version:"sample",change_note:changeNote,created_at:date(),span_count:1,proposal_count:1}; const p: Proposal = {id:id("proposal"),source_id:key,source_title:s.title,type:"lesson",statement:content.split(/[.!?]/)[0],rationale:"Sample interpretation of the updated source.",source_excerpt:content,status:"proposed",critic_notes:"Demo extraction only; review the source before approving.",created_at:date()}; proposals.unshift(p);proposalVersions.set(p.id,v.id);s.proposal_count++; s.content=content;s.content_hash=v.content_hash;versions.get(key)?.unshift(v);knowledge.filter(k=>k.source_id===key).forEach(k=>k.stale=true);event("source.versioned",s.title);return copy(v); },
    knowledgeRevisions: async key => copy(revisions.get(key) ?? []),
    supersedeKnowledge: async (key, statement, rationale, note) => {const k=find(knowledge,key);k.statement=statement;k.rationale=rationale;k.version++;k.revision_count++;k.approved_at=date();const original=revisions.get(key)![0];revisions.get(key)!.unshift({...original,id:id("revision"),revision:k.version,statement,rationale,change_note:note,approved_at:k.approved_at});event("knowledge.revised",statement);return copy(k);},
    approveProposal: async (key,statement,rationale) => {const p=find(proposals,key);if(p.status!=="proposed")throw new Error("Sample proposal has already been reviewed.");p.status="approved";const k:Knowledge={id:id("knowledge"),proposal_id:p.id,source_id:p.source_id,source_title:p.source_title,type:p.type,statement,rationale,source_excerpt:p.source_excerpt,status:"canonical",version:1,approved_at:date(),revision_count:1,stale:false,conflict_ids:[]};knowledge.unshift(k);revisions.set(k.id,[{id:id("revision"),knowledge_id:k.id,revision:1,statement,rationale,source_id:k.source_id,source_version_id:proposalVersions.get(p.id) ?? `${k.source_id}-v1`,source_span_id:null,source_excerpt:k.source_excerpt,change_note:"Sample approval",approved_at:k.approved_at}]);event("knowledge.approved",statement);return copy(k);},
    rejectProposal: async (key,reason) => {const p=find(proposals,key);p.status="rejected";event("proposal.rejected",reason);return copy(p);},
    chat: async question => {const terms=question.toLowerCase().split(/\W+/).filter(x=>x.length>3);const atoms=knowledge.filter(k=>terms.some(t=>k.statement.toLowerCase().includes(t)));return {answer:atoms.length?`Sample cited retrieval:\n\n${atoms.map(k=>k.statement).join("\n\n")}`:"No matching approved sample knowledge. Try asking about onboarding, customer owners, or decisions.",grounded:atoms.length>0,citations:atoms.map(k=>({knowledge_id:k.id,source_id:k.source_id,source_title:k.source_title,excerpt:k.source_excerpt}))};},
    exportUrl: "", // Workspace export is intentionally absent from the demo shell.
    interviews: async()=>copy(interviews), interview: async key=>copy(find(interviews,key)),
    createInterview: async payload=>{const s:InterviewSessionDetail={...payload,id:id("interview"),workspace_id:"sample-workspace",topic:payload.topic??"",person:payload.person??"",audience:payload.audience??"",outcome:payload.outcome??"",status:"active",source_id:null,created_at:date(),completed_at:null,question_count:0,response_count:0,extracted_count:0,questions:[]};interviews.unshift(s);return copy(s);},
    addQuestion: async(key,text)=>{const s=find(interviews,key);const q={id:id("question"),session_id:key,ordinal:++s.question_count,question_text:text,response_text:"",extracted:false,created_at:date()};s.questions.push(q);return copy(q);},
    submitResponse: async(key,qid,text)=>{const s=find(interviews,key);const q=find(s.questions,qid);if(!q.response_text)s.response_count++;q.response_text=text;if(!q.extracted)s.extracted_count++;q.extracted=true;capture({title:`${s.title} — response`,kind:"interview",sensitivity:"private",content:text});return copy(q);},
    completeInterview: async key=>{const s=find(interviews,key);s.status="completed";s.completed_at=date();return copy(s);},
    drafts: async()=>copy(drafts),draft:async key=>copy(find(drafts,key)),createDraft:async payload=>copy(makeDraft(payload)),
    addSection:async(key,payload)=>copy(section(find(drafts,key),payload)),deleteSection:async(key,sid)=>{const d=find(drafts,key);d.sections=d.sections.filter(s=>s.id!==sid);d.section_count=d.sections.length;d.citation_count=d.sections.reduce((n,s)=>n+s.citations.length,0);},
    assembleDraft:async payload=>{const d=makeDraft(payload);payload.knowledge_ids.forEach(key=>{const k=find(knowledge,key);section(d,{title:k.type,content:k.statement+(payload.include_excerpts?`\n\nEvidence: ${k.source_excerpt}`:""),knowledge_ids:[key]});});event("draft.assembled",d.title);return copy(d);},
  };
}
