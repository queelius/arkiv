# arkiv

Universal personal data format. JSONL in, SQL out, MCP to LLMs.

## The Format

Every record is a JSON object. All fields optional.

```jsonl
{"mimetype": "text/plain", "content": "I think the key insight is...", "url": "https://chatgpt.com/c/abc", "timestamp": "2023-05-14T10:30:00Z", "metadata": {"role": "user", "conversation_id": "abc"}}
{"mimetype": "audio/wav", "url": "file://media/podcast.wav", "timestamp": "2024-01-15", "metadata": {"transcript": "Welcome to...", "duration": 45.2}}
{"mimetype": "image/jpeg", "url": "file://media/photo.jpg", "metadata": {"caption": "My talk at MIT"}}
```

## The Stack

```
JSONL files (canonical, portable, human-readable)
    ↓ arkiv import
SQLite database (queryable, efficient, standard SQL)
    ↓ arkiv serve
MCP server (3 tools → any LLM)
```

## Quick Start

```bash
pip install arkiv

# Import JSONL to SQLite
arkiv import conversations.jsonl --db archive.db

# Query
arkiv query archive.db "SELECT content FROM records WHERE metadata->>'role' = 'user' LIMIT 5"

# Serve to LLMs via MCP
arkiv serve archive.db
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_manifest()` | What collections exist, their descriptions and schemas |
| `get_schema(collection?)` | What metadata keys can be queried |
| `sql_query(query)` | Run read-only SQL |

## Why

- Your data lives in silos (ChatGPT, email, bookmarks, photos, voice memos)
- Source toolkits (ctk, mtk, btk, ptk, ebk) export it as JSONL
- arkiv gives you one format, one database, one query interface
- Any LLM can query it via MCP
- JSONL is human-readable and durable. SQLite is the most deployed database in history.

## Spec

See [SPEC.md](SPEC.md) for the full technical specification.
