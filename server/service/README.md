# Service

이 폴더는 서버의 실제 비즈니스 로직을 담당합니다. 사용자 요청을 DB 작업으로 연결하고, 필요 시 언어 모델을 통해 자연어 응답을 생성합니다.

## 모듈 설명
### db_process.py
- 데이터베이스 접근, timeline 조회, 검증이 끝난 CRUD를 담당합니다.
- 자연어 문장이나 LLM 원문을 직접 받지 않습니다. 앞단 파이프라인이 아래 고정 계약에 맞는 값을 만든 뒤 호출해야 합니다.
- 기본값 생성, 필수 인자 재질문, 튜플 타겟팅, 최종 충돌 판정은 앞단 파이프라인의 책임입니다.
- INSERT와 전체 교체 UPDATE에서 전달되지 않은 선택 인자는 SQL NULL로 저장합니다.

#### 공통 호출 계약

```python
result = await process_db_query(
    user_id="user-1",
    query_type=0,
    query_args={"target_date": "2026-08-05"},
)
```

- `user_id`: `str`. 모든 유형에서 별도 위치 인자로 전달합니다.
- `query_type`: `int`. `0`부터 `7`까지만 허용합니다.
- `query_args`: `dict`. 유형별로 정해진 키만 구성하는 것을 원칙으로 합니다.
- 클라이언트와 파이프라인 사이의 canonical 형식은 아래 문자열 형식입니다. 내부 Python helper는 일부 `date`, `datetime`, `time` 객체도 받을 수 있지만 LLM 출력 계약에는 사용하지 않습니다.
- `None`은 SQL NULL을 뜻합니다.

|의미|canonical 자료형|형식 및 제약|
|:---|:---|:---|
|사용자 ID|`str`|비어 있지 않은 사용자 식별자|
|일정 ID|`int`|`schedule_id`|
|루틴 그룹 ID|`str`|`routine_group_id`, 현재 스키마 기준 최대 36자 UUID 문자열|
|날짜|`str`|`YYYY-MM-DD`|
|날짜와 시각|`str`|`YYYY-MM-DD HH:MM:SS`|
|하루 중 시각|`str`|`HH:MM:SS`|
|요일 목록|`list[int]`|`days_of_week`, 각 원소는 `0~6`; `0=일요일`, ..., `6=토요일`|
|내용|`str`|`business`, 비어 있지 않은 문자열|
|장소|`str \| None`|`location`|
|동반자|`list[str] \| None`|`who`; DB JSON으로 직렬화|

`days_of_week`는 빈 목록을 허용하지 않습니다. 정수 이외의 값, `bool`, 범위를 벗어난 값은 거부하며 중복은 제거하고 오름차순으로 저장합니다.

- `user_id`는 최대 50자, `business`와 `location`은 각각 최대 255자입니다.
- 일정의 명시적 `end_time`은 `start_time`보다 뒤여야 합니다.
- 루틴은 `end_time > start_time`이면 당일 종료, `end_time < start_time`이면 다음 날 종료이며 두 값이 같은 경우는 허용하지 않습니다.
- `start_date`와 `end_date`가 모두 존재하면 `start_date <= end_date`여야 합니다.

#### 쿼리 0~7 입력 계약

|유형|작업|`query_args` 필수 필드|선택 필드|DB 호출 전 파이프라인 책임|
|:---:|:---|:---|:---|:---|
|0|특정 일자 전체 조회|`target_date: str(date)`|없음|사용자 표현을 날짜 하나로 확정|
|1|특정 기간 전체 조회|`start_time: str(datetime)`, `end_time: str(datetime)`|없음|누락 기본값을 채우고 `start_time < end_time` 보장|
|2|일정 삽입|`start_time: str(datetime)`, `business: str`|`end_time: str(datetime) \| None`, `location: str \| None`, `who: list[str] \| None`|일정·루틴 충돌 검사 완료|
|3|루틴 삽입|`routine_group_id: str`, `start_time: str(time)`, `business: str`, `days_of_week: list[int]`|`end_time: str(time) \| None`, `location: str \| None`, `who: list[str] \| None`, `start_date: str(date) \| None`, `end_date: str(date) \| None`|UUID 생성, 날짜 범위와 일정·루틴 충돌 검사 완료|
|4|일정 전체 교체|`schedule_id: int`, `start_time: str(datetime)`, `business: str`|`end_time: str(datetime) \| None`, `location: str \| None`, `who: list[str] \| None`|대상 확정, 대상 일정 제외 후 충돌 검사 완료|
|5|루틴 그룹 전체 교체|`routine_group_id: str`, `start_time: str(time)`, `business: str`, `days_of_week: list[int]`|`end_time: str(time) \| None`, `location: str \| None`, `who: list[str] \| None`, `start_date: str(date) \| None`, `end_date: str(date) \| None`|대상 확정, 대상 그룹 제외 후 충돌 검사 완료|
|6|일정 삭제|`schedule_id: int`|없음|삭제 대상 확정|
|7|루틴 그룹 삭제|`routine_group_id: str`|없음|삭제 대상 확정|

