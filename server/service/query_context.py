from dataclasses import field, dataclass
from typing import Any, Dict

@dataclass
class ScheduleQueryContext:
    """현재 하나의 일정 요청을 처리하는 동안 유지하는 작업 기억."""

    user_id: str
    request_time: str
    user_text: str
    query_type: int = -1
    current_parameters: Dict[str, Any] = field(default_factory=dict)
    targeting_parameters: Dict[str, Any] = field(default_factory=dict)
    target_candidates: list[Dict[str, Any]] = field(default_factory=list)
    selected_targets: list[Dict[str, Any]] = field(default_factory=list)
    conversation_history: list[Dict[str, str]] = field(default_factory=list)
    pending_step: str = "classification"
    result_status: str | None = None
    response_message: str | None = None

# pending_step 유형별 초기 매핑
next_step_mapping = {
    0: "waiting_parameters",
    1: "waiting_parameters",
    2: "waiting_parameters",
    3: "waiting_parameters",
    4: "waiting_to_pick_day",
    5: "waiting_to_pick_weekday",
    6: "waiting_to_pick_day",
    7: "waiting_to_pick_weekday"
}

# current_parameters 초기값 템플릿
parameter_templates = {
    0: {"target_date": None},
    1: {"start_time": None,
        "end_time": None},
    2: {
        "start_time": None,
        "end_time": None,
        "business": None,
        "location": None,
        "who": None
        },
    3: {
        "routine_group_id": None,
        "start_time": None,
        "end_time": None,
        "business": None,
        "location": None,
        "who": None,
        "days_of_week": None,
        "start_date": None,
        "end_date": None
        },
    4: {
        "schedule_id": None,
        "start_time": None,
        "end_time": None,
        "business": None,
        "location": None,
        "who": None
        },
    5: {
        "routine_group_id": None,
        "start_time": None,
        "end_time": None,
        "business": None,
        "location": None,
        "who": None,
        "days_of_week": None,
        "start_date": None,
        "end_date": None
        },
    6: {"schedule_id": None},
    7: {"routine_group_id": None}
}

# 필수 인자 누락 확인용 리스트
mandatory_parameters = {
    0: ["target_date"],
    1: [],
    2: ["start_time", "business"],
    3: ["start_time", "business", "days_of_week"],
    4: ["schedule_id", "start_time", "business"],
    5: ["routine_group_id", "start_time", "business", "days_of_week"],
    6: ["schedule_id"],
    7: ["routine_group_id"]
}

# 재질문용 선택인자 리스트
optional_parameters = {
    0: [],
    1: ["start_time", "end_time"],
    2: ["end_time", "location", "who"],
    3: ["end_time", "location", "who", "start_date", "end_date"],
    4: ["end_time", "location", "who"],
    5: ["end_time", "location", "who", "start_date", "end_date"],
    6: [],
    7: []
}

# 인자 추출용 템플릿
QUERY_PARAMETER_SPECS = {
    0: {
        "target_date": {
            "type": "string",
            "format": "YYYY-MM-DD",
            "description": "조회 대상 날짜"
        }
    },
    1: {
        "start_time": {
            "type": "string",
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "조회 시작 시각"
        },
        "end_time": {
            "type": "string",
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "조회 종료 시각"
        }
    },
    2: {
        "start_time": {
            "type": "string",
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "일정 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "일정 종료 시각"
        },
        "business": {
            "type": "string",
            "description": "일정 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "일정 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": "string",
            "description": "함께하는 사람들"
        }
    },
    3: {
        "start_time": {
            "type": "string",
            "format": "HH:MM:SS",
            "description": "루틴 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "HH:MM:SS",
            "description": "루틴 종료 시각"
        },
        "business": {
            "type": "string",
            "description": "루틴 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "루틴 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": "string",
            "description": "함께하는 사람들"
        },
        "days_of_week": {
            "type": "array",
            "items": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
            },
            "uniqueItems": True,
            "description": (
                "루틴이 시작하는 요일 목록. "
                "0=일요일, 1=월요일, 2=화요일, "
                "3=수요일, 4=목요일, 5=금요일, 6=토요일. "
                "예: 월수금은 [1, 3, 5]"
            )
        },
        "start_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "루틴 적용 시작일"
        },
        "end_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "루틴 적용 종료일"
        }
    },
    4: {
        "start_time": {
            "type": "string",
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "일정 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "일정 종료 시각"
        },
        "business": {
            "type": "string",
            "description": "일정 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "일정 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": "string",
            "description": "함께하는 사람들"
        }
    },
    5: {
        "start_time": {
            "type": "string",
            "format": "HH:MM:SS",
            "description": "루틴 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "HH:MM:SS",
            "description": "루틴 종료 시각"
        },
        "business": {
            "type": "string",
            "description": "루틴 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "루틴 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": "string",
            "description": "함께하는 사람들"
        },
        "days_of_week": {
            "type": "array",
            "items": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
            },
            "uniqueItems": True,
            "description": (
                "루틴이 시작하는 요일 목록. "
                "0=일요일, 1=월요일, 2=화요일, "
                "3=수요일, 4=목요일, 5=금요일, 6=토요일. "
                "예: 월수금은 [1, 3, 5]"
            )
        },
        "start_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "루틴 적용 시작일"
        },
        "end_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "루틴 적용 종료일"
        }
    }
}
