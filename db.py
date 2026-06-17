"""PostgreSQL data layer: user accounts, Odoo connections, chat history, file uploads."""
import os
import bcrypt
from contextlib import contextmanager
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

_pool = None


def init_pool():
    global _pool
    if _pool is not None:
        return
    _pool = pool.SimpleConnectionPool(
        1, 10,
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "cognitive_ai"),
        user=os.getenv("POSTGRES_USER", "cognitive_ai"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


@contextmanager
def get_cursor(commit=False):
    conn = _pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        _pool.putconn(conn)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS odoo_connections (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255),
    url VARCHAR(500) NOT NULL,
    db_name VARCHAR(255) NOT NULL,
    odoo_username VARCHAR(255) NOT NULL,
    odoo_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chats (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    connection_id INTEGER REFERENCES odoo_connections(id) ON DELETE SET NULL,
    title VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS file_uploads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id INTEGER REFERENCES chats(id) ON DELETE SET NULL,
    filename VARCHAR(500) NOT NULL,
    mime_type VARCHAR(255),
    size_bytes BIGINT,
    content BYTEA,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_odoo_connections_user ON odoo_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_file_uploads_user ON file_uploads(user_id);
"""


def init_db():
    init_pool()
    with get_cursor(commit=True) as cur:
        cur.execute(SCHEMA)


# ── Users / auth ──────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_user(email: str, password: str, name: str = None) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) "
            "RETURNING id, email, name, created_at",
            (email.lower().strip(), hash_password(password), name),
        )
        return cur.fetchone()


def get_user_by_email(email: str) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email.lower().strip(),))
        return cur.fetchone()


def get_user_by_id(user_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT id, email, name, created_at FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


# ── Odoo connections ─────────────────────────────────────────────────────────
def create_odoo_connection(user_id: int, name: str, url: str, db_name: str,
                            odoo_username: str, odoo_password: str) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO odoo_connections (user_id, name, url, db_name, odoo_username, odoo_password) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, name, url, db_name, odoo_username, created_at",
            (user_id, name, url, db_name, odoo_username, odoo_password),
        )
        return cur.fetchone()


def list_odoo_connections(user_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, name, url, db_name, odoo_username, is_active, created_at "
            "FROM odoo_connections WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,),
        )
        return cur.fetchall()


def delete_odoo_connection(user_id: int, connection_id: int) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM odoo_connections WHERE id = %s AND user_id = %s",
            (connection_id, user_id),
        )
        return cur.rowcount > 0


# ── Chats / messages ─────────────────────────────────────────────────────────
def create_chat(user_id: int, title: str = None, connection_id: int = None) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO chats (user_id, connection_id, title) VALUES (%s, %s, %s) "
            "RETURNING id, title, connection_id, created_at",
            (user_id, connection_id, title),
        )
        return cur.fetchone()


def list_chats(user_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, title, connection_id, created_at, updated_at "
            "FROM chats WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,),
        )
        return cur.fetchall()


def add_message(chat_id: int, role: str, content: str) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO chat_messages (chat_id, role, content) VALUES (%s, %s, %s) "
            "RETURNING id, role, content, created_at",
            (chat_id, role, content),
        )
        row = cur.fetchone()
        cur.execute("UPDATE chats SET updated_at = now() WHERE id = %s", (chat_id,))
        return row


def get_chat_messages(chat_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, role, content, created_at FROM chat_messages "
            "WHERE chat_id = %s ORDER BY created_at ASC",
            (chat_id,),
        )
        return cur.fetchall()


def delete_chat(user_id: int, chat_id: int) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
        return cur.rowcount > 0


# ── File uploads ─────────────────────────────────────────────────────────────
def create_file_upload(user_id: int, filename: str, mime_type: str, content: bytes,
                        chat_id: int = None) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO file_uploads (user_id, chat_id, filename, mime_type, size_bytes, content) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING id, filename, mime_type, size_bytes, uploaded_at",
            (user_id, chat_id, filename, mime_type, len(content), content),
        )
        return cur.fetchone()


def list_file_uploads(user_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, filename, mime_type, size_bytes, uploaded_at FROM file_uploads "
            "WHERE user_id = %s ORDER BY uploaded_at DESC",
            (user_id,),
        )
        return cur.fetchall()


def get_file_upload(user_id: int, upload_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, filename, mime_type, content FROM file_uploads "
            "WHERE id = %s AND user_id = %s",
            (upload_id, user_id),
        )
        return cur.fetchone()


def delete_file_upload(user_id: int, upload_id: int) -> bool:
    """Deletes the row (and its BYTEA content) from PostgreSQL — nothing is left behind."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM file_uploads WHERE id = %s AND user_id = %s", (upload_id, user_id))
        return cur.rowcount > 0
