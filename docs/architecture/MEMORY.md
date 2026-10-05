# Memory & Knowledge

Memory is separated by kind; not everything is a vector.

| Kind | Storage | Use |
|---|---|---|
| Company memory (identity, mission, brand, policy, product, business rules) | `company_memory` (relational) | Always returned by `search_company_knowledge` |
| Long-form documents | `documents` + `document_chunks.embedding vector(1536)` (HNSW, cosine) | Similarity search scoped by organization and embedding model |
| CEO preferences | `organization_preferences` (organization or agent scope) | Injected into agent system prompts |
| Feedback | `agent_feedback` | Reviewed by the CEO, then promoted or dismissed |
| Operational data | relational tables (objectives, tasks, artifacts) | Queried directly |
| Project memory | documents and artifacts linked to a project or objective | Project page and retrieval |

## Feedback to preference

Comments never become permanent memory automatically. The CEO adds feedback on an artifact
("Too corporate. Make it technical and concise."), then explicitly promotes it to an organization-wide or
agent-specific preference in **Knowledge → Preferences & feedback**.

## Untrusted content

Documents are untrusted by default (uploads, external text). Retrieved chunks are wrapped in
`<untrusted_content>` and the platform rules tell agents to treat them as data. Tool permissions never depend
on the model obeying this.

## Embeddings

The organization's AI provider supplies embeddings (`text-embedding-3-small`, 1536 dimensions), or the
deterministic local hashing model (`local-hash-1536`) works offline. Each chunk records its embedding model and
search only compares vectors from the same model.
