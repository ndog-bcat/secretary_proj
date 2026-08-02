from dataclasses import field, dataclass
from typing import Any, Dict

@dataclass
class ScheduleQueryContext:
    user_id: str
    request_time: str
    user_text: str
    current_parameters: Dict[str, Any] = field(default_factory=dict)
    pending_step: str = "classification"  # 초기 단계는 분류 단계로 설정