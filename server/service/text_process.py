# 텍스트 쿼리 --> DB 저장 및 검색 쿼리 변환
# analyze_text_query: 자연어쿼리의 쿼리 유형 파악 후 해당 쿼리에 해당하는 인자만을 추출하여 query_type, query_args로 db_process.py에 전달
# process_text_query: db_process.py에서 받아온 쿼리 결과를 분석하여 자연어로 변환 후 반환
import httpx
import json
from datetime import datetime
from service import db_process, query_context
from service.query_context import next_step_mapping, parameter_templates, mandatory_parameters, optional_parameters, QUERY_PARAMETER_SPECS
from copy import deepcopy

OLLAMA_URL = "http://localhost:11434/api/generate"

async def process_text_query(query_context: query_context.ScheduleQueryContext) -> query_context.ScheduleQueryContext:
    if (query_context.pending_step == "classification"):
        query_type = await identify_query_type(query_context.request_time, query_context.user_text)
        if query_type not in range(8):
            query_context.pending_step = "failed"
            query_context.response_message = "❌ 쿼리 유형을 파악할 수 없습니다. 다시 시도해주세요."
            return query_context
        query_context.query_type = query_type # query_context에 query_type 저장
        query_context.current_parameters = deepcopy(parameter_templates.get(query_type)) # query_context에 current_parameters 초기화
        query_context.pending_step = deepcopy(next_step_mapping.get(query_type)) # query_context에 pending_step 초기화
    return await core_processing(query_context)

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

async def core_processing(query_context: query_context.ScheduleQueryContext):
    query_type = query_context.query_type
    match (query_type):
        case 0:
            return await handle_day_query(query_context)
        case 1:
            return await handle_range_query(query_context)
        case 2:
            return await handle_schedule_insert(query_context)
        case 3:
            return await handle_routine_insert(query_context)
        case 4:
            return await handle_schedule_update(query_context)
        case 5:
            return await handle_routine_update(query_context)
        case 6:
            return await handle_schedule_delete(query_context)
        case 7:
            return await handle_routine_delete(query_context)
        case _:
            # 오류
            pass

# 그냥 누락된 인자 체크(인자 추출용)
def list_to_extract(query_type: int, curr_arg: dict) -> list[str]:
    missing_args = []
    for i in mandatory_parameters.get(query_type):
        if (curr_arg.get(i) is None):
            missing_args.append(i)
    for i in optional_parameters.get(query_type):
        if (curr_arg.get(i) is None):
            missing_args.append(i)
    return missing_args

# 필수 인자 없을시 누락된 인자 반환(재질문용)
def check_arg(query_type: int, curr_arg: dict) -> list[str]:
    missing_args = []
    for i in mandatory_parameters.get(query_type):
        if (curr_arg.get(i) is None):
            missing_args.append(i)
    if (len(missing_args) > 0):
        for i in optional_parameters.get(query_type):
                if (curr_arg.get(i) is None):
                    missing_args.append(i)
    return missing_args

async def make_response_message(query_type: int, required_args: list[str]) -> str:
    if (query_type == 0):
        return f"{', '.join(required_args)}이(가) 누락되었습니다. 특정 날짜를 알려주세요."
    elif (query_type == 1):
        return f"{', '.join(required_args)}이(가) 누락되었습니다. 시작 날짜와 종료 날짜를 알려주세요."
    elif (query_type == 2):
        return f"{', '.join(required_args)}이(가) 누락되었습니다. 일정 삽입에 필요한 정보를 알려주세요."
    elif (query_type == 3):
        return f"{', '.join(required_args)}이(가) 누락되었습니다. 루틴 삽입에 필요한 정보를 알려주세요."
    elif (query_type == 4):
        return f"{', '.join(required_args)}이(가) 누락되었습니다. 일정 수정에 필요한 정보를 알려주세요."    
    elif (query_type == 5):
        return f"{', '.join(required_args)}이(가) 누락되었습니다. 루틴 수정에 필요한 정보를 알려주세요."

async def extract_parameters_from_text(query_type: int, user_text: str, required_args: list[str], request_time: str, current_parameters: dict):
    # 1. 필요 인자 추출
    # 2. 현재 있는 인자 중 없는 필요 인자들을 current_parameters에 추가
    return

async def request_date_info() -> str:
    return

async def request_weekday_info() -> str:
    return

async def targeting() -> str:
    target_id = None
    return

async def create_final_response(db_result: dict, query_type: int) -> str:
    if db_result.get("status") != "success":
        return db_result.get(
            "message",
            "일정을 조회하는 중 오류가 발생했습니다.",
        )

    timeline = db_result.get("timeline", [])
    target_date = db_result.get("target_date")

    if not timeline:
        return f"{target_date}에는 등록된 일정이나 루틴이 없습니다."

    # timeline 포맷팅

