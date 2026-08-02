from dataclasses import field, dataclass
from typing import Any, Dict

@dataclass
class ScheduleQueryContext:
    user_id: str
    request_time: str
    user_text: str
    query_type: int = -1  # 초기값은 -1로 설정 (분류되지 않은 상태)
    current_parameters: Dict[str, Any] = field(default_factory=dict)
    pending_step: str = "classification"  # 초기 단계는 분류 단계로 설정
    response_message: str | None = None