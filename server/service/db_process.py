# db_process.py
import aiomysql
import json
from datetime import date, datetime, time, timedelta

from database import connection

# ==========================================
# 1. SQL 쿼리 정의
# ==========================================

# [조회] 특정 일자의 전체 일정
# 입력: (user_id, day_end, day_start)
select_schedule_by_date_sql = """
    SELECT Schedule_ID, start_time, end_time, location, business, who
    FROM Schedule
    WHERE User_ID=%s
      AND start_time < %s
      AND COALESCE(end_time, DATE_ADD(start_time, INTERVAL 2 HOUR)) > %s
    ORDER BY start_time ASC;
"""

# [조회] 특정 날짜에 걸치는 루틴
# 입력: (target_date, user_id)
# day_offset=-1은 전날 시작해 target_date로 넘어온 루틴
select_routine_sql = """
    WITH params AS (
        SELECT CAST(%s AS DATE) AS target_date
    ),
    candidate_days AS (
        SELECT target_date AS occurrence_date, 0 AS day_offset
        FROM params
        UNION ALL
        SELECT DATE_SUB(target_date, INTERVAL 1 DAY), -1
        FROM params
    ),
    occurrences AS (
        SELECT r.*,
               d.occurrence_date,
               d.day_offset,
               COALESCE(
                   CASE
                       WHEN r.end_time < r.start_time
                           THEN TIME_TO_SEC(r.end_time) + 86400
                       ELSE TIME_TO_SEC(r.end_time)
                   END,
                   TIME_TO_SEC(r.start_time) + 7200
               ) AS occurrence_end_second
        FROM Routine AS r
        JOIN candidate_days AS d
          ON r.day_of_week = DAYOFWEEK(d.occurrence_date) - 1
        WHERE r.User_ID = %s
          AND (r.start_date IS NULL OR r.start_date <= d.occurrence_date)
          AND (r.end_date IS NULL OR r.end_date >= d.occurrence_date)
    )
    SELECT Routine_ID,
           Routine_Group_ID,
           start_time,
           end_time,
           location,
           business,
           who,
           occurrence_date,
           day_offset
    FROM occurrences
    WHERE day_offset = 0
       OR occurrence_end_second > 86400
    ORDER BY day_offset ASC, start_time ASC;
"""

# [조회] 특정 기간 일정 --> QUERY 1
select_schedule_range_sql = """
    SELECT Schedule_ID, start_time, end_time, location, business, who
    FROM Schedule
    WHERE User_ID = %s
      AND start_time < %s
      AND COALESCE(end_time, DATE_ADD(start_time, INTERVAL 2 HOUR)) > %s
    ORDER BY start_time ASC;
"""

# [삽입] 단발성 일정  --> QUERY 2
insert_schedule_sql = """
    INSERT INTO Schedule (User_ID, start_time, end_time, location, business, who)
    VALUES (%s, %s, %s, %s, %s, %s);
"""

# [삽입] 루틴 --> QUERY 3
insert_routine_sql = """
    INSERT INTO Routine (
        Routine_Group_ID,
        User_ID,
        start_time,
        end_time,
        location,
        business,
        who,
        day_of_week,
        start_date,
        end_date
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""

# [수정] 단발성 일정 --> QUERY 4
update_schedule_sql = """
    UPDATE Schedule
    SET start_time = %s,
        end_time = %s,
        location = %s,
        business = %s,
        who = %s
    WHERE Schedule_ID = %s AND User_ID = %s;
"""

# [삭제] 단발성 일정 --> QUERY 6
delete_schedule_sql = """
    DELETE FROM Schedule
    WHERE Schedule_ID = %s AND User_ID = %s;
"""

# [삭제] 루틴 그룹 --> QUERY 7
# 입력: (routine_group_id, user_id)
delete_routine_group_sql = """
    DELETE FROM Routine
    WHERE Routine_Group_ID = %s AND User_ID = %s;
