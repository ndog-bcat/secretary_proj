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
        query_type = await identify_query_type(query_context.user_text)
        if query_type not in range(8):
            query_context.pending_step = "failed"
            query_context.response_message = "❌ 쿼리 유형을 파악할 수 없습니다. 다시 시도해주세요."
            return query_context
        query_context.query_type = query_type # query_context에 query_type 저장
        query_context.current_parameters = deepcopy(parameter_templates.get(query_type)) # query_context에 current_parameters 초기화
        query_context.pending_step = deepcopy(next_step_mapping.get(query_type)) # query_context에 pending_step 초기화
    return await core_processing(query_context)

async def identify_query_type(user_text: str) -> int:
    prompt = (f"""
    역할: 사용자의 일정 관리 요청을 정확히 한 유형으로 분류한다.

    유형:
    0 = 하루의 일정 조회
    1 = 여러 날짜 또는 기간의 일정 조회
    2 = 한 번만 발생하는 일정 추가
    3 = 매일, 매주, 특정 요일에 반복되는 루틴 추가
    4 = 한 번만 발생하는 일정 수정
    5 = 반복되는 루틴 수정
    6 = 한 번만 발생하는 일정 삭제
    7 = 반복되는 루틴 삭제

    판단 규칙:
    - 보여줘, 알려줘, 뭐 있어는 조회다.
    - 추가해줘, 등록해줘, 잡아줘는 추가다.
    - 바꿔줘, 옮겨줘, 수정해줘는 수정이다.
    - 삭제해줘, 취소해줘, 없애줘는 삭제다.
    - 매일, 매주, 평일, 주말, 요일 반복이 명시되면 루틴이다.
    - 단순히 "월요일 일정"처럼 날짜를 요일로 표현한 것은 루틴이 아니다.
    - 오늘, 내일, 특정 날짜처럼 하루만 조회하면 0이다.
    - 이번 주, 다음 주, 며칠간처럼 기간을 조회하면 1이다.

    예시:
    "내일 일정 보여줘" -> {{"query_type": 0}}
    "이번 주 일정 알려줘" -> {{"query_type": 1}}
    "내일 3시에 회의 추가해줘" -> {{"query_type": 2}}
    "매주 월수금 9시에 운동 추가해줘" -> {{"query_type": 3}}
    "내일 회의를 4시로 바꿔줘" -> {{"query_type": 4}}
    "월수금 운동 루틴을 화목으로 바꿔줘" -> {{"query_type": 5}}
    "내일 회의 취소해줘" -> {{"query_type": 6}}
    "매주 월요일 운동 루틴 없애줘" -> {{"query_type": 7}}

    설명하지 말고 다음 형식의 JSON만 반환한다:
    {{"query_type": 0}}

    사용자 요청: {user_text}
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

async def parameter_request_message(query_type: int, required_args: list[str]) -> str:
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

async def extract_parameters_from_text(query_type: int, user_text: str, required_args: list[str], request_time: str, current_parameters: dict) -> dict:
    non_targeting_prompt = (f"""
        역할: 일정 요청에서 DB 처리에 필요한 값만 추출한다.

        쿼리 유형: {query_type}
        기준 시각: {request_time}
        추출할 필드: {required_args}
        이미 수집한 값: {current_parameters}

        필드 형식:
        - target_date: YYYY-MM-DD
        - start_time, end_time:
          · 일정과 기간 조회는 YYYY-MM-DD HH:MM:SS
          · 반복 루틴은 HH:MM:SS
        - business: 일정 또는 루틴의 핵심 내용 문자열
        - location: 장소 문자열
        - who: 사람 이름 문자열 배열
        - days_of_week: 0=일, 1=월, 2=화, 3=수, 4=목, 5=금, 6=토
        - start_date, end_date: YYYY-MM-DD

        규칙:
        - 오늘, 내일, 모레 같은 상대 날짜는 기준 시각으로 계산한다.
        - 오전과 오후를 구분하여 24시간제로 변환한다.
        - 매일은 [0,1,2,3,4,5,6], 평일은 [1,2,3,4,5], 주말은 [0,6]이다.
        - 사용자가 말하지 않은 값은 추측하지 말고 null로 반환한다.
        - 추출할 필드에 없는 키는 반환하지 않는다.
        - 설명이나 마크다운을 붙이지 않는다.

        다음 형식의 JSON만 반환한다:
        {{"extract_result": {{"필드명": "추출값 또는 null"}}}}

        사용자 요청: {user_text}
        """
        )

    targeting_prompt = (f"""
        역할: 수정 또는 삭제 요청에서 후보 탐색 정보와 수정 정보를 분리해 추출한다.

        쿼리 유형: {query_type}
        기준 시각: {request_time}
        이미 수집한 값: {current_parameters}

        타겟팅 규칙:
        - 일정 수정·삭제(4, 6)는 기존 일정이 있는 날짜만 target_date로 추출한다.
        - 루틴 수정·삭제(5, 7)는 기존 루틴의 요일만 days_of_week로 추출한다.
        - 후보는 날짜 또는 요일로 조회하므로 내용, 시간, 장소로 후보를 좁히지 않는다.
        - schedule_id와 routine_group_id는 서버가 후보 선택 후 결정하므로 생성하지 않는다.

        수정 규칙:
        - 수정 요청(4, 5)이면 사용자가 새로 바꾸려는 값만 update_information에 넣는다.
        - 기존 대상을 설명한 값과 새 값이 섞이지 않게 한다.
        - 일정 시각은 YYYY-MM-DD HH:MM:SS 형식이다.
        - 루틴 시각은 HH:MM:SS 형식이다.
        - 요일 번호는 0=일, 1=월, 2=화, 3=수, 4=목, 5=금, 6=토다.
        - 장소, 동반자, 종료 시각을 지우라는 요청은 해당 값을 null로 넣는다.
        - 삭제 요청(6, 7)의 update_information은 빈 객체다.
        - 사용자가 말하지 않은 값은 추측하지 않는다.

        예시:
        "내일 일정을 3시로 바꿔줘"
        -> {{"target": {{"target_date": "기준 시각으로 계산한 날짜"}}, "update_information": {{"start_time": "해당 날짜 15:00:00"}}}}

        "월수금 루틴을 화목으로 바꿔줘"
        -> {{"target": {{"days_of_week": [1,3,5]}}, "update_information": {{"days_of_week": [2,4]}}}}

        결과를 다음 객체에 넣어 JSON만 반환한다:
        {{"extract_result": {{"target": {{}}, "update_information": {{}}}}}}

        사용자 요청: {user_text}
        """
        )

    prompt = non_targeting_prompt if query_type < 4 else targeting_prompt

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
                extract_result = dict(json.loads(result_str).get("extract_result"))
                return extract_result
            print(f"Ollama 에러: {response.status_code}")
            return {"result": "extract fail"}
    except Exception as e:
        print(f"AI 라우팅 실패: {str(e)}")
        return {"result": "extract fail"}

async def update_current_parameters(query_type: int, user_text: str, required_args: list[str], request_time: str, current_parameters: dict) -> int:
    extracted_parameters = extract_parameters_from_text(query_type, user_text, required_args, request_time, current_parameters)
    is_success = False if (extracted_parameters.get("result") == "extract fail") else True
    if (is_success == False):
        print("인자 추출 중 오류가 발생했습니다.")
        return -1
    else:
        for key in extracted_parameters.keys():
            if (current_parameters[key] == None and extracted_parameters[key] != None):
                current_parameters[key] = extracted_parameters[key]
        return 1

async def request_date_info() -> str:
    return

async def request_weekday_info() -> str:
    return

async def targeting() -> str:
    target_id = None
    return

async def collission_check() -> dict:
    collision_schedule = {}
    return collision_schedule

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
        is_updated = await update_current_parameters(query_type, user_text, fields_to_extract, request_time, query_context.current_parameters)
        if (is_updated == -1):
            print("인자 업데이트 실패!")
            return query_context
        missing_args = check_arg(query_type, query_context.current_parameters)
        if (len(missing_args) > 0):
            query_context.response_message = await parameter_request_message(query_context.query_type, missing_args)
            return query_context
        # 2. DB 조회
        else:
            db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    # 3. 조회 성공 or 실패 답변 반환
    query_context.response_message = await create_final_response(db_result, query_context.query_type)
    query_context.pending_step = "done"
    return query_context

async def handle_range_query(query_context: query_context.ScheduleQueryContext):
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
        await update_current_parameters(query_type, user_text, fields_to_extract, request_time, query_context.current_parameters)
        # 인자 부재시 디폴트값 삽입
        if (query_context.current_parameters["start_time"] == None):
            query_context.current_parameters["start_time"] = request_time
        if (query_context.current_parameters["end_time"] == None):
            query_context.current_parameters["end_time"] = datetime.strftime(datetime.strptime(request_time, "%Y-%m-%d 00:00:00") + datetime.timedelta(days=1))
    # 2. DB 조회
    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    # 3. 조회 성공 or 실패 답변 반환
    query_context.response_message = await create_final_response(db_result, query_context.query_type)
    query_context.pending_step = "done"
    return query_context

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
