# arkiv

Universal personal data format. JSONL in, SQL out, MCP to LLMs.

## The Format

Every record is a JSON object. All fields optional.

```jsonl
{"mimetype": "text/plain", "content": "I think the key insight is...", "uri": "https://chatgpt.com/c/abc", "timestamp": "2023-05-14T10:30:00Z", "metadata": {"role": "user", "conversation_id": "abc"}}
{"mimetype": "audio/wav", "uri": "file://media/podcast.wav", "timestamp": "2024-01-15", "metadata": {"transcript": "Welcome to...", "duration": 45.2}}
{"mimetype": "image/jpeg", "uri": "file://media/photo.jpg", "metadata": {"caption": "My talk at MIT"}}
```

## The Stack

```
JSONL files (canonical, portable, human-readable)
    ↓ arkiv import
SQLite database (queryable, efficient, standard SQL)
    ↓ arkiv mcp
MCP server (3 tools → any LLM)
    ↑ arkiv export
```

## Quick Start

```bash
pip install arkiv

# Import JSONL to SQLite
arkiv import conversations.jsonl --db archive.db

# Query
arkiv query archive.db "SELECT content FROM records WHERE metadata->>'role' = 'user' LIMIT 5"

# Export with temporal slicing
arkiv export archive.db --output 2024/ --since 2024-01-01 --until 2024-12-31

# Serve to LLMs via MCP
arkiv mcp archive.db
```

## MCP Tools

Read-only by default. Start with `arkiv mcp --writable db` to enable the write tool.

| Tool | Description | Mode |
|------|-------------|------|
| `get_manifest()` | What collections exist, their descriptions and schemas | read-only |
| `get_schema(collection?)` | What metadata keys can be queried | read-only |
| `sql_query(query)` | Run read-only SQL | read-only |
| `write_record(...)` | Append a single record to a collection | writable |

## Why

- Your data lives in silos (ChatGPT, email, bookmarks, photos, voice memos)
- Source toolkits (memex, mtk, btk, ptk, ebk) export it as JSONL
- arkiv gives you one format, one database, one query interface
- Any LLM can query it via MCP
- JSONL is human-readable and durable. SQLite is the most deployed database in history.

## Spec and philosophy

- [SPEC.md](SPEC.md): full technical specification
- [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md): why arkiv exists and how it composes with [longecho](https://github.com/queelius/longecho)
