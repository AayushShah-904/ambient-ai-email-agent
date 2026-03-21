"""
Auto-creates all required database tables if they don't already exist.
Called once during application startup.
"""

CREATE_USER_TOKENS_TABLE = """
CREATE TABLE IF NOT EXISTS user_tokens (
    user_id TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_uri TEXT,
    client_id TEXT,
    client_secret TEXT,
    scopes TEXT,
    expiry TIMESTAMPTZ
);
"""

ALL_TABLES = [
    CREATE_USER_TOKENS_TABLE,
]


async def init_db(pool):
    """Run all CREATE TABLE IF NOT EXISTS statements using a connection from the pool."""
    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        for sql in ALL_TABLES:
            await conn.execute(sql)
    print("Database tables verified/created.")