"""

# [타겟팅] 지정한 요일에 걸치는 루틴 조회
# 입력: (days_of_week_json, reference_time, user_id)
# 요청 요일에 시작하는 루틴과 전날 시작해 요청 요일로 넘어오는 루틴을 모두 포함
# reference_time 이후에 실제 진행 중이거나 시작 가능한 발생분이 있는 루틴만 반환
select_routines_by_weekdays_sql = """
    WITH requested_days AS (
        SELECT DISTINCT requested_day
        FROM JSON_TABLE(
            %s,
            '$[*]' COLUMNS (
                requested_day TINYINT PATH '$'
            )
        ) AS requested
        WHERE requested_day BETWEEN 0 AND 6
    ),
    params AS (
        SELECT CAST(%s AS DATETIME) AS reference_time
    ),
    routine_bases AS (
        SELECT r.*,
               GREATEST(
                   DATE(p.reference_time),
                   COALESCE(r.start_date, DATE(p.reference_time))
               ) AS base_date,
               p.reference_time
        FROM Routine AS r
        CROSS JOIN params AS p
        WHERE r.User_ID = %s
    ),
    first_candidates AS (
        SELECT r.*,
               DATE_ADD(
                   r.base_date,
                   INTERVAL MOD(
                       r.day_of_week
                       - (DAYOFWEEK(r.base_date) - 1)
                       + 7,
                       7
                   ) DAY
               ) AS first_candidate_date
        FROM routine_bases AS r
    ),
    next_candidates AS (
        SELECT r.*,
               CASE
                   WHEN TIMESTAMPADD(
                            SECOND,
                            COALESCE(
                                CASE
                                    WHEN r.end_time < r.start_time
                                        THEN TIME_TO_SEC(r.end_time) + 86400
                                    ELSE TIME_TO_SEC(r.end_time)
                                END,
                                TIME_TO_SEC(r.start_time) + 7200
                            ),
                            CAST(r.first_candidate_date AS DATETIME)
                        ) <= r.reference_time
                       THEN DATE_ADD(r.first_candidate_date, INTERVAL 7 DAY)
                   ELSE r.first_candidate_date
               END AS candidate_date
        FROM first_candidates AS r
    ),
    future_occurrences AS (
        SELECT r.Routine_ID
        FROM next_candidates AS r
        WHERE r.end_date IS NULL OR r.end_date >= r.candidate_date

        UNION

        SELECT r.Routine_ID
        FROM routine_bases AS r
        WHERE r.day_of_week = DAYOFWEEK(
                  DATE_SUB(DATE(r.reference_time), INTERVAL 1 DAY)
              ) - 1
          AND (
              r.start_date IS NULL
              OR r.start_date <= DATE_SUB(
                     DATE(r.reference_time),
                     INTERVAL 1 DAY
                 )
          )
          AND (
              r.end_date IS NULL
              OR r.end_date >= DATE_SUB(
                     DATE(r.reference_time),
                     INTERVAL 1 DAY
                 )
          )
          AND TIMESTAMPADD(
                  SECOND,
                  COALESCE(
                      CASE
                          WHEN r.end_time < r.start_time
                              THEN TIME_TO_SEC(r.end_time) + 86400
                          ELSE TIME_TO_SEC(r.end_time)
                      END,
                      TIME_TO_SEC(r.start_time) + 7200
                  ),
                  CAST(
                      DATE_SUB(
                          DATE(r.reference_time),
                          INTERVAL 1 DAY
                      ) AS DATETIME
                  )
              ) > r.reference_time
    )
    SELECT r.Routine_ID,
           r.Routine_Group_ID,
           r.day_of_week,
           r.start_time,
           r.end_time,
           r.location,
           r.business,
           r.who,
           r.start_date,
           r.end_date
    FROM Routine AS r
    JOIN future_occurrences AS f
      ON f.Routine_ID = r.Routine_ID
    WHERE 1 = 1
      AND EXISTS (
          SELECT 1
          FROM requested_days AS d
          WHERE r.day_of_week = d.requested_day
             OR (
                 r.day_of_week = MOD(d.requested_day + 6, 7)
                 AND (
                     (
                         r.end_time IS NOT NULL
                         AND r.end_time < r.start_time
                         AND TIME_TO_SEC(r.end_time) > 0
                     )
                     OR (
                         r.end_time IS NULL
                         AND TIME_TO_SEC(r.start_time) + 7200 > 86400
                     )
                 )
             )
      )
    ORDER BY r.day_of_week ASC, r.start_time ASC, r.Routine_ID ASC;
"""

# [타겟팅] 현재 시각 이후 일정이 존재하는 날짜 후보 조회
# 입력: (reference_time, user_id)
# 여러 날에 걸친 일정은 실제로 걸치는 모든 날짜를 반환
select_future_schedule_dates_sql = """
    WITH RECURSIVE params AS (
        SELECT CAST(%s AS DATETIME) AS reference_time,
               %s AS user_id
    ),
    future_schedules AS (
        SELECT s.Schedule_ID,
               GREATEST(DATE(s.start_time), DATE(p.reference_time)) AS target_date,
               DATE(
                   DATE_SUB(
                       COALESCE(
                           s.end_time,
                           DATE_ADD(s.start_time, INTERVAL 2 HOUR)
                       ),
                       INTERVAL 1 MICROSECOND
                   )
               ) AS final_date
        FROM Schedule AS s
        CROSS JOIN params AS p
        WHERE s.User_ID = p.user_id
          AND COALESCE(
                  s.end_time,
                  DATE_ADD(s.start_time, INTERVAL 2 HOUR)
              ) > p.reference_time
    ),
    schedule_days AS (
        SELECT Schedule_ID, target_date, final_date
        FROM future_schedules
        WHERE target_date <= final_date

        UNION ALL

        SELECT Schedule_ID,
               DATE_ADD(target_date, INTERVAL 1 DAY),
               final_date
        FROM schedule_days
        WHERE target_date < final_date
    )
    SELECT DISTINCT target_date
    FROM schedule_days
    ORDER BY target_date ASC;
