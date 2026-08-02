import asyncio
from fastapi import FastAPI, UploadFile, Form, File
from contextlib import asynccontextmanager
from datetime import datetime
from service import audio_process, db_process, text_process, query_context
from database.connection import init_db_pool, close_db_pool
from service.db_process import cleanup_expired_data

async def schedule_cleanup_task():
    """서버가 켜져 있는 동안 무한히 돌며 12시간마다 DB를 청소하는 백그라운드 루프"""
    while True:
        try:
            # 12시간 대기 (초 단위 계산: 12 * 60 * 60)
            await asyncio.sleep(43200) 
            
            print("🧹 DB 정기 청소를 시작합니다...")
            result = await cleanup_expired_data()
            if result["status"] == "success":
                print(f"✅ 청소 완료: 일정 {result['deleted_schedules']}개, 루틴 {result['deleted_routines']}개 삭제됨.")
            else:
                print(f"❌ 청소 실패: {result['message']}")
                
        except asyncio.CancelledError:
            # 서버 종료 시 안전하게 백그라운드 루프 종료
            break

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 MySQL 연결 풀 초기화
    await init_db_pool()
    yield
    # 서버 종료 시 MySQL 연결 풀 안전하게 종료
    await close_db_pool()

app = FastAPI(lifespan=lifespan)

@app.post("/upload")
async def receive_data(
    data_type: str = Form(...),
    client_id: str = Form(...),
    sent_time: str = Form(...),
    file: UploadFile = File(...)
):
    # 1. 메타데이터 처리 (서버 내부 로직)
    print(f"[{data_type.upper()}] ID: {client_id} / SentAt: {sent_time}")
    
    # 2. 파일 비동기 읽기 (FastAPI 내부에서 Chunk 단위로 스트리밍 처리함)
    # await를 만나는 순간, 파일 데이터를 네트워크 소켓 버퍼에서 읽어올 때까지 
    # 이벤트 루프는 다른 클라이언트의 요청을 받으러 떠납니다. (I/O Multiplexing)
    file_contents = await file.read() 
    
    # 예시: 텍스트 유형이면 바로 디코딩해서 확인 가능
    if data_type == "text":
        text_data = file_contents.decode("utf-8")
        print(f"텍스트 내용: {text_data}")
    else:
        print(f"음성 파일 크기: {len(file_contents)} bytes")

    # 이후 나머지 처리(DB 저장, AI 모델 추론 등) 진행
    
    return {"status": "success", "message": "데이터 접수 완료"}

@app.get("/results/{client_id}")
async def get_results(client_id: str):
    # 예시: 클라이언트 ID에 따른 결과 조회 (DB 조회 등)
    # 여기서는 단순히 예시 메시지를 반환
    return {
        "client_id": client_id,
        "status": "처리 완료",
    }