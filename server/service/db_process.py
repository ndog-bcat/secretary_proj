# audio_process.py/text_process.py에서 받아온 DB 쿼리 결과를 처리하는 서비스
from database.connection import db_pool

async def process_db_query(query_type: int, query_args: dict) -> dict:
    async with db_pool.acquire() as conn:
        # 여기에 실제 DB 쿼리 로직을 구현
        pass