"""

# [타겟팅] 현재 또는 미래에 실제 발생 가능한 루틴이 걸치는 요일 후보 조회
# 입력: (reference_time, user_id)
# 자정을 넘는 루틴은 시작 요일과 다음 요일을 모두 반환
select_active_routine_weekdays_sql = """
    WITH params AS (
        SELECT CAST(%s AS DATETIME) AS reference_time
    ),
    routine_bases AS (
        SELECT r.*,
               GREATEST(
                   DATE(p.reference_time),
                   COALESCE(r.start_date, DATE(p.reference_time))
               ) AS base_date,
               p.reference_time
        FROM Routine AS r
        CROSS JOIN params AS p
        WHERE r.User_ID = %s
    ),
    first_candidates AS (
        SELECT r.*,
               DATE_ADD(
                   r.base_date,
                   INTERVAL MOD(
                       r.day_of_week
                       - (DAYOFWEEK(r.base_date) - 1)
                       + 7,
                       7
                   ) DAY
               ) AS first_candidate_date
        FROM routine_bases AS r
    ),
    next_candidates AS (
        SELECT r.*,
               CASE
                   WHEN TIMESTAMPADD(
                            SECOND,
                            COALESCE(
                                CASE
                                    WHEN r.end_time < r.start_time
                                        THEN TIME_TO_SEC(r.end_time) + 86400
                                    ELSE TIME_TO_SEC(r.end_time)
                                END,
                                TIME_TO_SEC(r.start_time) + 7200
                            ),
                            CAST(r.first_candidate_date AS DATETIME)
                        ) <= r.reference_time
                       THEN DATE_ADD(r.first_candidate_date, INTERVAL 7 DAY)
                   ELSE r.first_candidate_date
               END AS candidate_date
        FROM first_candidates AS r
    ),
    eligible_routines AS (
        SELECT r.Routine_ID
        FROM next_candidates AS r
        WHERE r.end_date IS NULL OR r.end_date >= r.candidate_date

        UNION

        SELECT r.Routine_ID
        FROM routine_bases AS r
        WHERE r.day_of_week = DAYOFWEEK(
                  DATE_SUB(DATE(r.reference_time), INTERVAL 1 DAY)
              ) - 1
          AND (
              r.start_date IS NULL
              OR r.start_date <= DATE_SUB(
                     DATE(r.reference_time),
                     INTERVAL 1 DAY
                 )
          )
          AND (
              r.end_date IS NULL
              OR r.end_date >= DATE_SUB(
                     DATE(r.reference_time),
                     INTERVAL 1 DAY
                 )
          )
          AND TIMESTAMPADD(
                  SECOND,
                  COALESCE(
                      CASE
                          WHEN r.end_time < r.start_time
                              THEN TIME_TO_SEC(r.end_time) + 86400
                          ELSE TIME_TO_SEC(r.end_time)
                      END,
                      TIME_TO_SEC(r.start_time) + 7200
                  ),
                  CAST(
                      DATE_SUB(
                          DATE(r.reference_time),
                          INTERVAL 1 DAY
                      ) AS DATETIME
                  )
              ) > r.reference_time
    ),
    active_routines AS (
        SELECT r.day_of_week,
               r.start_time,
               r.end_time
        FROM Routine AS r
        JOIN eligible_routines AS e
          ON e.Routine_ID = r.Routine_ID
    ),
    target_days AS (
        SELECT day_of_week AS target_day
        FROM active_routines

        UNION

        SELECT MOD(day_of_week + 1, 7) AS target_day
        FROM active_routines
        WHERE (
                  end_time IS NOT NULL
                  AND end_time < start_time
                  AND TIME_TO_SEC(end_time) > 0
              )
           OR (
               end_time IS NULL
               AND TIME_TO_SEC(start_time) + 7200 > 86400
           )
    )
    SELECT target_day
    FROM target_days
    ORDER BY target_day ASC;
"""

# [삽입] 유저
insert_user_info = """
    INSERT INTO User (ID, name)
    VALUES (%s, %s);
"""

# [충돌 검사] 신규/수정 일정(start, end)과 겹치는 기존 단발성 일정 조회
# 입력: (user_id, new_end_time, new_start_time, excluded_schedule_id)
# excluded_schedule_id가 None이면 모든 기존 일정을 검사
select_overlapping_schedules_sql = """
    SELECT Schedule_ID, start_time, end_time, location, business, who
    FROM Schedule
    WHERE User_ID = %s
      AND start_time < %s
      AND COALESCE(end_time, DATE_ADD(start_time, INTERVAL 2 HOUR)) > %s
      AND NOT (Schedule_ID <=> %s);
"""

# [충돌 후보] 신규/수정 루틴의 유효 기간에 걸치는 기존 일정 조회
# 입력: (new_start_date, new_end_date, user_id)
# 실제 요일/시간 충돌은 서비스 계층에서 발생 구간으로 변환해 판정
select_schedules_for_routine_conflict_sql = """
    WITH params AS (
        SELECT CAST(%s AS DATE) AS new_start_date,
               CAST(%s AS DATE) AS new_end_date
    )
    SELECT s.Schedule_ID,
           s.start_time,
           s.end_time,
           s.location,
           s.business,
           s.who
    FROM Schedule AS s
    CROSS JOIN params AS p
    WHERE s.User_ID = %s
      AND (
          p.new_start_date IS NULL
          OR COALESCE(
                 s.end_time,
                 DATE_ADD(s.start_time, INTERVAL 2 HOUR)
             ) > CAST(p.new_start_date AS DATETIME)
      )
      AND (
          p.new_end_date IS NULL
          OR s.start_time < DATE_ADD(p.new_end_date, INTERVAL 2 DAY)
      )
    ORDER BY s.start_time ASC;
