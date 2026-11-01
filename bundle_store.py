"""Small durable reference store; ownership is checked before resolving a draft."""

import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3


class BundleStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE IF NOT EXISTS bundles (id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS bundle_price_history (id TEXT PRIMARY KEY, total REAL NOT NULL)")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, bundle, owner, price_total=None):
        with self.connect() as connection:
            connection.execute("INSERT INTO bundles (id, owner, status, data) VALUES (?, ?, ?, ?)",
                               (bundle.id, owner, bundle.status, json.dumps(bundle.references())))
            if price_total is not None:
                connection.execute("INSERT OR REPLACE INTO bundle_price_history (id, total) VALUES (?, ?)", (bundle.id, price_total))

    def get(self, identifier, owner):
        if not self.path.exists():
            return None
        with self.connect() as connection:
            row = connection.execute("SELECT data FROM bundles WHERE id = ? AND (owner = ? OR status = 'published')", (identifier, owner)).fetchone()
        return json.loads(row[0]) if row else None

    def published(self):
        if not self.path.exists():
            return []
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM bundles WHERE status = 'published' ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def owned_drafts(self, owner):
        if not self.path.exists() or not owner:
            return []
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM bundles WHERE owner = ? AND status = 'draft' ORDER BY rowid DESC", (owner,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def price_total(self, identifier):
        if not self.path.exists():
            return None
        with self.connect() as connection:
            row = connection.execute("SELECT total FROM bundle_price_history WHERE id = ?", (identifier,)).fetchone()
        return row[0] if row else None

    def update_draft(self, bundle, owner, price_total=None):
        if not self.path.exists() or not owner:
            return False
        with self.connect() as connection:
            result = connection.execute("UPDATE bundles SET data = ? WHERE id = ? AND owner = ? AND status = 'draft'", (json.dumps(bundle.references()), bundle.id, owner))
            if result.rowcount == 1 and price_total is not None:
                connection.execute("INSERT OR REPLACE INTO bundle_price_history (id, total) VALUES (?, ?)", (bundle.id, price_total))
            return result.rowcount == 1
