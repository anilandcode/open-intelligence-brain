import { describe, expect, it, vi } from "vitest";
import { createDemoClient } from "./demo";

describe("isolated demo workspace", () => {
  it("captures, approves and retrieves cited knowledge without a network request", async () => {
    const network = vi.spyOn(globalThis, "fetch");
    const demo = createDemoClient();
    const original = "Prefer clear handoff ownership. Retain the original customer evidence.";
    const s = await demo.createSource({title:"Sample handoff",kind:"note",sensitivity:"private",content:original});
    const p = (await demo.proposals()).find(p=>p.source_id===s.id)!;
    expect((await demo.knowledge()).some(k=>k.source_id===s.id)).toBe(false);
    const k = await demo.approveProposal(p.id,p.statement,p.rationale);
    const result = await demo.chat("handoff ownership");
    expect(result.citations).toContainEqual({knowledge_id:k.id,source_id:s.id,source_title:s.title,excerpt:original});
    await expect(demo.approveProposal(p.id,p.statement,p.rationale)).rejects.toThrow("already been reviewed");
    expect(network).not.toHaveBeenCalled();network.mockRestore();
  });
  it("retains source versions and approved wording history separately", async()=>{
    const demo=createDemoClient();const [s]=await demo.sources();const [k]=await demo.knowledge();
    await demo.addSourceVersion(s.id,"A changed original with sufficient material for a second source version.","Updated interview");
    const updatedProposal = (await demo.proposals()).find(p=>p.source_id===s.id && p.statement.startsWith("A changed"))!;
    const approved = await demo.approveProposal(updatedProposal.id,updatedProposal.statement,updatedProposal.rationale);
    const approvedHistory = await demo.knowledgeRevisions(approved.id);
    const history=await demo.sourceVersions(s.id);expect(approvedHistory[0].source_version_id).toBe(history[0].id);expect(history).toHaveLength(2);expect(history[1].content).toBe(s.content);
    expect((await demo.knowledge()).find(x=>x.id===k.id)?.source_excerpt).toBe(k.source_excerpt);
    await demo.supersedeKnowledge(k.id,"A revised approved statement",k.rationale,"Clarify wording");
    const revisions=await demo.knowledgeRevisions(k.id);expect(revisions).toHaveLength(2);expect(revisions[1].statement).toBe(k.statement);
    expect((await createDemoClient().sources())).toHaveLength(2);
  });
  it("assembles a cited draft from approved sample records",async()=>{
    const demo=createDemoClient();const atoms=await demo.knowledge();const draft=await demo.assembleDraft({title:"Sample brief",knowledge_ids:atoms.map(k=>k.id),include_excerpts:true});
    expect(draft.citation_count).toBe(2);expect(draft.sections[0].citations[0].knowledge_id).toBe(atoms[0].id);
    expect(draft.sections[0].content).toContain(atoms[0].source_excerpt);
  });
});