"""

# [충돌 후보] 신규/수정 루틴과 유효 기간이 겹칠 수 있는 기존 루틴 조회
# 입력: (new_start_date, new_end_date, user_id, excluded_group_id)
# 하루를 넘기는 발생분까지 고려해 유효 기간 경계를 하루 확장하며,
# 실제 요일/시간 충돌은 서비스 계층에서 판정
select_routines_for_recurrence_conflict_sql = """
    WITH params AS (
        SELECT CAST(%s AS DATE) AS new_start_date,
               CAST(%s AS DATE) AS new_end_date
    )
    SELECT r.Routine_ID,
           r.Routine_Group_ID,
           r.start_time,
           r.end_time,
           r.location,
           r.business,
           r.who,
           r.day_of_week,
           r.start_date,
           r.end_date
    FROM Routine AS r
    CROSS JOIN params AS p
    WHERE r.User_ID = %s
      AND NOT (r.Routine_Group_ID <=> %s)
      AND (
          p.new_start_date IS NULL
          OR r.end_date IS NULL
          OR r.end_date >= DATE_SUB(p.new_start_date, INTERVAL 1 DAY)
      )
      AND (
          p.new_end_date IS NULL
          OR r.start_date IS NULL
          OR r.start_date <= DATE_ADD(p.new_end_date, INTERVAL 1 DAY)
      )
    ORDER BY r.day_of_week ASC, r.start_time ASC, r.Routine_ID ASC;
"""

# [충돌 검사] 특정 날짜에 시작하는 신규 루틴과 겹치는 기존 루틴 조회
# 입력: (occurrence_date, new_start_time, new_end_time, user_id, excluded_group_id)
# excluded_group_id가 None이면 모든 기존 루틴을 검사
# 기존 루틴의 전날/당일/다음 날 발생분을 초 단위의 연속된 구간으로 변환해 비교
select_overlapping_routines_sql = """
    WITH raw_params AS (
        SELECT CAST(%s AS DATE) AS occurrence_date,
               CAST(%s AS TIME) AS new_start_time,
               CAST(%s AS TIME) AS new_end_time
    ),
    params AS (
        SELECT occurrence_date,
               TIME_TO_SEC(new_start_time) AS new_start_second,
               COALESCE(
                   CASE
                       WHEN new_end_time < new_start_time
                           THEN TIME_TO_SEC(new_end_time) + 86400
                       ELSE TIME_TO_SEC(new_end_time)
                   END,
                   TIME_TO_SEC(new_start_time) + 7200
               ) AS new_end_second
        FROM raw_params
    ),
    candidate_days AS (
        SELECT DATE_SUB(occurrence_date, INTERVAL 1 DAY) AS routine_date,
               -86400 AS second_offset
        FROM params
        UNION ALL
        SELECT occurrence_date, 0
        FROM params
        UNION ALL
        SELECT DATE_ADD(occurrence_date, INTERVAL 1 DAY), 86400
        FROM params
    ),
    occurrences AS (
        SELECT r.*,
               d.routine_date,
               TIME_TO_SEC(r.start_time) + d.second_offset
                   AS occurrence_start_second,
               COALESCE(
                   CASE
                       WHEN r.end_time < r.start_time
                           THEN TIME_TO_SEC(r.end_time) + 86400
                       ELSE TIME_TO_SEC(r.end_time)
                   END,
                   TIME_TO_SEC(r.start_time) + 7200
               ) + d.second_offset AS occurrence_end_second
        FROM Routine AS r
        JOIN candidate_days AS d
          ON r.day_of_week = DAYOFWEEK(d.routine_date) - 1
        WHERE r.User_ID = %s
          AND NOT (r.Routine_Group_ID <=> %s)
          AND (r.start_date IS NULL OR r.start_date <= d.routine_date)
          AND (r.end_date IS NULL OR r.end_date >= d.routine_date)
    )
    SELECT Routine_ID,
           Routine_Group_ID,
           start_time,
           end_time,
           location,
           business,
           who
    FROM occurrences
    CROSS JOIN params
    WHERE occurrence_start_second < new_end_second
      AND occurrence_end_second > new_start_second
    ORDER BY occurrence_start_second ASC;
"""

# [삭제] end_time이 지난 단발성 일정 삭제 (end_time이 없으면 start_time 기준)
delete_expired_schedule_sql = """
    DELETE FROM Schedule
    WHERE COALESCE(end_time, DATE_ADD(start_time, INTERVAL 2 HOUR)) < NOW();
"""

# [삭제] 마지막 루틴 발생분의 실제 종료 시각이 지난 행 삭제
delete_expired_routine_sql = """
    DELETE FROM Routine
    WHERE end_date IS NOT NULL
      AND TIMESTAMPADD(
              SECOND,
              COALESCE(
                  CASE
                      WHEN end_time < start_time
                          THEN TIME_TO_SEC(end_time) + 86400
                      ELSE TIME_TO_SEC(end_time)
                  END,
                  TIME_TO_SEC(start_time) + 7200
              ),
              CAST(end_date AS DATETIME)
          ) <= NOW();
