import httpx
import asyncio
from datetime import datetime, timezone
from api import network
from ui import login_view, upload_view, result_view

SERVER_URL = "http://127.0.0.1:8000"

async def send_data():
    url = f"{SERVER_URL}/upload"
    
    # 1. 보낼 데이터 세팅
    data = {
        "data_type": "audio",  # 또는 "text"
        "client_id": "user_12345",
        "sent_time": datetime.now(timezone.utc).isoformat()
    }
    
    # 2. 파일 세팅 (실제 파일 경로 또는 바이너리 데이터)
    # 여기서는 예시로 임의의 바이너리 데이터를 파일처럼 보냅니다.
    files = {
        "file": ("sample_audio.mp3", b"RAW_AUDIO_BYTES_DATA_HERE", "audio/mpeg")
    }
    
    # 3. 비동기 클라이언트로 전송
    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=data, files=files)
        print(response.json())

async def get_result(ID):
    url = f"{SERVER_URL}/results/{ID}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        print(response.json())

# 실행
asyncio.run(send_data())