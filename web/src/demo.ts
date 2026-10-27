import type { BrainClient } from "./client";
import type { AgentNote, BatchReviewResult, Gardening, SourceHit, Watch, EvalQuestion, EvalReport, EvalRun, Entity, EntityChip, EntityRef, Source, Proposal, Knowledge, SourceVersion, KnowledgeRevision, InterviewSessionDetail, DraftDetail, DraftSection, McpConnection, ConnectedAccount, StagedAction } from "./api";

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
  const proposals: Proposal[] = sources.map((s, i) => ({ id: `sample-proposal-${i+1}`, source_id: s.id, source_title: s.title, type: i ? "principle" : "lesson", statement: i ? "Review proposed knowledge before agents reuse it." : "Send a written recap after every setup call.", rationale: "A candidate interpretation of the original interview, awaiting human review.", source_excerpt: s.content, status: "proposed", critic_notes: "Synthetic extraction. Inspect the evidence before approving.", summary: "Candidate extracted from the interview, awaiting review.", tags: '["setup", "handoff"]', entities: [{ name: i ? "Product team" : "Customer onboarding", kind: i ? "project" : "topic" }], created_at: date() }));
  const entities: Entity[] = [
    { id: "sample-entity-1", name: "Customer onboarding", kind: "topic", aliases: [], item_count: 0 },
    { id: "sample-entity-2", name: "Product team", kind: "project", aliases: [], item_count: 0 },
  ];
  const knowledge: Knowledge[] = sources.map((s, i) => ({ entities: [{ id: entities[i].id, name: entities[i].name, kind: entities[i].kind }], id: `sample-knowledge-${i+1}`, proposal_id: `sample-approved-${i+1}`, source_id: s.id, source_title: s.title, type: i ? "decision" : "lesson", statement: i ? "Record the rationale behind each product decision." : "Assign one named owner for the first customer week.", rationale: "Approved sample knowledge with preserved original evidence.", source_excerpt: s.content, status: "canonical", version: 1, approved_at: date(), revision_count: 1, stale: false, conflict_ids: [] }));
  const versions = new Map<string, SourceVersion[]>(sources.map(s => [s.id, [{ id: `${s.id}-v1`, source_id: s.id, version: 1, content_hash: s.content_hash, content: s.content, parser_version: "sample", change_note: "Original sample", created_at: s.created_at, span_count: 1, proposal_count: s.proposal_count }]]));
  const proposalVersions = new Map(proposals.map(p => [p.id, `${p.source_id}-v1`]));
  const revisions = new Map<string, KnowledgeRevision[]>(knowledge.map(k => [k.id, [{ id: `${k.id}-r1`, knowledge_id: k.id, revision: 1, statement: k.statement, rationale: k.rationale, source_id: k.source_id, source_version_id: `${k.source_id}-v1`, source_span_id: null, source_excerpt: k.source_excerpt, change_note: "Sample approval", approved_at: k.approved_at }]]));
  const interviews: InterviewSessionDetail[] = [{ id: "sample-interview-1", workspace_id: "sample-workspace", title: "A better first customer week", topic: "Onboarding", person: "Sample product lead", audience: "Customer success", outcome: "Understand handoff decisions", status: "active", source_id: null, created_at: date(), completed_at: null, question_count: 1, response_count: 0, extracted_count: 0, questions: [{ id: "sample-question-1", session_id: "sample-interview-1", ordinal: 1, question_text: "What makes a customer handoff work well?", response_text: "", extracted: false, created_at: date() }] }];
  const drafts: DraftDetail[] = [];
  const connections: McpConnection[] = [{ id: "sample-mcp-1", client_id: "", client_name: "", source_kind: "api_key", principal_preview: "owner…demo", role: "owner", user_agent: "Antigravity/1.0 (sample)", access_count: 3, first_seen: date(), last_seen: date(), status: "active" }];
  const events = [{ id: id("event"), action: "knowledge.approved", detail: "Synthetic onboarding knowledge approved for this demo", created_at: date() }];
  function event(action: string, detail: string) { events.unshift({ id: id("event"), action, detail, created_at: date() }); }
  function find<T extends {id: string}>(items: T[], key: string): T { const item = items.find(x => x.id === key); if (!item) throw new Error("Sample record not found."); return item; }
  function capture(payload: Pick<Source, "title" | "kind" | "sensitivity" | "content">) {
    const s: Source = { ...payload, id: id("source"), created_at: date(), proposal_count: 1, current_version: 1, content_hash: id("hash") };
    sources.unshift(s);
    versions.set(s.id, [{ id: `${s.id}-v1`, source_id: s.id, version: 1, content_hash: s.content_hash, content: s.content, parser_version: "sample", change_note: "Original sample capture", created_at: date(), span_count: 1, proposal_count: 1 }]);
    proposals.unshift({ id: id("proposal"), source_id: s.id, source_title: s.title, type: "lesson", statement: s.content.split(/[.!?]/)[0], rationale: "Sample extraction only; review before reuse.", source_excerpt: s.content, status: "proposed", critic_notes: "Demo extraction uses the opening sentence, without an AI service.", summary: "Opening sentence captured as a candidate.", tags: '["demo"]', created_at: date() });
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
  const evalQuestions: EvalQuestion[] = [];
  const flags = (k: Knowledge) => ({ due_for_review: !!k.review_by && new Date(k.review_by) <= new Date(), expired: !!k.expires_at && new Date(k.expires_at) <= new Date() });
  const dated = (dates?: { as_of?: string | null; review_by?: string | null; expires_at?: string | null }) => { const frame = { as_of: dates?.as_of ?? null, review_by: dates?.review_by ?? null, expires_at: dates?.expires_at ?? null }; return { ...frame, ...flags(frame as Knowledge) }; };
  const evalRuns: EvalRun[] = [];
  const watches: Watch[] = [];
  const notes: AgentNote[] = [{ id: "sample-note-1", author: "obk_agent…", topic: "renewal research", content: "Three customers asked about multi-year renewal pricing this week; check whether the discount cap applies to them.", sensitivity: "private", created_at: date(), expires_at: new Date(Date.now() + 6 * 86_400_000).toISOString(), promoted_source_id: null, promoted_at: null }];
  const entityByName = (name: string) => entities.find(e => e.name.toLowerCase() === name.toLowerCase() || e.aliases.some(a => a.toLowerCase() === name.toLowerCase()));
  const chipsFor = (refs: (EntityRef | EntityChip)[]): EntityChip[] => refs.map(ref => {
    const existing = entityByName(ref.name) ?? (() => { const created: Entity = { id: id("entity"), name: ref.name, kind: ref.kind as Entity["kind"], aliases: [], item_count: 0 }; entities.push(created); return created; })();
    return { id: existing.id, name: existing.name, kind: existing.kind };
  });
  const linkedTo = (entityId: string) => knowledge.filter(k => k.status === "canonical" && (k.entities ?? []).some(chip => chip.id === entityId));
  const entityView = (e: Entity): Entity => ({ ...copy(e), item_count: linkedTo(e.id).length });
  const client: BrainClient = {
    authStatus: async () => ({ sign_in_available: false, provider: null }),
    connectedAccounts: async () => [
      {
        connected_account_id: "sample-account-1",
        toolkit_slug: "x",
        alias: "personal-x",
        provider_account_id: "sample-x-user",
        display_name: "Sample account",
        status: "ACTIVE",
        expires_at: null,
        credential_state: "present",
      } satisfies ConnectedAccount,
    ],
    startConnectionLink: async () => ({ authorization_url: "https://example.com/authorize", session_uri: "su_sample" }),
    renameConnection: async (accountId: string, alias: string) => ({ connected_account_id: accountId, alias }),
    appConfig: async () => ({ redirect_uri: "https://bridge.trulyagentic.io/oauth/callback" }),
    setAppCredentials: async (toolkitSlug: string, clientId: string, _secret: string | null, environment: string, scopes: string | null) => ({
      toolkit_slug: toolkitSlug,
      client_id: clientId,
      environment,
      scopes,
      saved: true,
    }),
    verifyOAuthSession: async () => ({ connected_account_id: "sample-account-1", status: "ACTIVE" }),
    stagedActions: async () => [
      {
        id: "sample-action-1",
        tool_name: "X_CREATE_POST",
        account_alias: "personal-x",
        payload: { text: "Sample staged post" },
        status: "PENDING",
        result_urn: "",
        error: "",
        created_at: date(),
        decided_at: null,
      } satisfies StagedAction,
    ],
    stageAction: async (toolName: string, accountAlias: string, payload: Record<string, unknown>) => ({
      id: "sample-action-2",
      tool_name: toolName,
      account_alias: accountAlias,
      payload,
      status: "PENDING",
      result_urn: "",
      error: "",
      created_at: date(),
      decided_at: null,
    }),
    approveStagedAction: async (id: string) => ({
      id,
      tool_name: "X_CREATE_POST",
      account_alias: "personal-x",
      payload: {},
      status: "EXECUTED",
      result_urn: "urn:sample:post-1",
      error: "",
      created_at: date(),
      decided_at: date(),
    }),
    rejectStagedAction: async (id: string) => ({
      id,
      tool_name: "X_CREATE_POST",
      account_alias: "personal-x",
      payload: {},
      status: "REJECTED",
      result_urn: "",
      error: "",
      created_at: date(),
      decided_at: date(),
    }),
    login: async () => {
      throw new Error("Sign-in is not available in the sample workspace.");
    },
    logout: async () => undefined,
    me: async () => ({
      user: {
        id: "sample-user",
        provider: "demo",
        email: "sample@example.com",
        display_name: "Sample reviewer",
      },
      memberships: [],
    }),
    bootstrap: async () => {
      throw new Error("Claim is not available in the sample workspace.");
    },
    graph: async () => ({
      documents: [
        {
          id: "doc-demo-1",
          title: "Research interview",
          summary: "Original customer interview synthesis.",
          documentType: "interview",
          createdAt: "2026-09-28T10:00:00Z",
          updatedAt: "2026-09-28T10:00:00Z",
          memories: [
            { id: "mem-demo-1", memory: "One named owner is required for account setup.", content: "Approved from the interview excerpt.", version: 1, memoryRelations: {} },
            { id: "mem-demo-2", memory: "Setup handoff is the final activation step.", content: "Approved from the interview excerpt.", version: 1, memoryRelations: {} },
          ],
        },
      ],
      edges: [
        { source: "doc-demo-1", target: "mem-demo-1", edgeType: "document" },
        { source: "doc-demo-1", target: "mem-demo-2", edgeType: "document" },
        { source: "mem-demo-1", target: "mem-demo-2", edgeType: "extends" },
      ],
    }),
    overview: async () => ({ sources: sources.length, proposals: proposals.length, canonical: knowledge.length, pending_reviews: proposals.filter(p => p.status === "proposed").length, recent_activity: copy(events), engine: { name: "Synthetic demo", available: false, detail: "Local examples only. No model or API is connected.", container_tag: "sample", degraded: false } }),
    sources: async () => copy(sources), proposals: async () => copy(proposals.filter(p => p.status === "proposed")), knowledge: async (q = "") => copy(knowledge.filter(k => k.statement.toLowerCase().includes(q.toLowerCase()))),
    integrity: async () => ({ stale_count: knowledge.filter(k => k.stale).length, conflict_count: 0, issues: knowledge.filter(k => k.stale).map(k => ({kind: "stale_source" as const, knowledge_id: k.id, related_id: null, detail: "Sample source has a newer version. Review its approved knowledge."})) }),
    createSource: async payload => capture(payload),
    scratchpad: async (topic = "") => copy(notes.filter(n => !topic || n.topic === topic)),
    deleteNote: async key => {notes.splice(notes.indexOf(find(notes,key)),1);},
    promoteNote: async (key, title = "") => {const n=find(notes,key);if(n.promoted_source_id)throw new Error("This note was already promoted");const s=capture({title:title||`Agent note: ${n.topic||n.content.slice(0,60)}`,kind:"note",sensitivity:n.sensitivity,content:n.content});n.promoted_source_id=s.id;n.promoted_at=date();return s;},
    searchSources: async (query, limit = 10) => {const terms=query.toLowerCase().split(/\W+/).filter(t=>t.length>2);if(!terms.length)return [];const hits:SourceHit[]=[];sources.forEach(s=>s.content.split(/(?<=[.!?])\s+/).forEach(sentence=>{const score=terms.filter(t=>sentence.toLowerCase().includes(t)).length/terms.length;if(score>0){const k=knowledge.find(item=>item.status==="canonical"&&item.source_excerpt===sentence);hits.push({source_id:s.id,source_title:s.title,source_kind:s.kind,version:s.current_version,excerpt:sentence,speaker:null,status:k?"approved":"unreviewed",knowledge_id:k?.id ?? null,score});}}));return hits.sort((a,b)=>b.score-a.score).slice(0,limit);},
    capture: async payload => {const text=payload.text.trim();const content=payload.url?`${text}\n\nSource: ${payload.url}`:text;if(content.length<20)throw new Error("Too short to capture: add a few words.");const firstLine=text.split("\n").find(line=>line.trim())?.trim() ?? "";return capture({title:payload.title?.trim()||(firstLine.length>=3?firstLine.slice(0,80):payload.url||"Quick capture"),kind:payload.kind ?? "note",sensitivity:payload.sensitivity ?? "private",content});},
    watches: async () => copy(watches),
    createWatch: async payload => {if(watches.some(w=>w.provider===payload.provider&&w.folder_id===payload.folder_id))throw new Error("This folder is already watched");const w:Watch={id:id("watch"),provider:payload.provider,folder_id:payload.folder_id,label:payload.label ?? "",kind:payload.kind ?? "research",sensitivity:payload.sensitivity ?? "private",last_synced_at:null,last_result:"",created_at:date(),document_count:0};watches.push(w);event("watch.created",w.label||w.folder_id);return copy(w);},
    deleteWatch: async key => {watches.splice(watches.indexOf(find(watches,key)),1);},
    syncWatch: async key => {const w=find(watches,key);const first=w.document_count===0;if(first){capture({title:`${w.label||"Watched folder"}: sample document`,kind:w.kind,sensitivity:w.sensitivity,content:"A sample document from the watched folder, staged for review before any of it becomes canonical knowledge."});w.document_count=1;}const result={added:first?[`${w.label||"Watched folder"}: sample document`]:[],updated:[],unchanged:first?0:w.document_count,deferred:0,errors:[],summary:first?"1 new, 0 updated, 0 unchanged":`0 new, 0 updated, ${w.document_count} unchanged`};w.last_synced_at=date();w.last_result=result.summary;return result;},
    connectorIngest: async () => capture({ title: "Fetched provider document", kind: "research", sensitivity: "internal", content: "A document fetched from a connected provider, staged for human review before any of it becomes canonical knowledge." }),
    sourceVersions: async key => copy(versions.get(key) ?? []),
    addSourceVersion: async (key, content, changeNote) => { const s = find(sources,key); const v: SourceVersion = {id: id("version"),source_id:key,version:++s.current_version,content_hash:id("hash"),content,parser_version:"sample",change_note:changeNote,created_at:date(),span_count:1,proposal_count:1}; const p: Proposal = {id:id("proposal"),source_id:key,source_title:s.title,type:"lesson",statement:content.split(/[.!?]/)[0],rationale:"Sample interpretation of the updated source.",source_excerpt:content,status:"proposed",critic_notes:"Demo extraction only; review the source before approving.",created_at:date()}; proposals.unshift(p);proposalVersions.set(p.id,v.id);s.proposal_count++; s.content=content;s.content_hash=v.content_hash;versions.get(key)?.unshift(v);knowledge.filter(k=>k.source_id===key).forEach(k=>k.stale=true);event("source.versioned",s.title);return copy(v); },
    knowledgeRevisions: async key => copy(revisions.get(key) ?? []),
    supersedeKnowledge: async (key, statement, rationale, note) => {const k=find(knowledge,key);k.statement=statement;k.rationale=rationale;k.version++;k.revision_count++;k.approved_at=date();const original=revisions.get(key)![0];revisions.get(key)!.unshift({...original,id:id("revision"),revision:k.version,statement,rationale,change_note:note,approved_at:k.approved_at});event("knowledge.revised",statement);return copy(k);},
    approveProposal: async (key,statement,rationale,_tags,asNew,chosen,dates) => {const p=find(proposals,key);const chips=chipsFor(chosen ?? p.entities ?? []);if(p.status!=="proposed")throw new Error("Sample proposal has already been reviewed.");const target=!asNew&&p.relation&&p.relation!=="new"?knowledge.find(item=>item.id===p.target_knowledge_id):undefined;if(target){p.status="approved";target.statement=statement;target.rationale=rationale;target.source_id=p.source_id;target.source_title=p.source_title;target.source_excerpt=p.source_excerpt;target.version+=1;target.revision_count+=1;target.entities=[...(target.entities ?? []),...chips.filter(chip=>!(target.entities ?? []).some(old=>old.id===chip.id))];revisions.get(target.id)?.unshift({id:id("revision"),knowledge_id:target.id,revision:target.version,statement,rationale,source_id:p.source_id,source_version_id:proposalVersions.get(p.id) ?? `${p.source_id}-v1`,source_span_id:null,source_excerpt:p.source_excerpt,change_note:"Sample update from new evidence",approved_at:date()});event("knowledge.updated",statement);return copy(target);}p.status="approved";const k:Knowledge={id:id("knowledge"),proposal_id:p.id,source_id:p.source_id,source_title:p.source_title,type:p.type,statement,rationale,source_excerpt:p.source_excerpt,status:"canonical",version:1,approved_at:date(),revision_count:1,stale:false,conflict_ids:[],entities:chips,...dated(dates)};knowledge.unshift(k);revisions.set(k.id,[{id:id("revision"),knowledge_id:k.id,revision:1,statement,rationale,source_id:k.source_id,source_version_id:proposalVersions.get(p.id) ?? `${k.source_id}-v1`,source_span_id:null,source_excerpt:k.source_excerpt,change_note:"Sample approval",approved_at:k.approved_at}]);event("knowledge.approved",statement);return copy(k);},
    rejectProposal: async (key,reason) => {const p=find(proposals,key);p.status="rejected";event("proposal.rejected",reason);return copy(p);},
    entities: async (kind, query = "") => entities.filter(e => (!kind || e.kind === kind) && (!query || `${e.name} ${e.aliases.join(" ")}`.toLowerCase().includes(query.toLowerCase()))).map(entityView).filter(e => e.item_count > 0).sort((a, b) => b.item_count - a.item_count || a.name.localeCompare(b.name)),
    entity: async key => {const e=find(entities,key);const items=linkedTo(e.id);const counts=new Map<string,number>();items.forEach(k=>(k.entities ?? []).forEach(chip=>{if(chip.id&&chip.id!==e.id)counts.set(chip.id,(counts.get(chip.id) ?? 0)+1);}));return {...entityView(e),items:copy(items),related:[...counts.entries()].map(([other,count])=>({...entityView(find(entities,other)),item_count:count}))};},
    createEntity: async payload => {if(entityByName(payload.name))throw new Error(`${payload.name} is already a name or alias in this workspace`);const e:Entity={id:id("entity"),name:payload.name,kind:payload.kind,aliases:payload.aliases ?? [],item_count:0};entities.push(e);if(payload.link_existing!==false)knowledge.filter(k=>k.statement.toLowerCase().includes(e.name.toLowerCase())).forEach(k=>{k.entities=[...(k.entities ?? []),{id:e.id,name:e.name,kind:e.kind}];});event("entity.created",e.name);return entityView(e);},
    updateEntity: async (key, payload) => {const e=find(entities,key);if(payload.name&&payload.name!==e.name){e.aliases=[...e.aliases,e.name];e.name=payload.name;}if(payload.kind)e.kind=payload.kind;if(payload.aliases)e.aliases=payload.aliases;knowledge.forEach(k=>{k.entities=(k.entities ?? []).map(chip=>chip.id===e.id?{id:e.id,name:e.name,kind:e.kind}:chip);});event("entity.updated",e.name);return entityView(e);},
    mergeEntity: async (key, intoId) => {const dup=find(entities,key);const keep=find(entities,intoId);if(dup.id===keep.id)throw new Error("An entity cannot be merged into itself");knowledge.forEach(k=>{const chips=k.entities ?? [];if(chips.some(chip=>chip.id===dup.id)){k.entities=[...chips.filter(chip=>chip.id!==dup.id&&chip.id!==keep.id),{id:keep.id,name:keep.name,kind:keep.kind}];}});keep.aliases=[...keep.aliases,dup.name,...dup.aliases];entities.splice(entities.indexOf(dup),1);event("entity.merged",`${dup.name} into ${keep.name}`);return entityView(keep);},
    setTimeframe: async (key, changes) => {const k=find(knowledge,key);Object.assign(k,changes,flags({...k,...changes} as Knowledge));event("knowledge.timeframe",k.statement);return copy(k);},
    markReviewed: async (key, days = 90) => {const k=find(knowledge,key);k.last_reviewed_at=date();k.review_by=days?new Date(Date.now()+days*86_400_000).toISOString():null;Object.assign(k,flags(k));event("knowledge.reviewed",k.statement);return copy(k);},
    gardening: async () => {const live=knowledge.filter(k=>k.status==="canonical");const item=(k:Knowledge,detail:string)=>({knowledge_id:k.id,statement:k.statement,detail});const report={generated_at:date(),due_for_review:live.filter(k=>flags(k).due_for_review).map(k=>item(k,`Review was due ${k.review_by?.slice(0,10)}`)),expired:live.filter(k=>flags(k).expired).map(k=>item(k,`Expired ${k.expires_at?.slice(0,10)}`)),source_changed:live.filter(k=>k.stale).map(k=>item(k,"The sentence it rests on changed in a newer version")),conflicts:[],duplicates:[],unused:[]} as unknown as Gardening;const keys=["due_for_review","expired","source_changed","conflicts","duplicates","unused"] as const;report.counts=Object.fromEntries(keys.map(key=>[key,report[key].length])) as Gardening["counts"];report.total=keys.reduce((sum,key)=>sum+report[key].length,0);return report;},
    sendGardening: async () => ({sent:false,reason:"The demo workspace has no Hermes connection.",text:""}),
    evalQuestions: async () => copy(evalQuestions),
    addEvalQuestion: async payload => {const expected=payload.expected_ids ?? [];if(!payload.expect_abstain&&!expected.length)throw new Error("Name at least one expected item, or mark it as abstain");const q:EvalQuestion={id:id("evq"),question:payload.question,expected_ids:expected,expect_abstain:!!payload.expect_abstain,note:payload.note ?? "",created_at:date()};evalQuestions.push(q);return copy(q);},
    deleteEvalQuestion: async key => {evalQuestions.splice(evalQuestions.indexOf(find(evalQuestions,key)),1);},
    runEval: async (label = "") => {const results=await Promise.all(evalQuestions.map(async q=>{const r=await client.chat(q.question);const cited=r.citations.map(c=>c.knowledge_id);const passed=q.expect_abstain?!r.grounded:r.grounded&&cited.some(c=>q.expected_ids.includes(c));return {id:q.id,question:q.question,expect_abstain:q.expect_abstain,expected_ids:q.expected_ids,passed,grounded:r.grounded,cited_ids:cited,retrieved_ids:cited,hit_rank:passed&&!q.expect_abstain?1:null,stale_ids:[],reason:passed?"":q.expect_abstain?"Answered a question it should abstain on":"Answered without citing an expected item"};}));const answerable=results.filter(r=>!r.expect_abstain);const abstain=results.filter(r=>r.expect_abstain);const share=(a:number,b:number)=>b?Math.round(a/b*1000)/1000:null;const run:EvalReport={id:id("evr"),label,created_at:date(),results,summary:{questions:results.length,passed:results.filter(r=>r.passed).length,pass_rate:share(results.filter(r=>r.passed).length,results.length),answerable:answerable.length,recall_at_8:share(answerable.filter(r=>r.hit_rank).length,answerable.length),mrr:share(answerable.filter(r=>r.hit_rank).length,answerable.length),answered_correctly:answerable.filter(r=>r.passed).length,abstain_questions:abstain.length,abstained_correctly:abstain.filter(r=>r.passed).length,false_answers:abstain.filter(r=>!r.passed).length,stale_questions:0,write_answers:false}};evalRuns.unshift({id:run.id,label,summary:run.summary,created_at:run.created_at});return copy(run);},
    evalRuns: async () => copy(evalRuns),
    reviewProposals: async (keys, action, reason) => {const result: BatchReviewResult = {approved: [], rejected: [], skipped: []};for (const key of keys) {const p=proposals.find(item => item.id===key);if(!p||p.status!=="proposed"){result.skipped.push({proposal_id:key,reason:p?"Sample proposal has already been reviewed.":"Not found"});continue;}if(action==="approve"){const k=await client.approveProposal(p.id,p.statement,p.rationale);result.approved.push(k.id);}else{p.status="rejected";event("proposal.rejected",reason ?? "Sample batch reject");result.rejected.push(p.id);}}return result;},
    dismissSourceProposals: async (sourceKey, reason) => {const pending=proposals.filter(p => p.source_id===sourceKey && p.status==="proposed");pending.forEach(p => {p.status="rejected";});if(pending.length) event("proposal.rejected",reason);return {source_id:sourceKey,rejected:pending.length};},
    chat: async question => {const terms=question.toLowerCase().split(/\W+/).filter(x=>x.length>3);const atoms=knowledge.filter(k=>terms.some(t=>k.statement.toLowerCase().includes(t)));return {answer:atoms.length?`Sample cited retrieval:\n\n${atoms.map(k=>k.statement).join("\n\n")}`:"No matching approved sample knowledge. Try asking about onboarding, customer owners, or decisions.",grounded:atoms.length>0,citations:atoms.map(k=>({knowledge_id:k.id,source_id:k.source_id,source_title:k.source_title,excerpt:k.source_excerpt}))};},
    exportUrl: "", // Workspace export is intentionally absent from the demo shell.
    interviews: async()=>copy(interviews), interview: async key=>copy(find(interviews,key)),
    mcpConnections: async()=>copy(connections),
    createInterview: async payload=>{const s:InterviewSessionDetail={...payload,id:id("interview"),workspace_id:"sample-workspace",topic:payload.topic??"",person:payload.person??"",audience:payload.audience??"",outcome:payload.outcome??"",status:"active",source_id:null,created_at:date(),completed_at:null,question_count:0,response_count:0,extracted_count:0,questions:[]};interviews.unshift(s);return copy(s);},
    addQuestion: async(key,text)=>{const s=find(interviews,key);const q={id:id("question"),session_id:key,ordinal:++s.question_count,question_text:text,response_text:"",extracted:false,created_at:date()};s.questions.push(q);return copy(q);},
    submitResponse: async(key,qid,text)=>{const s=find(interviews,key);const q=find(s.questions,qid);if(!q.response_text)s.response_count++;q.response_text=text;if(!q.extracted)s.extracted_count++;q.extracted=true;capture({title:`${s.title} — response`,kind:"interview",sensitivity:"private",content:text});return copy(q);},
    completeInterview: async key=>{const s=find(interviews,key);s.status="completed";s.completed_at=date();return copy(s);},
    drafts: async()=>copy(drafts),draft:async key=>copy(find(drafts,key)),createDraft:async payload=>copy(makeDraft(payload)),
    addSection:async(key,payload)=>copy(section(find(drafts,key),payload)),deleteSection:async(key,sid)=>{const d=find(drafts,key);d.sections=d.sections.filter(s=>s.id!==sid);d.section_count=d.sections.length;d.citation_count=d.sections.reduce((n,s)=>n+s.citations.length,0);},
    assembleDraft:async payload=>{const d=makeDraft(payload);payload.knowledge_ids.forEach(key=>{const k=find(knowledge,key);section(d,{title:k.type,content:k.statement+(payload.include_excerpts?`\n\nEvidence: ${k.source_excerpt}`:""),knowledge_ids:[key]});});event("draft.assembled",d.title);return copy(d);},
  };
  return client;
}