"""

# ==========================================
# 2. 값 변환 및 조회 결과 정규화
# ==========================================

DEFAULT_DURATION = timedelta(hours=2)
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_to_datetime(value) -> datetime:
    """MySQL DATETIME으로 사용할 값을 로컬 naive datetime으로 변환합니다."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"지원하지 않는 날짜/시간 형식입니다: {value}") from exc
    else:
        raise ValueError(f"날짜/시간 값이 필요합니다: {value!r}")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def parse_to_date(value) -> date:
    """DATE 또는 날짜 문자열을 date로 변환합니다."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"지원하지 않는 날짜 형식입니다: {value}") from exc
    raise ValueError(f"날짜 값이 필요합니다: {value!r}")


def parse_to_time(value) -> time:
    """MySQL TIME 반환값을 24시간제 시각으로 변환합니다."""
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        if not 0 <= total_seconds < 86400:
            raise ValueError(f"24시간제 시각 범위를 벗어났습니다: {value}")
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return time(hours, minutes, seconds)
    if isinstance(value, str):
        normalized = value.strip()
        try:
            return time.fromisoformat(normalized)
        except ValueError:
            if " " in normalized or "T" in normalized:
                return parse_to_datetime(normalized).time()
            raise ValueError(f"지원하지 않는 시간 형식입니다: {value}")
    raise ValueError(f"시간 값이 필요합니다: {value!r}")


def serialize_json(value):
    """JSON 컬럼에 저장할 값을 직렬화합니다. None은 SQL NULL로 유지합니다."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except json.JSONDecodeError:
            pass
    return json.dumps(value, ensure_ascii=False)