1번의 `start_time`과 `end_time`은 DB 경계에서는 둘 다 필수입니다. 사용자가 생략할 수 있게 만들 경우 파이프라인이 다음 규칙 등을 적용해 값으로 만든 뒤 전달합니다.

- `start_time` 생략: 요청 시각
- `end_time` 생략: 요청일 다음 날 `00:00:00`

0번과 1번은 반열린 구간 `[start_time, end_time)`으로 조회합니다. 일정은 한 번 조회하고, 루틴은 날짜별 실제 발생분으로 변환한 뒤 날짜·시간순 timeline으로 합칩니다. 전날 시작해 자정을 넘긴 일정과 루틴도 범위에 걸치면 포함합니다.

3번은 `routine_group_id` 하나를 모든 요일별 행에 공통으로 사용합니다. 5번은 기존 그룹을 삭제한 뒤 동일한 `routine_group_id`로 새 요일별 행을 삽입하며, 전체 과정은 하나의 트랜잭션으로 처리됩니다. 4번과 5번은 전체 교체이므로 생략한 선택 필드는 기존 값을 유지하지 않고 NULL이 됩니다.

#### 쿼리 0~7 성공 반환 계약

|유형|성공 시 주요 반환값|
|:---:|:---|
|0|`status`, `query_type`, `target_date`, `range`, `timeline`|
|1|`status`, `query_type`, `range`, `timeline`|
|2|`status`, `query_type`, `data.schedule_id`|
|3|`status`, `query_type`, `data.routine_group_id`, `data.routine_ids`|
|4|`status`, `query_type`, `data.schedule_id`, `data.affected_rows`|
|5|`status`, `query_type`, `data.routine_group_id`, `data.deleted_rows`, `data.routine_ids`|
|6|`status`, `query_type`, `data.schedule_id`, `data.affected_rows`|
|7|`status`, `query_type`, `data.routine_group_id`, `data.affected_rows`|

조회 timeline의 공통 시각 형식은 `YYYY-MM-DD HH:MM:SS`입니다.

```python
# 일정 항목
{
    "type": "schedule",
    "id": 10,
    "business": "팀 회의",
    "start_time": "2026-08-05 10:00:00",
    "end_time": "2026-08-05 12:00:00",
    "end_time_inferred": False,
    "location": None,
    "who": ["철수"],
}

# 루틴 발생 항목
{
    "type": "routine",
    "id": 20,
    "routine_group_id": "UUID 문자열",
    "business": "수업",
    "start_time": "2026-08-05 23:00:00",
    "end_time": "2026-08-06 01:00:00",
    "end_time_inferred": False,
    "location": None,
    "who": None,
    "occurrence_date": "2026-08-05",
}
```

`end_time`이 NULL이면 조회와 충돌 판정에서 시작 후 2시간으로 계산되고 `end_time_inferred`가 `True`가 됩니다.

4·6·7번은 대상이 없어도 예외 대신 `affected_rows=0`인 성공 응답을 반환하므로 파이프라인이 이를 “대상 없음”으로 처리해야 합니다. 5번은 대상 그룹이 없으면 오류로 처리합니다.

실패 시에는 다음 형태를 반환하고 해당 트랜잭션을 rollback합니다.

```python
{
    "status": "error",
    "query_type": 3,
    "message": "DB 처리 중 에러 발생: ...",
}
```

#### 타겟팅·충돌 전처리 helper

아래 함수는 `process_db_query()`의 쿼리 유형이 아니라 파이프라인에서 사용하는 내부 helper입니다. 첫 번째 `conn` 인자는 활성 `aiomysql` 연결이며, 결과의 날짜·시각에는 DB 드라이버의 `date`, `datetime`, `timedelta` 같은 내부 자료형이 포함될 수 있으므로 클라이언트에 직접 반환하지 않습니다.

