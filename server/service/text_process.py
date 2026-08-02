# 텍스트 쿼리 --> DB 저장 및 검색 쿼리 변환
# analyze_text_query: 자연어쿼리의 쿼리 유형 파악 후 해당 쿼리에 해당하는 인자만을 추출하여 query_type, query_args로 db_process.py에 전달
# process_text_query: db_process.py에서 받아온 쿼리 결과를 분석하여 자연어로 변환 후 반환
import httpx
import json
from datetime import datetime
from service import db_process, query_context

OLLAMA_URL = "http://localhost:11434/api/generate"

async def process_text_query(query_context: query_context.ScheduleQueryContext) -> dict:
    if (query_context.pending_step == "classification"):
        user_id = query_context.user_id
        request_time = query_context.request_time
        user_text = query_context.user_text
        query_type = await identify_query_type(request_time, user_text)
        match (query_type):
            case 0:
                return await handle_day_query(
                    user_id, request_time, user_text
                )
            case 1:
                return await handle_range_query(
                    user_id, request_time, user_text
                )
            case 2:
                return await handle_schedule_insert(
                    user_id, request_time, user_text
                )
            case 3:
                return await handle_routine_insert(
                    user_id, request_time, user_text
                )
            case 4:
                return await handle_schedule_update(
                    user_id, request_time, user_text
                )
            case 5:
                return await handle_routine_update(
                    user_id, request_time, user_text
                )
            case 6:
                return await handle_schedule_delete(
                    user_id, request_time, user_text
                )
            case 7:
                return await handle_routine_delete(
                    user_id, request_time, user_text
                )
            case _:
                # 오류
                pass
    else:
        return await resume_processing(query_context)

async def identify_query_type(request_time: str, user_text: str) -> int:
    prompt = (f"""
    당신은 일정 관리 요청 분류기다.
    기준 시각:
    {request_time}

    아래 자연어 요청을 0~7 중 하나로 분류하라.

    0: 특정 날짜 조회
    1: 특정 기간 조회
    2: 일정 삽입
    3: 루틴 삽입
    4: 일정 수정
    5: 루틴 수정
    6: 일정 삭제
    7: 루틴 삭제

    반드시 JSON만 반환하라.

    출력 예시:
    {{"query_type": 0}}

    사용자 요청:
    {user_text}
    """
    )

    payload = {
        "model": "qwen2.5-coder:7b",
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(OLLAMA_URL, json=payload, timeout=30.0)
            if response.status_code == 200:
                result_str = response.json().get("response", "{}")
                query_type = int(json.loads(result_str).get("query_type", -1))
                if query_type not in range(8):
                    return -1
                return query_type
            print(f"Ollama 에러: {response.status_code}")
            return -1
    except Exception as e:
        print(f"AI 라우팅 실패: {str(e)}")
        return -1

async def resume_processing(query_context: query_context.ScheduleQueryContext):
    # query_context.status에 따라 이전 상태를 기반으로 처리 재개
    if query_context.status == "waiting_parameters":
        # 필요한 인자 수집 후 DB 조회
        pass
    elif query_context.status == "waiting_targeting":
        # 타겟팅 후 DB 조회
        pass
    elif query_context.status == "waiting_collision_check":
        # 충돌 검사 후 DB 삽입/수정/삭제
        pass
    else:
        # 완료 또는 실패 상태 처리
        pass

async def create_final_response(db_result: dict, is_success: bool, query_type: int) -> str:
    if (is_success):
        pass
    else:
        pass
    return

async def handle_day_query(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 필수 인자(재질문)
    # 3. 조회
    # 4. 조회 성공 or 실패 답변 반환
    return

async def handle_range_query(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 필수 인자(재짊문)
    # 3. 조회
    # 4. 조회 성공 or 실패 답변 반환
    return

async def handle_schedule_insert(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 필수 인자(재질문)
    # 3. 충돌검사
    # 4. 삽입 성공 or 충돌 답변 반환
    return

async def handle_routine_insert(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 필수 인자(재질문)
    # 3. 충돌검사
    # 4. 삽입 성공 or 충돌 답변 반환
    return

async def handle_schedule_update(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 타겟팅(재질문)
    # 3. 튜플 존재 확인
    # 4. 수정튜플 충돌검사
    # 5. 수정 성공 or 실패 답변 반환
    return

async def handle_routine_update(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 타겟팅(재질문)
    # 3. 튜플 존재 확인
    # 4. 수정튜플 충돌검사
    # 5. 수정 성공 or 실패 답변 반환
    return

async def handle_schedule_delete(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 타겟팅(재질문)
    # 3. 튜플 존재 확인
    # 4. 삭제 성공 or 실패 답변 반환
    return

async def handle_routine_delete(user_id: str, request_time: str, user_text: str):
    # 1. 주어진 쿼리 1차 분석
    # 2. 타겟팅(재질문)
    # 3. 튜플 존재 확인
    # 4. 삭제 성공 or 실패 답변 반환
    return

def check_arg(query_type: int, curr_arg: dict, required_arg: dict) -> dict:
    return