async def handle_day_query(query_context: query_context.ScheduleQueryContext):
    user_id = query_context.user_id
    query_type = query_context.query_type
    user_text = query_context.user_text
    request_time = query_context.request_time
    # 종료상태에서 재진입 시 바로 반환
    if query_context.pending_step == "done":
        return query_context
    # 1. 필수 인자(재질문)
    if (query_context.pending_step == "waiting_parameters"):
        # 첫번째로 필수 인자 및 필요인자 체크
        fields_to_extract = list_to_extract(query_type, query_context.current_parameters)
        # 2차 분석 단계에서 필요한 인자 추출
        await extract_parameters_from_text(query_type, user_text, fields_to_extract, request_time, query_context.current_parameters)
        missing_args = check_arg(query_type, query_context.current_parameters)
        if (len(missing_args) > 0):
            query_context.response_message = await make_response_message(query_context.query_type, missing_args)
            return query_context
        # 2. DB 조회
        else:
            db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    # 3. 조회 성공 or 실패 답변 반환
    query_context.response_message = await create_final_response(db_result, query_context.query_type)
    query_context.pending_step = "done"
    return query_context

async def handle_range_query(query_context: query_context.ScheduleQueryContext):
    # 1. 필수 인자(재질문)
    if (query_context.pending_step == "waiting_parameters"):
        # 첫번째로 필수 인자 및 필요인자 체크
        # 2차 분석 단계에서 필요한 인자 추출
        # 예: 시작 날짜, 종료 날짜, 일정 종류 등
        pass
    # 2. DB 조회
    # 3. 조회 성공 or 실패 답변 반환
    if (query_context.pending_step == "completed"):
        pass
    if (query_context.pending_step == "failed"):
        pass
    return

async def handle_schedule_insert(query_context: query_context.ScheduleQueryContext):
    # 1. 필수 인자(재질문)
    if (query_context.pending_step == "waiting_parameters"):
        # 첫번째로 필수 인자 및 필요인자 체크
        # 2차 분석 단계에서 필요한 인자 추출
        # 예: 시작 날짜, 종료 날짜, 일정 종류 등
        # 2. 충돌검사 후에 다음단계
        pass
    if (query_context.pending_step == "waiting_collision_decision"):
        # 충돌검사의 결과에 대한 사용자의 선택에 따른 처리
        # 예: 충돌 무시하고 삽입, 충돌 해결 후 삽입, 삽입 취소 등
        pass
    # 3. 삽입 성공 or 충돌 답변 반환
    if (query_context.pending_step == "completed"):
        pass
    if (query_context.pending_step == "failed"):
        pass
    return

async def handle_routine_insert(query_context: query_context.ScheduleQueryContext):
    # 1. 필수 인자(재질문)
    if (query_context.pending_step == "waiting_parameters"):
        # 첫번째로 필수 인자 및 필요인자 체크
        # 2차 분석 단계에서 필요한 인자 추출
        # 예: 시작 날짜, 종료 날짜, 일정 종류 등
        # 2. 충돌검사 후에 다음단계
        pass
    if (query_context.pending_step == "waiting_collision_decision"):
        # 충돌검사의 결과에 대한 사용자의 선택에 따른 처리
        # 예: 충돌 무시하고 삽입, 충돌 해결 후 삽입, 삽입 취소 등
        pass
    # 3. 삽입 성공 or 충돌 답변 반환
    if (query_context.pending_step == "completed"):
        pass
    if (query_context.pending_step == "failed"):
        pass
    return

async def handle_schedule_update(query_context: query_context.ScheduleQueryContext):
    # 1-1. 타겟팅(현재기준 일정 존재하는 날짜 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_day"):
        pass
    # 1-2. 타겟팅(해당 날짜의 일정 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        pass
    # 2. 인자 확인
    if (query_context.pending_step == "waiting_parameters"):
        pass
    # 3. 수정튜플 충돌검사
    if (query_context.pending_step == "waiting_collision_decision"):
        pass
    # 4. 수정 성공 or 실패 답변 반환
    if (query_context.pending_step == "completed"):
        pass
    if (query_context.pending_step == "failed"):
        pass
    return

async def handle_routine_update(query_context: query_context.ScheduleQueryContext):
    # 1-1. 타겟팅(유효한 루틴 존재하는 요일 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_weekday"):
        pass
    # 1-2. 타겟팅(해당 요일의 루틴 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        pass
    # 2. 인자 확인
    if (query_context.pending_step == "waiting_parameters"):
        pass
    # 3. 수정튜플 충돌검사
    if (query_context.pending_step == "waiting_collision_decision"):
        pass
    # 4. 수정 성공 or 실패 답변 반환
    if (query_context.pending_step == "completed"):
        pass
    if (query_context.pending_step == "failed"):
        pass
    return

async def handle_schedule_delete(query_context: query_context.ScheduleQueryContext):
    # 1-1. 타겟팅(현재기준 일정 존재하는 날짜 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_day"):
        pass
    # 1-2. 타겟팅(해당 날짜의 일정 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        pass
    # 2. 삭제
    # 3. 삭제 성공 or 실패 답변 반환
    if (query_context.pending_step == "completed"):
        pass
    if (query_context.pending_step == "failed"):
        pass
    return

async def handle_routine_delete(query_context: query_context.ScheduleQueryContext):
    # 1-1. 타겟팅(유효한 루틴 존재하는 요일 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_weekday"):
        pass
    # 1-2. 타겟팅(해당 요일의 루틴 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        pass
    # 2. 삭제
    # 3. 삭제 성공 or 실패 답변 반환
    if (query_context.pending_step == "completed"):
        pass
    if (query_context.pending_step == "failed"):
        pass
    return