|함수|입력|반환|용도|
|:---|:---|:---|:---|
|`select_future_schedule_dates`|`user_id: str`, `reference_time: str(datetime)`|`list[str(date)]`|기준 시각 이후 일정이 걸치는 날짜 후보|
|`select_active_routine_weekdays`|`user_id: str`, `reference_time: str(datetime)`|`list[int]`|현재 진행 중이거나 미래 발생이 있는 루틴의 요일 후보|
|`select_routines_by_weekdays`|`user_id: str`, `days_of_week: list[int]`, `reference_time: str(datetime)`|`list[dict]`|선택 요일에 시작하거나 전날부터 넘어오는 루틴 후보|
|`select_overlapping_schedules`|`user_id: str`, `start_time: str(datetime)`, `end_time: str(datetime) \| None`, `excluded_schedule_id: int \| None`|`list[dict]`|일정 구간과 겹치는 단발성 일정 조회|
|`select_overlapping_routines`|`user_id: str`, `occurrence_date: str(date)`, `start_time: str(time)`, `end_time: str(time) \| None`, `excluded_group_id: str \| None`|`list[dict]`|특정 날짜의 한 발생 구간과 겹치는 루틴 조회|
|`select_schedules_for_routine_conflict`|`user_id: str`, `start_date: str(date) \| None`, `end_date: str(date) \| None`|`list[dict]`|새 루틴 유효 기간과 겹칠 수 있는 일정 후보 조회|
|`select_routines_for_recurrence_conflict`|`user_id: str`, `start_date: str(date) \| None`, `end_date: str(date) \| None`, `excluded_group_id: str \| None`|`list[dict]`|새 루틴과 유효 기간이 겹칠 수 있는 기존 루틴 후보 조회|

`select_schedules_for_routine_conflict`와 `select_routines_for_recurrence_conflict`는 false negative를 막기 위한 후보 조회입니다. 반환된 모든 행이 실제 충돌이라는 뜻은 아니며, 파이프라인이 요일·실제 발생일·시간 구간을 비교해 최종 판정해야 합니다. 구간이 정확히 맞닿기만 하는 경우는 충돌이 아닙니다.

### text_process.py
- 사용자의 자연어 질문을 분석해 DB 쿼리 인자를 생성하고, DB 결과를 다시 자연어로 변환합니다.
- 현재는 Ollama를 통해 LLM 응답을 받아 처리하는 구조입니다.
- LLM은 쿼리 유형 분류와 필드 후보 추출에만 사용합니다. 임의 형식의 값을 그대로 DB에 전달하지 않습니다.
- 추출 결과는 유형별 고정 스키마로 파싱하고 자료형·범위·필수 필드를 일반 코드로 검증합니다. 변환할 수 없는 입력은 재질문하거나 요청을 거부합니다.
- 기본값 계산, UUID 생성, 타겟 선택, 충돌 판정과 DB 호출 여부 결정은 결정론적인 프로그램 로직으로 처리합니다.
#### pending_step
0. 특정 일자 조회
classification
waiting_parameters
done

1. 특정 기간 조회
classification
waiting_parameters
done

2. 일정 삽입
classification
waiting_parameters
waiting_collision_decision
done

3. 루틴 삽입
classification
waiting_parameters
waiting_collision_decision
done

4. 일정 수정
classification
waiting_to_pick_day
waiting_target
waiting_parameters
waiting_collision_decision
done

5. 루틴 수정
classification
waiting_to_pick_weekday
waiting_target
waiting_parameters
waiting_collision_decision
done

6. 일정 삭제
classification
waiting_to_pick_day
waiting_target
done

7. 루틴 삭제
classification
waiting_to_pick_weekday
waiting_target
done

#### 타겟팅 원칙
- 일정 수정·삭제는 날짜를 선택한 뒤 해당 날짜에 걸치는 일정 후보에서 `schedule_id`를 확정합니다.
- 루틴 수정·삭제는 요일을 선택한 뒤 해당 요일에 걸치는 루틴을 그룹 후보로 묶어 `routine_group_id`를 확정합니다.
- 자정을 넘는 일정과 루틴은 시작 날짜·요일뿐 아니라 실제로 걸치는 다음 날짜·요일의 후보에도 포함합니다.
- `ScheduleQueryContext`는 현재 요청을 완료할 때까지만 유지하는 작업 기억입니다. 요청을 넘어서는 범용 비서의 장기 기억은 이 모듈의 범위가 아닙니다.

### audio_process.py
- 음성 입력을 자연어 텍스트로 변환해주는 파일

## 처리 흐름
1. 텍스트 요청이 들어오면 LLM이 쿼리 유형과 유형별 필드 후보를 추출합니다.
2. 프로그램이 후보 값을 고정 자료형으로 파싱하고 필수 필드·범위·기본값을 검증합니다.
3. 필요한 경우 재질문, 타겟팅과 충돌 검사를 수행합니다.
4. 검증 완료된 `user_id`, `query_type`, `query_args`만 db_process.py에 전달합니다.
5. db_process.py가 MySQL을 통해 일정 정보를 조회하거나 수정합니다.
6. 결과를 정해진 응답 구조로 변환한 뒤 자연어로 정리해 클라이언트에 반환합니다.

## 참고 사항
- DB 작업은 aiomysql 커넥션 풀을 사용해 비동기 처리됩니다.