def deserialize_json(value):
    """MySQL JSON 문자열을 Python 값으로 복원합니다."""
    if value is None or not isinstance(value, (str, bytes, bytearray)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return value


def format_datetime(value: datetime) -> str:
    return value.strftime(DATETIME_FORMAT)


def routine_occurrence_bounds(row: dict) -> tuple[datetime, datetime, bool]:
    """루틴 조회 행을 실제 발생 시작/종료 DATETIME으로 변환합니다."""
    occurrence_date = parse_to_date(row["occurrence_date"])
    start_value = parse_to_time(row["start_time"])
    stored_end = row.get("end_time")
    occurrence_start = datetime.combine(occurrence_date, start_value)

    if stored_end is None:
        return occurrence_start, occurrence_start + DEFAULT_DURATION, True

    end_value = parse_to_time(stored_end)
    occurrence_end = datetime.combine(occurrence_date, end_value)
    if end_value < start_value:
        occurrence_end += timedelta(days=1)
    return occurrence_start, occurrence_end, False


def schedule_to_timeline_item(row: dict) -> tuple[datetime, dict]:
    occurrence_start = parse_to_datetime(row["start_time"])
    stored_end = row.get("end_time")
    inferred_end = stored_end is None
    occurrence_end = (
        occurrence_start + DEFAULT_DURATION
        if inferred_end
        else parse_to_datetime(stored_end)
    )
    item = {
        "type": "schedule",
        "id": row["Schedule_ID"],
        "business": row["business"],
        "start_time": format_datetime(occurrence_start),
        "end_time": format_datetime(occurrence_end),
        "end_time_inferred": inferred_end,
        "location": row.get("location"),
        "who": deserialize_json(row.get("who")),
    }
    return occurrence_start, item


def routine_to_timeline_item(row: dict) -> tuple[datetime, datetime, dict]:
    occurrence_start, occurrence_end, inferred_end = routine_occurrence_bounds(row)
    item = {
        "type": "routine",
        "id": row["Routine_ID"],
        "routine_group_id": row.get("Routine_Group_ID"),
        "business": row["business"],
        "start_time": format_datetime(occurrence_start),
        "end_time": format_datetime(occurrence_end),
        "end_time_inferred": inferred_end,
        "location": row.get("location"),
        "who": deserialize_json(row.get("who")),
        "occurrence_date": parse_to_date(row["occurrence_date"]).isoformat(),
    }
    return occurrence_start, occurrence_end, item


def iter_dates(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def normalize_days_of_week(value) -> list[int]:
    """요일 목록을 중복 없는 0~6 정수 목록으로 검증·정규화합니다."""
    if not isinstance(value, list):
        raise ValueError("days_of_week은 0부터 6까지 정수로 이루어진 목록이어야 합니다.")

    normalized = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError("days_of_week의 각 값은 0부터 6까지의 정수여야 합니다.")
        if item not in range(7):
            raise ValueError("days_of_week의 각 값은 0부터 6 사이여야 합니다.")
        if item not in normalized:
            normalized.append(item)

    if not normalized:
        raise ValueError("하나 이상의 요일이 필요합니다.")
    return sorted(normalized)


def normalize_db_rows(rows) -> list[dict]:
    """DictCursor 조회 행의 JSON 필드를 Python 값으로 복원합니다."""
    normalized = []
    for row in rows:
        item = dict(row)
        if "who" in item:
            item["who"] = deserialize_json(item.get("who"))
        normalized.append(item)
    return normalized


async def select_future_schedule_dates(
    conn,
    user_id: str,
    reference_time,
) -> list[str]:
    """현재 시각 이후 일정이 실제로 걸치는 날짜 후보를 반환합니다."""
    reference_dt = parse_to_datetime(reference_time)
    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(
            select_future_schedule_dates_sql,
            (reference_dt, user_id),
        )
        rows = await cur.fetchall()
    return [parse_to_date(row["target_date"]).isoformat() for row in rows]


async def select_active_routine_weekdays(
    conn,
    user_id: str,
    reference_time,
) -> list[int]:
    """현재 또는 미래에 유효한 루틴이 걸치는 요일 후보를 반환합니다."""
    reference_dt = parse_to_datetime(reference_time)
    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(
            select_active_routine_weekdays_sql,
            (reference_dt, user_id),
        )
        rows = await cur.fetchall()
    return [int(row["target_day"]) for row in rows]


async def select_routines_by_weekdays(
    conn,
    user_id: str,
    days_of_week: list[int],
    reference_time,
) -> list[dict]:
    """지정 요일에 시작하거나 전날부터 넘어오는 유효 루틴을 조회합니다."""
    normalized_days = normalize_days_of_week(days_of_week)
    reference_dt = parse_to_datetime(reference_time)
    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(
            select_routines_by_weekdays_sql,
            (json.dumps(normalized_days), reference_dt, user_id),
        )
        rows = await cur.fetchall()
    return normalize_db_rows(rows)


async def select_overlapping_schedules(
    conn,
    user_id: str,
    start_time,
    end_time=None,
    excluded_schedule_id=None,
) -> list[dict]:
    """일정 구간과 겹치는 기존 일정을 조회하며 수정 대상은 선택적으로 제외합니다."""
    start_dt = parse_to_datetime(start_time)
    end_dt = (
        start_dt + DEFAULT_DURATION
        if end_time is None
        else parse_to_datetime(end_time)
    )
    if start_dt >= end_dt:
        raise ValueError("일정 종료 시각은 시작 시각보다 뒤여야 합니다.")

    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(
            select_overlapping_schedules_sql,
            (user_id, end_dt, start_dt, excluded_schedule_id),
        )
        rows = await cur.fetchall()
    return normalize_db_rows(rows)


async def select_overlapping_routines(
    conn,
    user_id: str,
    occurrence_date,
    start_time,
    end_time=None,
    excluded_group_id=None,
) -> list[dict]:
    """특정 날짜의 새 루틴 발생분과 겹치는 기존 루틴을 조회합니다."""
    target_date = parse_to_date(occurrence_date)
    start_value = parse_to_time(start_time)
    end_value = None if end_time is None else parse_to_time(end_time)
    if end_value is not None and end_value == start_value:
        raise ValueError("루틴 종료 시각은 시작 시각과 같을 수 없습니다.")

    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(
            select_overlapping_routines_sql,
            (
                target_date,
                start_value,
                end_value,
                user_id,
                excluded_group_id,
            ),
        )
        rows = await cur.fetchall()
    return normalize_db_rows(rows)


async def select_schedules_for_routine_conflict(
    conn,
    user_id: str,
    start_date,
    end_date=None,
) -> list[dict]:
    """새 루틴 유효 기간에 충돌할 가능성이 있는 기존 일정 후보를 조회합니다."""
    normalized_start = None if start_date is None else parse_to_date(start_date)
    normalized_end = None if end_date is None else parse_to_date(end_date)
    if (
        normalized_start is not None
        and normalized_end is not None
        and normalized_start > normalized_end
    ):
        raise ValueError("루틴 종료 날짜는 시작 날짜보다 빠를 수 없습니다.")

    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(
            select_schedules_for_routine_conflict_sql,
            (normalized_start, normalized_end, user_id),
        )
        rows = await cur.fetchall()
    return normalize_db_rows(rows)


async def select_routines_for_recurrence_conflict(
    conn,
    user_id: str,
    start_date,
    end_date=None,
    excluded_group_id=None,
) -> list[dict]:
    """새 루틴과 충돌할 가능성이 있는 기존 반복 규칙 후보를 조회합니다."""
    normalized_start = None if start_date is None else parse_to_date(start_date)
    normalized_end = None if end_date is None else parse_to_date(end_date)
    if (
        normalized_start is not None
        and normalized_end is not None
        and normalized_start > normalized_end
    ):
        raise ValueError("루틴 종료 날짜는 시작 날짜보다 빠를 수 없습니다.")

    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(
            select_routines_for_recurrence_conflict_sql,
            (
                normalized_start,
                normalized_end,
                user_id,
                excluded_group_id,
            ),
        )
        rows = await cur.fetchall()
    return normalize_db_rows(rows)


async def select_timeline(
    conn,
    user_id: str,
    start_dt: datetime,
    end_dt: datetime,
    *,
    schedule_sql: str,
) -> list[dict]:
    """반열린 구간 [start_dt, end_dt)에 걸치는 일정과 루틴을 통합합니다."""
    if start_dt >= end_dt:
        raise ValueError("조회 종료 시각은 시작 시각보다 뒤여야 합니다.")

    timeline = []
    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(schedule_sql, (user_id, end_dt, start_dt))
        for row in await cur.fetchall():
            sort_key, item = schedule_to_timeline_item(row)
            timeline.append((sort_key, item))

        last_date = (end_dt - timedelta(microseconds=1)).date()
        seen_occurrences = set()
        for target_date in iter_dates(start_dt.date(), last_date):
            await cur.execute(select_routine_sql, (target_date, user_id))
            for row in await cur.fetchall():
                occurrence_date = parse_to_date(row["occurrence_date"])
                occurrence_key = (row["Routine_ID"], occurrence_date)
                if occurrence_key in seen_occurrences:
                    continue
                seen_occurrences.add(occurrence_key)

                occurrence_start, occurrence_end, item = routine_to_timeline_item(row)
                if occurrence_start < end_dt and occurrence_end > start_dt:
                    timeline.append((occurrence_start, item))

    timeline.sort(key=lambda entry: (entry[0], entry[1]["type"], entry[1]["id"]))
    return [item for _, item in timeline]


# ==========================================
# 3. 쿼리 유형 0~7 처리 함수
# ==========================================

async def select_day(conn, user_id: str, args: dict) -> dict:
    """0: 특정 일자의 전체 루틴과 일정을 조회합니다."""
    target_date = parse_to_date(args.get("target_date"))
    start_dt = datetime.combine(target_date, time.min)
    end_dt = start_dt + timedelta(days=1)
    timeline = await select_timeline(
        conn,
        user_id,
        start_dt,
        end_dt,
        schedule_sql=select_schedule_by_date_sql,
    )
    return {
        "status": "success",
        "query_type": 0,
        "target_date": target_date.isoformat(),
        "range": {
            "start_time": format_datetime(start_dt),
            "end_time": format_datetime(end_dt),
        },
        "timeline": timeline,
    }


async def select_range(conn, user_id: str, args: dict) -> dict:
    """1: 입력 범위 또는 요청 시점부터 요청 당일 자정까지 조회합니다."""
    start_dt = parse_to_datetime(args["start_time"])
    end_dt = parse_to_datetime(args["end_time"])
    timeline = await select_timeline(
        conn,
        user_id,
        start_dt,
        end_dt,
        schedule_sql=select_schedule_range_sql,
    )
    return {
        "status": "success",
        "query_type": 1,
        "range": {
            "start_time": format_datetime(start_dt),
            "end_time": format_datetime(end_dt),
        },
        "timeline": timeline,
    }


async def insert_schedule(conn, user_id: str, args: dict) -> dict:
    """2: 충돌 검사가 끝난 단발성 일정을 삽입합니다."""
    values = (
        user_id,
        args.get("start_time"),
        args.get("end_time"),
        args.get("location"),
        args.get("business"),
        serialize_json(args.get("who")),
    )
    async with conn.cursor() as cur:
        await cur.execute(insert_schedule_sql, values)
        schedule_id = cur.lastrowid
    return {
        "status": "success",
        "query_type": 2,
        "data": {"schedule_id": schedule_id},
    }


async def _insert_routine_rows(cur, user_id: str, args: dict) -> list[int]:
    """같은 그룹 ID로 요일별 루틴 행을 삽입하고 생성 ID 목록을 반환합니다."""
    routine_group_id = args.get("routine_group_id")
    if not isinstance(routine_group_id, str) or not routine_group_id.strip():
        raise ValueError("routine_group_id가 필요합니다.")

    days_of_week = normalize_days_of_week(args.get("days_of_week"))
    routine_ids = []
    for day_of_week in days_of_week:
        values = (
            routine_group_id,
            user_id,
            args.get("start_time"),
            args.get("end_time"),
            args.get("location"),
            args.get("business"),
            serialize_json(args.get("who")),
            day_of_week,
            args.get("start_date"),
            args.get("end_date"),
        )
        await cur.execute(insert_routine_sql, values)
        routine_ids.append(cur.lastrowid)
    return routine_ids


async def insert_routine(conn, user_id: str, args: dict) -> dict:
    """3: 충돌 검사가 끝난 다중 요일 루틴을 같은 그룹으로 삽입합니다."""
    async with conn.cursor() as cur:
        routine_ids = await _insert_routine_rows(cur, user_id, args)
    return {
        "status": "success",
        "query_type": 3,
        "data": {
            "routine_group_id": args["routine_group_id"],
            "routine_ids": routine_ids,
        },
    }


async def update_schedule(conn, user_id: str, args: dict) -> dict:
    """4: 타겟팅과 충돌 검사가 끝난 단발성 일정을 전체 교체합니다."""
    schedule_id = args.get("schedule_id")
    values = (
        args.get("start_time"),
        args.get("end_time"),
        args.get("location"),
        args.get("business"),
        serialize_json(args.get("who")),
        schedule_id,
        user_id,
    )
    async with conn.cursor() as cur:
        await cur.execute(update_schedule_sql, values)
        affected_rows = cur.rowcount
    return {
        "status": "success",
        "query_type": 4,
        "data": {
            "schedule_id": schedule_id,
            "affected_rows": affected_rows,
        },
    }


async def update_routine(conn, user_id: str, args: dict) -> dict:
    """5: 기존 루틴 그룹을 삭제하고 새 요일별 행으로 전체 교체합니다."""
    routine_group_id = args.get("routine_group_id")
    if not isinstance(routine_group_id, str) or not routine_group_id.strip():
        raise ValueError("routine_group_id가 필요합니다.")

    async with conn.cursor() as cur:
        await cur.execute(
            delete_routine_group_sql,
            (routine_group_id, user_id),
        )
        deleted_rows = cur.rowcount
        if deleted_rows == 0:
            raise LookupError("수정할 루틴 그룹을 찾을 수 없습니다.")
        routine_ids = await _insert_routine_rows(cur, user_id, args)
    return {
        "status": "success",
        "query_type": 5,
        "data": {
            "routine_group_id": routine_group_id,
            "deleted_rows": deleted_rows,
            "routine_ids": routine_ids,
        },
    }


async def delete_schedule(conn, user_id: str, args: dict) -> dict:
    """6: 타겟팅이 끝난 단발성 일정을 삭제합니다."""
    schedule_id = args.get("schedule_id")
    async with conn.cursor() as cur:
        await cur.execute(delete_schedule_sql, (schedule_id, user_id))
        affected_rows = cur.rowcount
    return {
        "status": "success",
        "query_type": 6,
        "data": {
            "schedule_id": schedule_id,
            "affected_rows": affected_rows,
        },
    }


async def delete_routine(conn, user_id: str, args: dict) -> dict:
    """7: 타겟팅이 끝난 루틴 그룹 전체를 삭제합니다."""
    routine_group_id = args.get("routine_group_id")
    async with conn.cursor() as cur:
        await cur.execute(
            delete_routine_group_sql,
            (routine_group_id, user_id),
        )
        affected_rows = cur.rowcount
    return {
        "status": "success",
        "query_type": 7,
        "data": {
            "routine_group_id": routine_group_id,
            "affected_rows": affected_rows,
        },
    }


QUERY_HANDLERS = {
    0: select_day,
    1: select_range,
    2: insert_schedule,
    3: insert_routine,
    4: update_schedule,
    5: update_routine,
    6: delete_schedule,
    7: delete_routine,
}

async def get_schedule_collision_candidates(conn, user_id, args):
    start_dt = parse_to_datetime(args.get("start_time"))
    end_dt = (
        None
        if args.get("end_time") is None
        else parse_to_datetime(args.get("end_time"))
    )
    schedules = await select_overlapping_schedules(
        conn,
        user_id,
        start_dt,
        end_dt,
    )
    routines = await select_overlapping_routines(
        conn,
        user_id,
        start_dt.date(),
        start_dt.time(),
        None if end_dt is None else end_dt.time(),
    )
    return {
        "status": "success",
        "schedules": schedules,
        "routines": routines,
    }

async def get_routine_collision_candidates(conn, user_id, args):
    schedules = await select_schedules_for_routine_conflict(
        conn,
        user_id,
        args.get("start_date"),
        args.get("end_date"),
    )
    routines = await select_routines_for_recurrence_conflict(
        conn,
        user_id,
        args.get("start_date"),
        args.get("end_date"),
    )
    return {
        "status": "success",
        "schedules": schedules,
        "routines": routines,
    }

COLLISION_HANDLERS = {
    2: get_schedule_collision_candidates,
    3: get_routine_collision_candidates,
    4: get_schedule_collision_candidates,
    5: get_routine_collision_candidates
}

# ==========================================
# 4. 통합 엔트리 포인트 및 정기 청소
# ==========================================

async def process_db_query(user_id: str, query_type: int, query_args: dict) -> dict:
    handler = QUERY_HANDLERS.get(query_type)
    if handler is None:
        return {"status": "error", "message": "알 수 없는 쿼리 타입입니다."}
    if connection.db_pool is None:
        return {"status": "error", "message": "DB 연결 풀이 초기화되지 않았습니다."}

    async with connection.db_pool.acquire() as conn:
        try:
            result = await handler(conn, user_id, query_args or {})
            await conn.commit()
            return result
        except Exception as exc:
            await conn.rollback()
            return {
                "status": "error",
                "query_type": query_type,
                "message": f"DB 처리 중 에러 발생: {exc}",
            }

async def process_collision_query(user_id: str, query_type: int, query_args: dict) -> dict:
    handler = COLLISION_HANDLERS.get(query_type)
    if handler is None:
        return {"status": "error", "message": "알 수 없는 쿼리 타입입니다."}
    if connection.db_pool is None:
        return {"status": "error", "message": "DB 연결 풀이 초기화되지 않았습니다."}
    
    async with connection.db_pool.acquire() as conn:
        try:
            result = await handler(conn, user_id, query_args or {})
            return result
        except Exception as exc:
            await conn.rollback()
            return {
                "status": "error",
                "query_type": query_type,
                "message": f"충돌 검사 중 에러 발생: {exc}",
            }

async def cleanup_expired_data() -> dict:
    """백그라운드에서 정기적으로 실행되어 만료된 일정 및 루틴을 청소합니다."""
    if connection.db_pool is None:
        return {"status": "error", "message": "DB 연결 풀이 초기화되지 않았습니다."}

    async with connection.db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(delete_expired_schedule_sql)
                deleted_schedules = cur.rowcount
                await cur.execute(delete_expired_routine_sql)
                deleted_routines = cur.rowcount
                await conn.commit()
                return {
                    "status": "success",
                    "deleted_schedules": deleted_schedules,
                    "deleted_routines": deleted_routines,
                }
            except Exception as exc:
                await conn.rollback()
                return {"status": "error", "message": f"정기 청소 중 에러 발생: {exc}"}
