# 텍스트 쿼리 --> DB 저장 및 검색 쿼리 변환
# analyze_text_query: 자연어쿼리의 쿼리 유형 파악 후 해당 쿼리에 해당하는 인자만을 추출하여 query_type, query_args로 db_process.py에 전달
# process_text_query: db_process.py에서 받아온 쿼리 결과를 분석하여 자연어로 변환 후 반환
import httpx
import json
from datetime import datetime, timedelta
from uuid import uuid4
from service import db_process, query_context
from service.query_context import (
    mandatory_parameters,
    next_step_mapping,
    optional_parameters,
    parameter_templates,
    parameter_request_mapping,
)
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
    prompt = (f"""
        역할: 사용자의 일정 요청에서 현재 단계에 필요한 필드만 추출한다.

        쿼리 유형: {query_type}
        기준 시각: {request_time}
        현재 단계에서 추출할 필드: {required_args}
        이미 수집한 값: {current_parameters}

        쿼리 유형:
        0 = 하루 조회
        1 = 기간 조회
        2 = 일정 삽입
        3 = 루틴 삽입
        4 = 일정 수정
        5 = 루틴 수정
        6 = 일정 삭제
        7 = 루틴 삭제

        필드 형식:
        - target_date: YYYY-MM-DD
        - 일정의 start_time, end_time: YYYY-MM-DD HH:MM:SS
        - 루틴의 start_time, end_time: HH:MM:SS
        - business: 일정 또는 루틴의 핵심 내용 문자열
        - location: 장소 문자열
        - who: 사람 이름 문자열 배열
        - days_of_week: 0~6을 원소로 가지는 배열. 0=일, 1=월, 2=화, 3=수, 4=목, 5=금, 6=토
        - start_date, end_date: YYYY-MM-DD

        규칙:
        - 반드시 "현재 단계에서 추출할 필드"에 있는 키만 처리한다.
        - 타겟팅 단계에서 target_date만 주어지면 기존 일정의 날짜만 추출한다.
        - 타겟팅 단계에서 days_of_week만 주어지면 기존 루틴의 요일만 추출한다.
        - 수정 단계에서는 전달된 수정 필드에 대해 사용자가 새로 바꾸려는 값만 추출한다.
        - 기존 대상을 설명하는 값과 새로 변경할 값을 혼동하지 않는다.
        - schedule_id와 routine_group_id는 사용자 문장으로 추측하거나 생성하지 않는다.
        - 오늘, 내일, 모레 같은 상대 날짜는 기준 시각으로 계산한다.
        - 오전과 오후를 구분하여 24시간제로 변환한다.
        - 매일은 [0,1,2,3,4,5,6], 평일은 [1,2,3,4,5], 주말은 [0,6]이다.
        - 기간 조회의 end_time은 조회에 포함되지 않는 종료 경계다.
        - “이번 주”는 이번 주 월요일 00:00:00부터 다음 주 월요일 00:00:00까지다.
        - 사용자가 말하지 않은 값은 추측하지 말고 null로 반환한다.
        - 장소, 동반자, 종료 시각을 지우라는 요청은 해당 필드 값을 null로 반환한다.
        - 설명이나 마크다운을 붙이지 않는다.

        다음 형식의 JSON만 반환한다:
        {{"extract_result": {{"필드명": "추출값 또는 null"}}}}

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
                extract_result = dict(json.loads(result_str).get("extract_result"))
                return extract_result
            print(f"Ollama 에러: {response.status_code}")
            return {"result": "extract fail"}
    except Exception as e:
        print(f"AI 라우팅 실패: {str(e)}")
        return {"result": "extract fail"}

async def update_current_parameters(query_type: int, user_text: str, required_args: list[str], request_time: str, current_parameters: dict) -> int:
    extracted_parameters = await extract_parameters_from_text(query_type, user_text, required_args, request_time, current_parameters)
    is_success = False if (extracted_parameters.get("result") == "extract fail") else True
    if (is_success == False):
        print("인자 추출 중 오류가 발생했습니다.")
        return -1
    else:
        for key in current_parameters.keys():
            if (
                key in extracted_parameters
                and current_parameters[key] is None
                and extracted_parameters[key] is not None
            ):
                current_parameters[key] = extracted_parameters[key]
        return 1

def routine_occurs_on(routine: dict, occurrence_date) -> bool:
    days_of_week = routine.get("days_of_week")
    if days_of_week is None:
        days_of_week = [routine["day_of_week"]]

    project_weekday = (occurrence_date.weekday() + 1) % 7
    if project_weekday not in days_of_week:
        return False

    start_date = routine.get("start_date")
    end_date = routine.get("end_date")
    if start_date is not None and occurrence_date < db_process.parse_to_date(start_date):
        return False
    if end_date is not None and occurrence_date > db_process.parse_to_date(end_date):
        return False
    return True

def routine_occurrence_bounds(routine: dict, occurrence_date):
    start_time = db_process.parse_to_time(routine["start_time"])
    start_dt = datetime.combine(occurrence_date, start_time)
    if routine.get("end_time") is None:
        return start_dt, start_dt + db_process.DEFAULT_DURATION

    end_time = db_process.parse_to_time(routine["end_time"])
    end_dt = datetime.combine(occurrence_date, end_time)
    if end_time < start_time:
        end_dt += timedelta(days=1)
    return start_dt, end_dt

async def get_collision(user_id: str, query_type: int, current_parameters: dict) -> list[dict]:
    candidates = await db_process.process_collision_query(
        user_id,
        query_type,
        current_parameters,
    )
    if candidates.get("status") != "success":
        raise RuntimeError(candidates.get("message", "충돌 후보 조회에 실패했습니다."))

    schedules = candidates["schedules"]
    routines = candidates["routines"]

    if query_type == 4:
        schedule_id = current_parameters["schedule_id"]
        schedules = [
            item
            for item in schedules
            if item["Schedule_ID"] != schedule_id
        ]

    if query_type in (2, 4):
        return schedules + routines

    new_routine = current_parameters
    collision_result = []

    # 기존 일정이 새 루틴의 실제 발생분과 겹치는지 확인
    for item in schedules:
        schedule_start = db_process.parse_to_datetime(item["start_time"])
        schedule_end = (
            schedule_start + db_process.DEFAULT_DURATION
            if item.get("end_time") is None
            else db_process.parse_to_datetime(item["end_time"])
        )
        occurrence_date = schedule_start.date() - timedelta(days=1)
        while occurrence_date <= schedule_end.date():
            if routine_occurs_on(new_routine, occurrence_date):
                routine_start, routine_end = routine_occurrence_bounds(
                    new_routine,
                    occurrence_date,
                )
                if routine_start < schedule_end and routine_end > schedule_start:
                    collision_result.append(item)
                    break
            occurrence_date += timedelta(days=1)

    # 기존 루틴과 새 루틴이 실제로 함께 발생하는 날짜 확인
    for item in routines:
        if (
            query_type == 5
            and item["Routine_Group_ID"]
            == current_parameters["routine_group_id"]
        ):
            continue

        reference_dates = [datetime.now().date()]
        for value in (new_routine.get("start_date"), item.get("start_date")):
            if value is not None:
                reference_dates.append(db_process.parse_to_date(value))
        reference_date = max(reference_dates)

        has_collision = False
        for day_offset in range(-1, 8):
            new_occurrence_date = reference_date + timedelta(days=day_offset)
            if not routine_occurs_on(new_routine, new_occurrence_date):
                continue

            new_start, new_end = routine_occurrence_bounds(
                new_routine,
                new_occurrence_date,
            )
            for old_day_offset in (-1, 0, 1):
                old_occurrence_date = (
                    new_occurrence_date + timedelta(days=old_day_offset)
                )
                if not routine_occurs_on(item, old_occurrence_date):
                    continue

                old_start, old_end = routine_occurrence_bounds(
                    item,
                    old_occurrence_date,
                )
                if new_start < old_end and new_end > old_start:
                    has_collision = True
                    break
            if has_collision:
                collision_result.append(item)
                break

    return collision_result

async def collision_decision_request(query_type: int, collision_list: list[dict]) -> str:
    lines = []
    for index, item in enumerate(collision_list, start=1):
        item_type = "일정" if "Schedule_ID" in item else "루틴"
        location = f" / 장소: {item['location']}" if item.get("location") else ""
        lines.append(
            f"{index}. [{item_type}] "
            f"{item.get('start_time')} ~ {item.get('end_time')}"
            f" / {item.get('business')}{location}"
        )

    return (
        "다음 일정 또는 루틴과 시간이 겹칩니다.\n"
        + "\n".join(lines)
        + "\n무시하고 이대로 삽입하려면 '진행', 삽입하지 않으려면 '폐기'라고 단어만으로 말씀해주세요."
    )

async def extract_dayinfo_from_text(query_type: int, user_text: str, request_time: str) -> dict:
    schedule_prompt = (f"""
        역할: 사용자의 일정 수정/삭제 요청에서 해당 일정이 어느 날짜에 속하는지 추출한다.

        기준 시각: {request_time}
        현재 단계에서 추출할 필드: target_date

        필드 형식:
        - target_date: YYYY-MM-DD

        규칙:
        - 반드시 "현재 단계에서 추출할 필드"에 있는 키만 처리한다.
        - 오늘, 내일, 모레 같은 상대 날짜는 기준 시각으로 계산한다.
        - 오전과 오후를 구분하여 24시간제로 변환한다.
        - “이번 주”는 이번 주 월요일 00:00:00부터 다음 주 월요일 00:00:00까지다.
        - 사용자가 말하지 않은 값은 추측하지 말고 null로 반환한다.
        - 설명이나 마크다운을 붙이지 않는다.

        다음 형식의 JSON만 반환한다:
        {{"extract_result": {{"필드명": "추출값 또는 null"}}}}

        사용자 요청: {user_text}
        """
        )

    routine_prompt = (f"""
        역할: 사용자의 루틴 수정/삭제 요청에서 해당 루틴이 어느 요일에 속하는지 추출한다.
    
        기준 시각: {request_time}
        현재 단계에서 추출할 필드: days_of_week
    
        필드 형식:
        - days_of_week: 0~6을 원소로 가지는 배열. 0=일, 1=월, 2=화, 3=수, 4=목, 5=금, 6=토
    
        규칙:
        - 반드시 "현재 단계에서 추출할 필드"에 있는 키만 처리한다.
        - 오늘, 내일, 모레 같은 상대 날짜는 기준 시각으로 계산한다.
        - 오전과 오후를 구분하여 24시간제로 변환한다.
        - 매일은 [0,1,2,3,4,5,6], 평일은 [1,2,3,4,5], 주말은 [0,6]이다.
        - “이번 주”는 이번 주 월요일 00:00:00부터 다음 주 월요일 00:00:00까지다.
        - 사용자가 말하지 않은 값은 추측하지 말고 null로 반환한다.
        - 설명이나 마크다운을 붙이지 않는다.
    
        다음 형식의 JSON만 반환한다:
        {{"extract_result": {{"필드명": "추출값 또는 null"}}}}
    
        사용자 요청: {user_text}
        """
        )

    prompt = schedule_prompt if (query_type == 4 or query_type == 6) else routine_prompt

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

async def extract_update_parameters(query_type: int, user_text: str, required_args: list[str], request_time: str) -> dict:
    prompt = (f"""
        역할: 사용자의 일정 요청에서 현재 단계에 필요한 필드만 추출한다.
    
        쿼리 유형: {query_type}
        기준 시각: {request_time}
        현재 단계에서 추출할 필드: {required_args}
    
        쿼리 유형:
        4 = 일정 수정
        5 = 루틴 수정
    
        필드 형식:
        - 일정의 start_time, end_time: YYYY-MM-DD HH:MM:SS
        - 루틴의 start_time, end_time: HH:MM:SS
        - business: 일정 또는 루틴의 핵심 내용 문자열
        - location: 장소 문자열
        - who: 사람 이름 문자열 배열
        - days_of_week: 0~6을 원소로 가지는 배열. 0=일, 1=월, 2=화, 3=수, 4=목, 5=금, 6=토
        - start_date, end_date: YYYY-MM-DD
    
        규칙:
        - 타겟팅 단계에서 target_date만 주어지면 기존 일정의 날짜만 추출한다.
        - 타겟팅 단계에서 days_of_week만 주어지면 기존 루틴의 요일만 추출한다.
        - 수정 단계에서는 전달된 수정 필드에 대해 사용자가 새로 바꾸려는 값만 추출한다.
        - 기존 대상을 설명하는 값과 새로 변경할 값을 혼동하지 않는다.
        - schedule_id와 routine_group_id는 사용자 문장으로 추측하거나 생성하지 않는다.
        - 오늘, 내일, 모레 같은 상대 날짜는 기준 시각으로 계산한다.
        - 오전과 오후를 구분하여 24시간제로 변환한다.
        - 매일은 [0,1,2,3,4,5,6], 평일은 [1,2,3,4,5], 주말은 [0,6]이다.
        - 기간 조회의 end_time은 조회에 포함되지 않는 종료 경계다.
        - “이번 주”는 이번 주 월요일 00:00:00부터 다음 주 월요일 00:00:00까지다.
        - 사용자가 말하지 않은 값은 반환하지 않는다.
        - 장소, 동반자, 종료 시각을 지우라는 요청은 해당 필드 값을 null로 반환한다.
        - 설명이나 마크다운을 붙이지 않는다.
    
        다음 형식의 JSON만 반환한다:
        {{"extract_result": {{"필드명": "추출값 또는 null"}}}}
    
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
                extract_result = dict(json.loads(result_str).get("extract_result"))
                return extract_result
            print(f"Ollama 에러: {response.status_code}")
            return {"result": "extract fail"}
    except Exception as e:
        print(f"AI 라우팅 실패: {str(e)}")
        return {"result": "extract fail"}

async def request_date_info(day_candidates: list[str]) -> str:
    return (
        "일정이 존재하는 날짜입니다.\n"
        + "\n".join(
            f"{index}번: {target_date}"
            for index, target_date in enumerate(day_candidates, start=1)
        )
        + "\n수정/삭제할 일정이 존재하는 날짜가 몇번째인지 \"x번\"으로 말씀해주세요."
    )

async def request_weekday_info(weekday_candidates: list[int]) -> str:
    weekday_names = {
        0: "일요일",
        1: "월요일",
        2: "화요일",
        3: "수요일",
        4: "목요일",
        5: "금요일",
        6: "토요일",
    }
    return (
        "루틴이 존재하는 요일입니다.\n"
        + ", ".join(weekday_names[weekday] for weekday in weekday_candidates)
        + "\n수정/삭제할 루틴이 존재하는 요일을 \"월\", \"화\" 등으로 말씀해주세요."
    )

def get_candidate_index(user_text: str, candidate_count: int) -> int | None:
    choice = user_text.strip()
    if choice.endswith("번"):
        choice = choice[:-1].strip()
    if not choice.isdecimal():
        return None

    candidate_index = int(choice) - 1
    if candidate_index not in range(candidate_count):
        return None
    return candidate_index

def get_weekday_candidate(user_text: str, weekday_candidates: list[int]) -> int | None:
    weekday_mapping = {
        "일": 0,
        "월": 1,
        "화": 2,
        "수": 3,
        "목": 4,
        "금": 5,
        "토": 6,
    }
    choice = user_text.strip().replace(" ", "")
    if choice.endswith("요일"):
        choice = choice[:-2]

    weekday = weekday_mapping.get(choice)
    if weekday not in weekday_candidates:
        return None
    return weekday

async def request_targeting(query_type: int, candidates: list[dict]) -> str:
    action = "수정" if query_type in (4, 5) else "삭제"
    target_type = "일정" if query_type in (4, 6) else "루틴"
    weekday_names = {
        0: "일요일",
        1: "월요일",
        2: "화요일",
        3: "수요일",
        4: "목요일",
        5: "금요일",
        6: "토요일",
    }

    lines = []
    for index, candidate in enumerate(candidates, start=1):
        start_time = candidate.get("start_time")
        end_time = candidate.get("end_time")
        time_text = (
            str(start_time)
            if end_time is None
            else f"{start_time} ~ {end_time}"
        )
        weekday = ""
        if query_type in (5, 7):
            weekday = f"{weekday_names[candidate['day_of_week']]} / "
        location = (
            f" / 장소: {candidate['location']}"
            if candidate.get("location")
            else ""
        )
        lines.append(
            f"{index}번: {weekday}{time_text}"
            f" / {candidate.get('business')}{location}"
        )

    return (
        f"{action}할 {target_type} 후보입니다.\n"
        + "\n".join(lines)
        + f"\n{action}할 {target_type}이 몇 번째인지 \"x번\"으로 말씀해주세요."
    )

async def get_target_candidates(user_id: str, query_type: int, time_info, request_time: str) -> dict:
    return await db_process.process_target_candidates_query(user_id, query_type, time_info, request_time)

async def create_final_response(db_result: dict, query_type: int) -> str:
    if db_result.get("status") != "success":
        return db_result.get(
            "message",
            "일정을 조회하는 중 오류가 발생했습니다.",
        )

    timeline = db_result.get("timeline", [])
    target_date = db_result.get("target_date")

    if not timeline:
        if query_type == 0:
            return f"{target_date}에는 등록된 일정이나 루틴이 없습니다."

        query_range = db_result.get("range", {})
        return (
            f"{query_range.get('start_time')}부터 "
            f"{query_range.get('end_time')}까지 등록된 일정이나 루틴이 없습니다."
        )

    lines = []

    for item in timeline:
        schedule_type = "일정" if item["type"] == "schedule" else "루틴"
        location = (
            f" / 장소: {item['location']}"
            if item.get("location")
            else ""
        )
        who = (
            f" / 함께하는 사람: {', '.join(item['who'])}"
            if item.get("who")
            else ""
        )
        inferred = " (종료 시각 추정)" if item.get("end_time_inferred") else ""

        lines.append(
            f"- [{schedule_type}] "
            f"{item['start_time']} ~ {item['end_time']}{inferred}"
            f" / {item['business']}{location}{who}"
        )

    if query_type == 0:
        title = f"{target_date}의 일정입니다."
    else:
        query_range = db_result.get("range", {})
        title = (
            f"{query_range.get('start_time')}부터 "
            f"{query_range.get('end_time')}까지의 일정입니다."
        )

    return f"{title}\n" + "\n".join(lines)

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
        if is_updated == -1:
            query_context.response_message = "요청 내용을 분석하지 못했습니다. 다시 말씀해주세요."
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
        is_updated = await update_current_parameters(query_type, user_text, fields_to_extract, request_time, query_context.current_parameters)
        if is_updated == -1:
            query_context.response_message = "요청 내용을 분석하지 못했습니다. 다시 말씀해주세요."
            return query_context
        # 인자 부재시 디폴트값 삽입
        if (query_context.current_parameters["start_time"] == None):
            query_context.current_parameters["start_time"] = request_time
        if (query_context.current_parameters["end_time"] == None):
            query_context.current_parameters["end_time"] = (datetime.strptime(request_time, "%Y-%m-%d %H:%M:%S").replace(hour=0, minute=0, second=0) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    # 2. DB 조회
    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    # 3. 조회 성공 or 실패 답변 반환
    query_context.response_message = await create_final_response(db_result, query_context.query_type)
    query_context.pending_step = "done"
    return query_context

async def handle_schedule_insert(query_context: query_context.ScheduleQueryContext):
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
        if is_updated == -1:
            query_context.response_message = "요청 내용을 분석하지 못했습니다. 다시 말씀해주세요."
            return query_context
        missing_args = check_arg(query_type, query_context.current_parameters)
        if (len(missing_args) > 0):
            query_context.response_message = await parameter_request_message(query_context.query_type, missing_args)
            return query_context

    if (query_context.pending_step == "waiting_collision_decision"):
        decision = user_text.strip().replace(" ", "")
        if decision == "폐기":
            query_context.response_message = "일정 삽입을 종료하였습니다."
            query_context.pending_step = "done"
            return query_context
        if decision != "진행":
            query_context.response_message = (
                "일정 삽입을 계속하려면 '진행', 삽입하지 않으려면 "
                "'폐기'라고 말씀해주세요."
            )
            return query_context
    else:
        collision_list = await get_collision(user_id, query_type, query_context.current_parameters)
        if (len(collision_list) > 0):
            query_context.response_message = await collision_decision_request(query_context.query_type, collision_list)
            query_context.pending_step = "waiting_collision_decision"
            return query_context

    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    if (db_result["status"] == "success"):
        query_context.response_message = "일정 삽입에 성공하였습니다."
    else:
        query_context.response_message = "db 오류로 인해 일정삽입에 실패하였습니다."
    # 3. 삽입 성공 or 충돌 답변 반환
    query_context.pending_step = "done"
    return query_context

async def handle_routine_insert(query_context: query_context.ScheduleQueryContext):
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
        if is_updated == -1:
            query_context.response_message = "요청 내용을 분석하지 못했습니다. 다시 말씀해주세요."
            return query_context
        missing_args = check_arg(query_type, query_context.current_parameters)
        if (len(missing_args) > 0):
            query_context.response_message = await parameter_request_message(query_context.query_type, missing_args)
            return query_context

    if (query_context.pending_step == "waiting_collision_decision"):
        decision = user_text.strip().replace(" ", "")
        if decision == "폐기":
            query_context.response_message = "루틴 삽입을 종료하였습니다."
            query_context.pending_step = "done"
            return query_context
        if decision != "진행":
            query_context.response_message = (
                "루틴 삽입을 계속하려면 '진행', 삽입하지 않으려면 "
                "'폐기'라고 말씀해주세요."
            )
            return query_context
    else:
        collision_list = await get_collision(user_id, query_type, query_context.current_parameters)
        if (len(collision_list) > 0):
            query_context.response_message = await collision_decision_request(query_context.query_type, collision_list)
            query_context.pending_step = "waiting_collision_decision"
            return query_context

    if query_context.current_parameters["routine_group_id"] is None:
        query_context.current_parameters["routine_group_id"] = str(uuid4())

    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    if (db_result["status"] == "success"):
        query_context.response_message = "루틴 삽입에 성공하였습니다."
    else:
        query_context.response_message = "db 오류로 인해 루틴 삽입에 실패하였습니다."
    # 3. 삽입 성공 or 충돌 답변 반환
    query_context.pending_step = "done"
    return query_context

async def handle_schedule_update(query_context: query_context.ScheduleQueryContext):
    user_id = query_context.user_id
    query_type = query_context.query_type
    user_text = query_context.user_text
    request_time = query_context.request_time
    # 종료상태에서 재진입 시 바로 반환
    if query_context.pending_step == "done":
        return query_context
    # 0. 최초 요청문에서 인자 추출 시도
    if (query_context.pending_step == "waiting_initial_extraction"):
        required_args = list_to_extract(query_type, query_context.current_parameters)
        update_args = await extract_update_parameters(query_type, user_text, required_args, request_time)
        if (update_args.get("result") != "extract fail"):
            query_context.update_parameters = {
                key: value
                for key, value in update_args.items()
                if key in query_context.current_parameters
                and key != "schedule_id"
            }
        day_info = await extract_dayinfo_from_text(query_type, user_text, request_time)
        if (day_info.get("result") != "extract fail"):
            if (day_info.get("target_date") != None):
                query_context.targeting_parameters = {"target_date": day_info.get("target_date")}
                query_context.pending_step = "waiting_to_pick_day"
            else:
                day_result = await db_process.process_target_day_query(user_id, query_type, request_time)
                if (day_result.get("status") != "success"):
                    query_context.response_message = day_result.get("message", "일정 날짜 조회에 실패하였습니다.")
                    return query_context
                query_context.target_candidates = day_result.get("candidates", [])
                if (len(query_context.target_candidates) <= 0):
                    query_context.response_message = "수정할 일정이 존재하지 않습니다."
                    query_context.pending_step = "done"
                    return query_context
                query_context.response_message = await request_date_info(query_context.target_candidates)
                query_context.pending_step = "waiting_to_pick_day"
                return query_context
        else:
            day_result = await db_process.process_target_day_query(user_id, query_type, request_time)
            if (day_result.get("status") != "success"):
                query_context.response_message = day_result.get("message", "일정 날짜 조회에 실패하였습니다.")
                return query_context
            query_context.target_candidates = day_result.get("candidates", [])
            if (len(query_context.target_candidates) <= 0):
                query_context.response_message = "수정할 일정이 존재하지 않습니다."
                query_context.pending_step = "done"
                return query_context
            query_context.response_message = await request_date_info(query_context.target_candidates)
            query_context.pending_step = "waiting_to_pick_day"
            return query_context
    # 1-1. 타겟팅(현재기준 일정 존재하는 날짜 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_day"):
        target_date = query_context.targeting_parameters.get("target_date")
        if target_date is None:
            candidate_index = get_candidate_index(user_text, len(query_context.target_candidates))
            if candidate_index is None:
                query_context.response_message = await request_date_info(query_context.target_candidates)
                return query_context
            target_date = query_context.target_candidates[candidate_index]
            query_context.targeting_parameters = {"target_date": target_date}
        target_result = await get_target_candidates(user_id, query_type, target_date, request_time)
        if target_result.get("status") != "success":
            query_context.response_message = target_result.get("message", "일정 후보 조회에 실패하였습니다.")
            return query_context
        query_context.target_candidates = target_result.get("candidates", [])
        if len(query_context.target_candidates) <= 0:
            query_context.response_message = "해당 날짜에는 수정할 일정이 존재하지 않습니다."
            query_context.pending_step = "done"
            return query_context
        query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
        query_context.pending_step = "waiting_target"
        return query_context
    # 1-2. 타겟팅(해당 날짜의 일정 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        # 여기선 기존 응답 고려 안함. 고정적으로 정해진 날짜안의 일정 리스트 제공 후 단어 응답 대기
        candidate_index = get_candidate_index(user_text, len(query_context.target_candidates))
        if candidate_index is None:
            query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
            return query_context
        else:
            target_schedule = query_context.target_candidates[candidate_index]
            query_context.selected_targets = [target_schedule]
            query_context.current_parameters = {
                "schedule_id": target_schedule["Schedule_ID"],
                "start_time": target_schedule["start_time"],
                "end_time": target_schedule.get("end_time"),
                "business": target_schedule["business"],
                "location": target_schedule.get("location"),
                "who": target_schedule.get("who"),
            }
            for key, value in query_context.update_parameters.items():
                if key in query_context.current_parameters and key != "schedule_id":
                    query_context.current_parameters[key] = value

            if not query_context.update_parameters:
                query_context.response_message = "수정할 정보를 말씀해주세요."
                query_context.pending_step = "waiting_parameters"
                return query_context
    # 2. 인자 확인
    if (query_context.pending_step == "waiting_parameters"):
        if not query_context.update_parameters:
            required_args = list(query_context.current_parameters.keys())
            update_args = await extract_update_parameters(query_type, user_text, required_args, request_time,)
            if update_args.get("result") == "extract fail":
                query_context.response_message = "요청 내용을 분석하지 못했습니다. 다시 말씀해주세요."
                return query_context

            for key, value in update_args.items():
                if (key in query_context.current_parameters and key != "schedule_id"):
                    query_context.update_parameters[key] = value

        if not query_context.update_parameters:
            query_context.response_message = "수정할 정보를 말씀해주세요."
            return query_context

        for key, value in query_context.update_parameters.items():
            if key in query_context.current_parameters and key != "schedule_id":
                query_context.current_parameters[key] = value
    # 3. 수정튜플 충돌검사
    if (query_context.pending_step == "waiting_collision_decision"):
        decision = user_text.strip().replace(" ", "")
        if decision == "폐기":
            query_context.response_message = "일정 수정을 종료하였습니다."
            query_context.pending_step = "done"
            return query_context
        if decision != "진행":
            query_context.response_message = ("일정 수정을 계속하려면 '진행', 수정하지 않으려면 '폐기'라고 말씀해주세요.")
            return query_context
    else:
        collision_list = await get_collision(user_id, query_type, query_context.current_parameters)
        if (len(collision_list) > 0):
            query_context.response_message = await collision_decision_request(query_context.query_type, collision_list)
            query_context.pending_step = "waiting_collision_decision"
            return query_context
    # 4. 수정 성공 or 실패 답변 반환
    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    if (db_result["status"] == "success"):
        query_context.response_message = "일정 수정에 성공하였습니다."
    else:
        query_context.response_message = "db 오류로 인해 일정수정에 실패하였습니다."
    # 3. 삽입 성공 or 실패 답변 반환
    query_context.pending_step = "done"
    return query_context

async def handle_routine_update(query_context: query_context.ScheduleQueryContext):
    user_id = query_context.user_id
    query_type = query_context.query_type
    user_text = query_context.user_text
    request_time = query_context.request_time
    # 종료상태에서 재진입 시 바로 반환
    if query_context.pending_step == "done":
        return query_context
    # 0. 최초 요청문에서 인자 추출 시도
    if (query_context.pending_step == "waiting_initial_extraction"):
        required_args = list_to_extract(query_type, query_context.current_parameters)
        update_args = await extract_update_parameters(query_type, user_text, required_args, request_time)
        if (update_args.get("result") != "extract fail"):
            query_context.update_parameters = {
                key: value
                for key, value in update_args.items()
                if key in query_context.current_parameters
                and key != "routine_group_id"
            }
        day_info = await extract_dayinfo_from_text(query_type, user_text, request_time)
        if (day_info.get("result") != "extract fail"):
            if (day_info.get("days_of_week") != None):
                query_context.targeting_parameters = {"days_of_week": day_info.get("days_of_week")}
                query_context.pending_step = "waiting_to_pick_weekday"
            else:
                day_result = await db_process.process_target_day_query(user_id, query_type, request_time)
                if (day_result.get("status") != "success"):
                    query_context.response_message = day_result.get("message", "루틴 요일 조회에 실패하였습니다.")
                    return query_context
                query_context.target_candidates = day_result.get("candidates", [])
                if (len(query_context.target_candidates) <= 0):
                    query_context.response_message = "수정할 루틴이 존재하지 않습니다."
                    query_context.pending_step = "done"
                    return query_context
                query_context.response_message = await request_weekday_info(query_context.target_candidates)
                query_context.pending_step = "waiting_to_pick_weekday"
                return query_context
        else:
            day_result = await db_process.process_target_day_query(user_id, query_type, request_time)
            if (day_result.get("status") != "success"):
                query_context.response_message = day_result.get("message", "루틴 요일 조회에 실패하였습니다.")
                return query_context
            query_context.target_candidates = day_result.get("candidates", [])
            if (len(query_context.target_candidates) <= 0):
                query_context.response_message = "수정할 루틴이 존재하지 않습니다."
                query_context.pending_step = "done"
                return query_context
            query_context.response_message = await request_weekday_info(query_context.target_candidates)
            query_context.pending_step = "waiting_to_pick_weekday"
            return query_context
    # 1-1. 타겟팅(유효한 루틴 존재하는 요일 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_weekday"):
        target_days = query_context.targeting_parameters.get("days_of_week")
        if target_days is None:
            target_weekday = get_weekday_candidate(user_text, query_context.target_candidates)
            if target_weekday is None:
                query_context.response_message = await request_weekday_info(query_context.target_candidates)
                return query_context
            target_days = [target_weekday]
            query_context.targeting_parameters = {"days_of_week": target_days}

        target_result = await get_target_candidates(user_id, query_type, target_days, request_time)
        if target_result.get("status") != "success":
            query_context.response_message = target_result.get("message", "루틴 후보 조회에 실패하였습니다.")
            return query_context

        group_candidates = {}
        for candidate in target_result.get("candidates", []):
            group_candidates.setdefault(candidate["Routine_Group_ID"], candidate)
        query_context.target_candidates = list(group_candidates.values())
        if not query_context.target_candidates:
            query_context.response_message = "해당 요일에는 수정할 루틴이 존재하지 않습니다."
            query_context.pending_step = "done"
            return query_context

        query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
        query_context.pending_step = "waiting_target"
        return query_context
    # 1-2. 타겟팅(해당 요일의 루틴 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        candidate_index = get_candidate_index(user_text, len(query_context.target_candidates))
        if candidate_index is None:
            query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
            return query_context

        target_routine = query_context.target_candidates[candidate_index]
        routine_group_id = target_routine["Routine_Group_ID"]
        group_result = await db_process.process_routine_group_query(user_id, routine_group_id)
        if group_result.get("status") != "success":
            query_context.response_message = group_result.get("message", "루틴 그룹 조회에 실패하였습니다.")
            return query_context

        group_rows = group_result.get("candidates", [])
        if not group_rows:
            query_context.response_message = "수정할 루틴 그룹이 존재하지 않습니다."
            query_context.pending_step = "done"
            return query_context

        query_context.selected_targets = group_rows
        base_routine = group_rows[0]
        query_context.current_parameters = {
            "routine_group_id": routine_group_id,
            "start_time": base_routine["start_time"],
            "end_time": base_routine.get("end_time"),
            "business": base_routine["business"],
            "location": base_routine.get("location"),
            "who": base_routine.get("who"),
            "days_of_week": sorted({
                row["day_of_week"]
                for row in group_rows
            }),
            "start_date": base_routine.get("start_date"),
            "end_date": base_routine.get("end_date"),
        }
        for key, value in query_context.update_parameters.items():
            if (key in query_context.current_parameters and key != "routine_group_id"):
                query_context.current_parameters[key] = value

        if not query_context.update_parameters:
            query_context.response_message = "수정할 정보를 말씀해주세요."
            query_context.pending_step = "waiting_parameters"
            return query_context
    # 2. 인자 확인
    if (query_context.pending_step == "waiting_parameters"):
        if not query_context.update_parameters:
            required_args = list(query_context.current_parameters.keys())
            update_args = await extract_update_parameters(query_type, user_text, required_args, request_time)
            if update_args.get("result") == "extract fail":
                query_context.response_message = "요청 내용을 분석하지 못했습니다. 다시 말씀해주세요."
                return query_context

            for key, value in update_args.items():
                if (key in query_context.current_parameters and key != "routine_group_id"):
                    query_context.update_parameters[key] = value

        if not query_context.update_parameters:
            query_context.response_message = "수정할 정보를 말씀해주세요."
            return query_context

        for key, value in query_context.update_parameters.items():
            if (key in query_context.current_parameters and key != "routine_group_id"):
                query_context.current_parameters[key] = value
    # 3. 수정튜플 충돌검사
    if (query_context.pending_step == "waiting_collision_decision"):
        decision = user_text.strip().replace(" ", "")
        if decision == "폐기":
            query_context.response_message = "루틴 수정을 종료하였습니다."
            query_context.pending_step = "done"
            return query_context
        if decision != "진행":
            query_context.response_message = "루틴 수정을 계속하려면 '진행', 수정하지 않으려면 '폐기'라고 말씀해주세요."
            return query_context
    else:
        collision_list = await get_collision(user_id, query_type, query_context.current_parameters)
        if (len(collision_list) > 0):
            query_context.response_message = await collision_decision_request(query_context.query_type, collision_list)
            query_context.pending_step = "waiting_collision_decision"
            return query_context
    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    if (db_result["status"] == "success"):
        query_context.response_message = "루틴 수정에 성공하였습니다."
    else:
        query_context.response_message = "db 오류로 인해 루틴 수정에 실패하였습니다."
    # 3. 삽입 성공 or 충돌 답변 반환
    query_context.pending_step = "done"
    return query_context

async def handle_schedule_delete(query_context: query_context.ScheduleQueryContext):
    user_id = query_context.user_id
    query_type = query_context.query_type
    user_text = query_context.user_text
    request_time = query_context.request_time
    if query_context.pending_step == "done":
        return query_context

    # 1-1. 타겟팅(현재기준 일정 존재하는 날짜 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_day"):
        target_date = query_context.targeting_parameters.get("target_date")
        if target_date is None and not query_context.target_candidates:
            day_info = await extract_dayinfo_from_text(query_type, user_text, request_time)
            target_date = day_info.get("target_date")
            if target_date is not None:
                query_context.targeting_parameters = {"target_date": target_date}
            else:
                day_result = await db_process.process_target_day_query(user_id, query_type, request_time)
                if day_result.get("status") != "success":
                    query_context.response_message = day_result.get("message", "일정 날짜 조회에 실패하였습니다.")
                    return query_context
                query_context.target_candidates = day_result.get("candidates", [])
                if not query_context.target_candidates:
                    query_context.response_message = "삭제할 일정이 존재하지 않습니다."
                    query_context.pending_step = "done"
                    return query_context
                query_context.response_message = await request_date_info(query_context.target_candidates)
                return query_context

        if target_date is None:
            candidate_index = get_candidate_index(user_text, len(query_context.target_candidates))
            if candidate_index is None:
                query_context.response_message = await request_date_info(query_context.target_candidates)
                return query_context
            target_date = query_context.target_candidates[candidate_index]
            query_context.targeting_parameters = {"target_date": target_date}

        target_result = await get_target_candidates(user_id, query_type, target_date, request_time)
        if target_result.get("status") != "success":
            query_context.response_message = target_result.get("message", "일정 후보 조회에 실패하였습니다.")
            return query_context
        query_context.target_candidates = target_result.get("candidates", [])
        if not query_context.target_candidates:
            query_context.response_message = "해당 날짜에는 삭제할 일정이 존재하지 않습니다."
            query_context.pending_step = "done"
            return query_context
        query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
        query_context.pending_step = "waiting_target"
        return query_context

    # 1-2. 타겟팅(해당 날짜의 일정 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        candidate_index = get_candidate_index(user_text, len(query_context.target_candidates))
        if candidate_index is None:
            query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
            return query_context
        target_schedule = query_context.target_candidates[candidate_index]
        query_context.selected_targets = [target_schedule]
        query_context.current_parameters = {"schedule_id": target_schedule["Schedule_ID"]}

    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    if db_result.get("status") == "success":
        query_context.response_message = "일정 삭제에 성공하였습니다."
    else:
        query_context.response_message = "db 오류로 인해 일정 삭제에 실패하였습니다."
    query_context.pending_step = "done"
    return query_context

async def handle_routine_delete(query_context: query_context.ScheduleQueryContext):
    user_id = query_context.user_id
    query_type = query_context.query_type
    user_text = query_context.user_text
    request_time = query_context.request_time
    if query_context.pending_step == "done":
        return query_context

    # 1-1. 타겟팅(유효한 루틴 존재하는 요일 후보 제공 후 선택)
    if (query_context.pending_step == "waiting_to_pick_weekday"):
        target_days = query_context.targeting_parameters.get("days_of_week")
        if target_days is None and not query_context.target_candidates:
            day_info = await extract_dayinfo_from_text(query_type, user_text, request_time)
            target_days = day_info.get("days_of_week")
            if target_days:
                query_context.targeting_parameters = {"days_of_week": target_days}
            else:
                day_result = await db_process.process_target_day_query(user_id, query_type, request_time)
                if day_result.get("status") != "success":
                    query_context.response_message = day_result.get("message", "루틴 요일 조회에 실패하였습니다.")
                    return query_context
                query_context.target_candidates = day_result.get("candidates", [])
                if not query_context.target_candidates:
                    query_context.response_message = "삭제할 루틴이 존재하지 않습니다."
                    query_context.pending_step = "done"
                    return query_context
                query_context.response_message = await request_weekday_info(query_context.target_candidates)
                return query_context

        if target_days is None:
            target_weekday = get_weekday_candidate(user_text, query_context.target_candidates)
            if target_weekday is None:
                query_context.response_message = await request_weekday_info(query_context.target_candidates)
                return query_context
            target_days = [target_weekday]
            query_context.targeting_parameters = {"days_of_week": target_days}

        target_result = await get_target_candidates(user_id, query_type, target_days, request_time)
        if target_result.get("status") != "success":
            query_context.response_message = target_result.get("message", "루틴 후보 조회에 실패하였습니다.")
            return query_context

        group_candidates = {}
        for candidate in target_result.get("candidates", []):
            group_candidates.setdefault(candidate["Routine_Group_ID"], candidate)
        query_context.target_candidates = list(group_candidates.values())
        if not query_context.target_candidates:
            query_context.response_message = "해당 요일에는 삭제할 루틴이 존재하지 않습니다."
            query_context.pending_step = "done"
            return query_context
        query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
        query_context.pending_step = "waiting_target"
        return query_context

    # 1-2. 타겟팅(해당 요일의 루틴 제공 후 선택)
    if (query_context.pending_step == "waiting_target"):
        candidate_index = get_candidate_index(user_text, len(query_context.target_candidates))
        if candidate_index is None:
            query_context.response_message = await request_targeting(query_type, query_context.target_candidates)
            return query_context
        target_routine = query_context.target_candidates[candidate_index]
        query_context.selected_targets = [target_routine]
        query_context.current_parameters = {"routine_group_id": target_routine["Routine_Group_ID"]}

    db_result = await db_process.process_db_query(user_id, query_type, query_context.current_parameters)
    if db_result.get("status") == "success":
        query_context.response_message = "루틴 삭제에 성공하였습니다."
    else:
        query_context.response_message = "db 오류로 인해 루틴 삭제에 실패하였습니다."
    query_context.pending_step = "done"
    return query_context
