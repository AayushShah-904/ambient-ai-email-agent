from fastapi import Request

async def get_db(request: Request):
    # Retrieve the pool from the lifespan state
    pool = request.state.db_pool
    async with pool.connection() as conn:
        yield conn