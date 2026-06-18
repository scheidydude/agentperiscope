"""Script to create a minimal OpenCode fixture SQLite database for tests."""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "opencode_fixture.db"

conn = sqlite3.connect(str(DB))
conn.executescript("""
CREATE TABLE IF NOT EXISTS project (
    id TEXT PRIMARY KEY, worktree TEXT NOT NULL, name TEXT,
    time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, sandboxes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, slug TEXT NOT NULL,
    directory TEXT NOT NULL, title TEXT NOT NULL, version TEXT NOT NULL,
    model TEXT, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
    cost REAL DEFAULT 0, tokens_input INTEGER DEFAULT 0, tokens_output INTEGER DEFAULT 0,
    tokens_cache_read INTEGER DEFAULT 0, tokens_cache_write INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS message (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
    time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS part (
    id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
    time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
);
""")

conn.execute(
    "INSERT INTO project VALUES (?,?,?,?,?,?)",
    ("proj_1", "/home/user/project", "test-project", 1748764800000, 1748764800000, "[]"),
)
conn.execute(
    "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("ses_test001", "proj_1", "test-session", "/home/user/project", "Test session", "1",
     json.dumps({"id": "gpt-4o", "providerID": "openai"}), 1748764800000, 1748764810000,
     0.001, 100, 50, 0, 0),
)
conn.execute(
    "INSERT INTO message VALUES (?,?,?,?,?)",
    ("msg_test001", "ses_test001", 1748764801000, 1748764809000,
     json.dumps({"role": "assistant", "agent": "build", "finish": "stop",
                 "tokens": {"total": 150, "input": 100, "output": 50,
                            "cache": {"write": 0, "read": 0}},
                 "modelID": "gpt-4o"})),
)
conn.execute(
    "INSERT INTO part VALUES (?,?,?,?,?,?)",
    ("prt_test001", "msg_test001", "ses_test001", 1748764802000, 1748764803000,
     json.dumps({"type": "text", "text": "Hello! I can help you with that.",
                 "time": {"start": 1748764802000, "end": 1748764803000}})),
)
conn.execute(
    "INSERT INTO part VALUES (?,?,?,?,?,?)",
    ("prt_test002", "msg_test001", "ses_test001", 1748764804000, 1748764808000,
     json.dumps({"type": "tool", "tool": "read", "callID": "call_oc_001",
                 "state": {"status": "completed",
                           "input": {"filePath": "/home/user/project/README.md"},
                           "output": "# Project\nThis is a test."}})),
)
conn.commit()
conn.close()
print(f"Created {DB}")
