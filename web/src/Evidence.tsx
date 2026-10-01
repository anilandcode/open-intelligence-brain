export function EvidenceCitation({index, title, excerpt, knowledgeId, href}: {index: number; title: string; excerpt: string; knowledgeId?: string; href?: string}) {
  return <details className="evidence-citation"><summary><span>{index}</span>{title}</summary><blockquote>{excerpt}</blockquote>{knowledgeId && <code>{knowledgeId}</code>}{href && <a href={href}>Inspect original source</a>}</details>;
}
