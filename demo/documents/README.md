# Demo Financial Documents

Sample financial reports for demonstrating the RAG system.

## Documents

| File | Description | Source |
|------|-------------|--------|
| `Tesla_sample.pdf` | Tesla Q2 2025 Quarterly Report | Public SEC Filing |
| `NVIDIA_sample.pdf` | NVIDIA Q1 FY2027 Quarterly Report | Public SEC Filing |
| `Apple_sample.pdf` | Apple Q2 2026 Quarterly Report | Public SEC Filing |

## Usage

These documents are automatically loaded into the demo knowledge base on first startup:

```bash
docker compose up -d
```

The demo initialization script processes these PDFs through the RAG pipeline:
1. Text extraction
2. Semantic chunking
3. Embedding generation
4. ChromaDB vector storage

## Adding More Documents

Place additional PDF files in this directory. They will be processed on the next demo initialization.

## License

These documents are sourced from publicly available SEC filings and are used for demonstration purposes only.