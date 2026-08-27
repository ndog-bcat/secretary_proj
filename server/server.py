import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from api_schemas import TextQueryRequest, TextQueryResponse
from database.connection import init_db_pool, close_db_pool
from service import text_process, query_context
from service.db_process import cleanup_expired_data

#디버그용
from dataclasses import asdict
from fastapi.encoders import jsonable_encoder

# "사용자 아이디": "사용자 대화 맥락 구조체" 형식의 딕셔너리
query_contexts: dict[str, query_context.ScheduleQueryContext] = {}

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
    await init_db_pool()
    cleanup_task = asyncio.create_task(schedule_cleanup_task())

    try:
        yield
    finally:
        cleanup_task.cancel()
        await cleanup_task
        await close_db_pool()

app = FastAPI(lifespan=lifespan)

@app.post("/query/text", response_model=TextQueryResponse)
async def process_text_request(request: TextQueryRequest):
    request_time = request.request_time.strftime("%Y-%m-%d %H:%M:%S")

    context = query_contexts.get(request.user_id)

    # 딕셔너리 조회 후 대화 기록이 없다면 새로 생성
    if context is None:
        context = query_context.ScheduleQueryContext(
            user_id=request.user_id,
            request_time=request_time,
            user_text=request.user_text,
        )
    else:
        # 이미 있다면 사용자 반응만 업데이트
        context.user_text = request.user_text

    result = await text_process.process_text_query(context)

    if result.pending_step in {"done", "failed"}:
        query_contexts.pop(request.user_id, None)
    else:
        query_contexts[request.user_id] = result

    return TextQueryResponse(message=result.response_message or "요청을 처리하지 못했습니다.")

# 디버그용
@app.get("/debug/contexts")
async def get_query_contexts():
    return {
        "count": len(query_contexts),
        "contexts": jsonable_encoder({
            user_id: asdict(context)
            for user_id, context in query_contexts.items()
        }),
    }