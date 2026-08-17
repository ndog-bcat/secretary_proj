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
    update_parameters: Dict[str, Any] = field(default_factory=dict)
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
    4: "waiting_initial_extraction",
    5: "waiting_initial_extraction",
    6: "waiting_to_pick_day",
    7: "waiting_to_pick_weekday"
}

# 인자 요청시 사용할 딕셔너리
parameter_request_mapping = {}

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

# 0~3번 조회·삽입 요청에서 DB 실행 정보를 직접 추출할 때 사용하는 스펙
DIRECT_PARAMETER_SPECS = {
    0: {
        "target_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "조회 대상 날짜"
        }
    },
    1: {
        "start_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "조회 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "조회 종료 시각"
        }
    },
    2: {
        "start_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "일정 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "일정 종료 시각"
        },
        "business": {
            "type": ["string", "null"],
            "description": "일정 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "일정 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "함께하는 사람들"
        }
    },
    3: {
        "start_time": {
            "type": ["string", "null"],
            "format": "HH:MM:SS",
            "description": "루틴 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "HH:MM:SS",
            "description": "루틴 종료 시각"
        },
        "business": {
            "type": ["string", "null"],
            "description": "루틴 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "루틴 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "함께하는 사람들"
        },
        "days_of_week": {
            "type": ["array", "null"],
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

# 4~7번 수정·삭제 요청에서 후보 목록을 조회하기 위한 스펙
# 일정은 날짜, 루틴은 요일만으로 후보를 조회한다. 나머지 표현으로 후보를
# 미리 필터링하지 않으며 실제 ID는 사용자의 후보 선택 후 서버가 확정한다.
TARGETING_PARAMETER_SPECS = {
    4: {
        "target_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "수정할 일정 후보를 조회할 날짜"
        }
    },
    5: {
        "days_of_week": {
            "type": ["array", "null"],
            "items": {"type": "integer", "minimum": 0, "maximum": 6},
            "uniqueItems": True,
            "description": "수정할 루틴 후보를 조회할 시작 요일 목록"
        }
    },
    6: {
        "target_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "삭제할 일정 후보를 조회할 날짜"
        }
    },
    7: {
        "days_of_week": {
            "type": ["array", "null"],
            "items": {"type": "integer", "minimum": 0, "maximum": 6},
            "uniqueItems": True,
            "description": "삭제할 루틴 후보를 조회할 시작 요일 목록"
        }
    }
}

# 4~5번 수정 요청에서 선택된 기존 데이터 위에 덮어쓸 값의 추출 스펙
# 키가 없으면 기존 값을 유지한다. 명시적인 null은 nullable 필드 제거 요청을 뜻한다.
# schedule_id/routine_group_id는 서버가 별도로 넣는다.
UPDATE_PARAMETER_SPECS = {
    4: {
        "start_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "변경할 일정 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD HH:MM:SS",
            "description": "변경할 일정 종료 시각"
        },
        "business": {
            "type": ["string", "null"],
            "description": "변경할 일정 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "변경할 일정 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "변경할 일정에 함께하는 사람들"
        }
    },
    5: {
        "start_time": {
            "type": ["string", "null"],
            "format": "HH:MM:SS",
            "description": "변경할 루틴 시작 시각"
        },
        "end_time": {
            "type": ["string", "null"],
            "format": "HH:MM:SS",
            "description": "변경할 루틴 종료 시각"
        },
        "business": {
            "type": ["string", "null"],
            "description": "변경할 루틴 내용"
        },
        "location": {
            "type": ["string", "null"],
            "description": "변경할 루틴 장소"
        },
        "who": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "변경할 루틴에 함께하는 사람들"
        },
        "days_of_week": {
            "type": ["array", "null"],
            "items": {"type": "integer", "minimum": 0, "maximum": 6},
            "uniqueItems": True,
            "description": "변경 후 루틴 시작 요일 목록"
        },
        "start_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "변경할 루틴 적용 시작일"
        },
        "end_date": {
            "type": ["string", "null"],
            "format": "YYYY-MM-DD",
            "description": "변경할 루틴 적용 종료일"
        }
    }
}

# 각 단계에서 사용할 빈 컨테이너 템플릿
targeting_parameter_templates = {
    query_type: {key: None for key in spec}
    for query_type, spec in TARGETING_PARAMETER_SPECS.items()
}

update_parameter_templates = {
    query_type: {}
    for query_type in UPDATE_PARAMETER_SPECS
}
