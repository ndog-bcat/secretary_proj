import aiomysql
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": os.getenv("DB_PASSWORD"),
    "db": "meeting_DB",
    "autocommit": True
}

db_pool = None

#서버가 켜질 때 MySQL 연결 풀을 초기화하는 함수
async def init_db_pool():
    global db_pool
    db_pool = await aiomysql.create_pool(**DB_CONFIG, minsize=5, maxsize=10)
    print("🚀 MySQL Connection Pool 생성 완료!")

#서버가 종료될 때 MySQL 연결 풀을 안전하게 종료하는 함수
async def close_db_pool():
    global db_pool
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()
        print("🔒 MySQL Connection Pool 안전하게 종료됨")