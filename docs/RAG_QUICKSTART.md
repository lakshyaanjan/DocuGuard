# Snapshot organisation and RAG quickstart

DocuGuard's organisation stage creates a versioned corpus snapshot. Its RAG command then retrieves relevant raw chunks from that snapshot and, when an LLM is configured, generates an answer grounded in those chunks.

## 1. Organise a project

From the DocuGuard repository root:

~~~powershell
python -m docuguard.ingestion --repo . --project-name DocuGuard
~~~

The command writes a versioned snapshot below:

~~~text
.docuguard/index/<project-id>/<snapshot-id>/
  manifest.json
  files.jsonl
  chunks.jsonl
  summaries.jsonl
  project_summary.json
~~~

The snapshot stores file/source metadata, code and documentation chunks, line ranges, content hashes, symbols/sections, and extractive file/section summaries. Raw chunks remain available as the source of truth. Secret-like files and common dependency/build directories are skipped by the ingestion policy.

## 2. Ask a question using the snapshot

~~~powershell
python -m docuguard.rag --index .docuguard/index --query "Where is the default application port configured?"
~~~

The index root is accepted directly; DocuGuard selects the newest snapshot under it. You can also pass the exact snapshot directory printed by the ingestion command.

The retrieval stage uses BM25 lexical ranking by default. It searches raw chunks and uses the file/section summaries to help navigate to relevant source chunks. Returned citations are validated against the retrieved chunk IDs and display original paths and line ranges.

## 3. Enable grounded answer generation

Set an API key and model configuration in the current PowerShell session. For Google AI Studio, see the Gemini setup in the main README. Then run:

~~~powershell
python -m docuguard.rag --index .docuguard/index --query "Explain the configuration options for the server." --llm-mode required
~~~

The model receives the question, the retrieved raw evidence, and short navigation summaries. It must return an answer and the IDs of the evidence chunks supporting it. DocuGuard discards citations that are not among the retrieved chunk IDs.

For a fast/offline retrieval demonstration, use:

~~~powershell
python -m docuguard.rag --index .docuguard/index --query "Where is the default application port configured?" --llm-mode off
~~~

Offline mode intentionally shows retrieved evidence rather than pretending an LLM generated an answer. In auto mode, DocuGuard attempts generation when a key is configured and clearly labels retrieval-only fallback if the model call fails.

## Retrieval options

- --top-k 5 controls the number of raw evidence chunks returned (1-12).
- --no-embeddings forces BM25-only retrieval.
- Set DOCUGUARD_USE_EMBEDDINGS=true and configure an embeddings model to enable hybrid BM25/vector ranking. Vectors are cached locally by model and content hash.
- --json prints the answer, snapshot metadata, retrieved summaries, and validated provenance citations as JSON.

## Scope and limitations

This is a local snapshot-backed RAG prototype, not a hosted vector database. Ingestion currently rescans files into a new versioned snapshot rather than performing incremental indexing. The default path uses lexical retrieval; embeddings are optional and depend on provider availability. The LLM must answer from retrieved evidence, but generated answers still require human review for important decisions.