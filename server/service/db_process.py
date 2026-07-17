# db_process.py
from database.connection import db_pool
import aiomysql
from datetime import datetime, time, timedelta

# ==========================================
# 1. SQL 쿼리 정의
# ==========================================

# [조회] 특정 시점 이후 일정
select_schedule_sql = """
    SELECT Schedule_ID, start_time, end_time, location, business
    FROM Schedule
    WHERE User_ID = %s AND start_time >= %s
    ORDER BY start_time ASC;
"""

# [조회] 특정 기간 일정
select_schedule_range_sql = """
    SELECT Schedule_ID, start_time, end_time, location, business
    FROM Schedule
    WHERE User_ID = %s AND start_time >= %s AND start_time <= %s
    ORDER BY start_time ASC;
"""

# [조회] 특정 일자의 전체 일정
select_schedule_by_date_sql = """
    SELECT Schedule_ID, start_time, end_time, location, business
    FROM Schedule
    WHERE User_ID = %s AND DATE(start_time) = DATE(%s)
    ORDER BY start_time ASC;
"""

# [조회] 특정 요일 반복 일정
select_routine_sql = """
    SELECT Routine_ID, business, start_time, end_time, location
    FROM Routine
    WHERE User_ID = %s AND day_of_week = %s
    ORDER BY start_time ASC;
"""

# [충돌 검사] 신규 일정(start, end)과 겹치는 기존 단발성 일정 조회 (자정 걸침 문제 완벽 해결)
select_overlapping_schedules_sql = """
    SELECT Schedule_ID, start_time, end_time, location, business
    FROM Schedule
    WHERE User_ID = %s 
      AND start_time < %s 
      AND COALESCE(end_time, DATE_ADD(start_time, INTERVAL 1 HOUR)) > %s;
"""

# [삽입] 단발성 일정
insert_schedule_sql = """
    INSERT INTO Schedule (User_ID, start_time, end_time, location, business)
    VALUES (%s, %s, %s, %s, %s);
"""

# [삽입] 반복 일정
insert_routine_sql = """
    INSERT INTO Routine (User_ID, business, day_of_week, start_time, end_time, end_date, location)
    VALUES (%s, %s, %s, %s, %s, %s, %s);
"""

# [수정] 단발성 일정
update_schedule_sql = """
    UPDATE Schedule
    SET start_time = %s, end_time = %s, location = %s, business = %s
    WHERE Schedule_ID = %s AND User_ID = %s;
"""

# [추적] 닉네임 기반 친구 추적
trace_friend_by_nickname_sql = """
    SELECT DISTINCT f.Friend_ID, f.name 
    FROM Friend f
    LEFT JOIN Nickname n ON f.Friend_ID = n.Friend_ID
    WHERE f.User_ID = %s AND (f.name = %s OR n.nickname = %s);
"""

# [추적] 일정 기반 친구 추적
trace_friend_by_schedule_sql = """
    SELECT f.Friend_ID, f.name
    FROM Schedule s
    JOIN To_meet tm ON s.Schedule_ID = tm.Schedule_ID
    JOIN Friend f ON tm.Friend_ID = f.Friend_ID
    WHERE s.User_ID = %s AND (s.location LIKE %s OR s.business LIKE %s)
    ORDER BY s.start_time DESC
    LIMIT 1;
"""

# [지인 매핑] To_meet 테이블 관계 주입
insert_to_meet_sql = """
    INSERT INTO To_meet (Schedule_ID, Friend_ID)
    VALUES (%s, %s);
"""

# [삭제] end_time이 지난 단발성 일정 삭제 (end_time이 없으면 start_time 기준)
delete_expired_schedule_sql = """
    DELETE FROM Schedule 
    WHERE (end_time IS NOT NULL AND end_time < NOW())
       OR (end_time IS NULL AND start_time < DATE_SUB(NOW(), INTERVAL 1 DAY));
"""

# [삭제] end_date 기간이 만료된 반복 일정 삭제
delete_expired_routine_sql = """
    DELETE FROM Routine 
    WHERE end_date IS NOT NULL AND end_date < CURDATE();
"""


# ==========================================
# 2. 타입 안전성(Type Safety) 보장 헬퍼 함수
# ==========================================

def parse_to_datetime(val) -> datetime:
    """다양한 타입의 입력을 안전하게 datetime 객체로 변환합니다."""
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        raise ValueError(f"지원하지 않는 날짜/시간 형식입니다: {val}")
    return val

def parse_to_time(val) -> time:
    """문자열, timedelta, datetime 등에서 안전하게 time 객체를 추출합니다."""
    if isinstance(val, str):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(val, fmt).time()
            except ValueError:
                continue
        if " " in val:
            return parse_to_datetime(val).time()
        raise ValueError(f"지원하지 않는 시간 형식입니다: {val}")
    elif isinstance(val, timedelta):
        total_seconds = int(val.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return time(hours, minutes, seconds)
    elif isinstance(val, datetime):
        return val.time()
    elif isinstance(val, time):
        return val
    return val


# ==========================================
# 3. 비즈니스 로직 서브 함수
# ==========================================

async def select_flexible_schedule(conn, user_id: str, args: dict) -> dict:
    """
    query_type == 0: 유저의 질문 시점에 맞춰 시작/종료 시점의 디폴트를 조절하는 유연한 타임라인 조회
    - start_time 미지정 시: 현재 시간(Now) 디폴트
    - end_time 미지정 시: 시작 시간 날짜의 당일 '23:59:59' 디폴트
    """
    now = datetime.now()
    
    start_time_input = args.get("start_time")
    end_time_input = args.get("end_time")
    
    # 1. 시작 시간(start_time) 설정
    start_dt = parse_to_datetime(start_time_input) if start_time_input else now
        
    # 2. 종료 시간(end_time) 설정
    if end_time_input:
        end_dt = parse_to_datetime(end_time_input)
    else:
        # "이따 5시에 뭐 해야 돼?" 또는 당일 남은 일정 조회를 위해 시작일의 밤 11시 59분 59초로 자동 설정
        end_dt = datetime.combine(start_dt.date(), time(23, 59, 59))
        
    async with conn.cursor(aiomysql.DictCursor) as cur:
        # 3. 설정된 범위 안의 단발성 일정 조회
        await cur.execute(select_schedule_range_sql, (user_id, start_dt, end_dt))
        schedules = await cur.fetchall()
        
        # 4. 고정 루틴 조회 (시작 시간의 요일 기준)
        python_weekday = start_dt.weekday()
        db_day_of_week = (python_weekday + 1) % 7
        
        await cur.execute(select_routine_sql, (user_id, db_day_of_week))
        routines = await cur.fetchall()
        
        combined_timeline = []
        
        # 일회성 일정 추가
        for s in schedules:
            combined_timeline.append({
                "type": "one-time",
                "id": s["Schedule_ID"],
                "title": s["business"],
                "start": s["start_time"].strftime("%H:%M"),
                "end": s["end_time"].strftime("%H:%M") if s["end_time"] else None,
                "location": s["location"],
                "full_start_time": s["start_time"].strftime("%Y-%m-%d %H:%M:%S")
            })
            
        # 고정 루틴 시간 필터링
        start_tm = start_dt.time()
        end_tm = end_dt.time()
        
        for r in routines:
            r_start = parse_to_time(r["start_time"])
            r_end = parse_to_time(r["end_time"]) if r["end_time"] else None
            
            # 같은 날짜 안에서 조회하는 경우, 범위 필터링 적용
            if start_dt.date() == end_dt.date():
                r_end_effective = r_end if r_end else (datetime.combine(datetime.min, r_start) + timedelta(hours=1)).time()
                # 겹침 감지 공식: 루틴이 끝나기 전이고 요청 시간 종료 전에 루틴이 시작하는 경우
                if not (r_start <= end_tm and r_end_effective >= start_tm):
                    continue
            else:
                # 다중 날짜(Cross-day) 조회 시, 당일(start_dt) 기준의 루틴만 안전하게 필터링
                r_end_effective = r_end if r_end else (datetime.combine(datetime.min, r_start) + timedelta(hours=1)).time()
                if not (r_end_effective >= start_tm):
                    continue
                    
            combined_timeline.append({
                "type": "routine",
                "id": r["Routine_ID"],
                "title": f"[고정] {r['business']}",
                "start": r_start.strftime("%H:%M"),
                "end": r_end.strftime("%H:%M") if r_end else None,
                "location": r["location"],
                "full_start_time": f"{start_dt.strftime('%Y-%m-%d')} {r_start.strftime('%H:%M:%S')}"
            })

        # 5. 최종 결합된 타임라인을 시간 순서대로 정렬 (가장 가까운 일정이 인덱스 0번으로 오도록)
        combined_timeline.sort(key=lambda x: x["full_start_time"])

        return {
            "status": "success",
            "search_range": {
                "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end_dt.strftime("%Y-%m-%d %H:%M:%S")
            },
            "timeline": combined_timeline
        }

async def select_integrated_schedule(conn, user_id: str, args: dict) -> dict:
    target_date_str = args.get("target_date")  # YYYY-MM-DD 형식
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
    
    python_weekday = target_date.weekday()
    db_day_of_week = (python_weekday + 1) % 7 

    async with conn.cursor(aiomysql.DictCursor) as cur:
        # 1. 특정 날짜 일회성 일정 조회 (하루 전체 일정을 정확하게 타겟팅)
        await cur.execute(select_schedule_by_date_sql, (user_id, target_date_str))
        schedules = await cur.fetchall()

        # 2. 고정 루틴 조회
        await cur.execute(select_routine_sql, (user_id, db_day_of_week))
        routines = await cur.fetchall()

        combined_timeline = []
        
        for s in schedules:
            combined_timeline.append({
                "type": "one-time",
                "id": s["Schedule_ID"],
                "title": s["business"],
                "start": s["start_time"].strftime("%H:%M"),
                "end": s["end_time"].strftime("%H:%M") if s["end_time"] else None,
                "location": s["location"]
            })
            
        for r in routines:
            r_start = parse_to_time(r["start_time"])
            r_end = parse_to_time(r["end_time"]) if r["end_time"] else None
            
            combined_timeline.append({
                "type": "routine",
                "id": r["Routine_ID"],
                "title": f"[고정] {r['business']}",
                "start": r_start.strftime("%H:%M"),
                "end": r_end.strftime("%H:%M") if r_end else None,
                "location": r["location"]
            })

        # 시작 시간 기준으로 정렬
        combined_timeline.sort(key=lambda x: x["start"])

        return {
            "status": "success",
            "date": target_date_str,
            "timeline": combined_timeline
        }

async def check_conflicts_opt(conn, user_id: str, start_time_str: str, end_time_str: str, day_of_week: int, exclude_schedule_id: int = None) -> list:
    """[최적화] DB 인덱스를 타서 기존 오버랩 일정과 루틴을 한 번에 가져와 정확하게 충돌 감지"""
    combined_conflicts = []
    
    # 입력 파싱
    try:
        new_start_dt = parse_to_datetime(start_time_str)
        new_end_dt = parse_to_datetime(end_time_str) if end_time_str else new_start_dt + timedelta(hours=1)
        has_date = True
    except ValueError:
        has_date = False

    new_start_time = parse_to_time(start_time_str)
    new_end_time = parse_to_time(end_time_str) if end_time_str else (datetime.combine(datetime.min, new_start_time) + timedelta(hours=1)).time()
    
    async with conn.cursor(aiomysql.DictCursor) as cur:
        # 1. 일회성 일정 충돌 조회 (SQL 레벨에서 겹치는 자정 걸침 데이터까지 한방에 검색)
        if has_date:
            await cur.execute(select_overlapping_schedules_sql, (user_id, new_end_dt, new_start_dt))
            overlapping_schedules = await cur.fetchall()
            
            for s in overlapping_schedules:
                # 현재 수정 대상인 일정 자체는 중복 검사 제외
                if exclude_schedule_id and s["Schedule_ID"] == exclude_schedule_id:
                    continue
                combined_conflicts.append({
                    "type": "one-time",
                    "id": s["Schedule_ID"],
                    "title": s["business"],
                    "start": s["start_time"].strftime("%H:%M"),
                    "end": s["end_time"].strftime("%H:%M") if s["end_time"] else None,
                    "location": s["location"]
                })
        
        # 2. 고정 루틴 충돌 검사
        if day_of_week is not None:
            await cur.execute(select_routine_sql, (user_id, day_of_week))
            existing_routines = await cur.fetchall()
            
            for r in existing_routines:
                r_start = parse_to_time(r['start_time'])
                r_end = parse_to_time(r['end_time']) if r['end_time'] else None
                if not r_end:
                    r_end = (datetime.combine(datetime.min, r_start) + timedelta(hours=1)).time()
                    
                if r_start < new_end_time and r_end > new_start_time:
                    combined_conflicts.append({
                        "type": "routine",
                        "id": r["Routine_ID"],
                        "title": f"[고정] {r['business']}",
                        "start": r_start.strftime("%H:%M"),
                        "end": r_end.strftime("%H:%M"),
                        "location": r["location"]
                    })
                
    return combined_conflicts

async def insert_schedule(conn, user_id: str, args: dict) -> dict:
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    location = args.get("location")
    business = args.get("business")
    who_list = args.get("who", []) 

    target_dt = parse_to_datetime(start_time)
    python_weekday = target_dt.weekday()
    db_day_of_week = (python_weekday + 1) % 7 # 요일 보정

    # 1. 삽입 전 최적화된 충돌 검사 실행
    combined_conflicts = await check_conflicts_opt(conn, user_id, start_time, end_time, db_day_of_week)
    if combined_conflicts:
        return {
            "status": "error",
            "message": "해당 시간대에 이미 일정이 존재합니다.",
            "conflicts": combined_conflicts
        }

    async with conn.cursor() as cur:
        # 2. 일정 추가
        await cur.execute(insert_schedule_sql, (user_id, start_time, end_time, location, business))
        schedule_id = cur.lastrowid  # 방금 생성된 Schedule_ID 획득
        
        # 3. 지인 매핑 진행 (who_list가 존재할 때)
        mapped_friends = []
        if who_list:
            for name_or_nick in who_list:
                await cur.execute(trace_friend_by_nickname_sql, (user_id, name_or_nick, name_or_nick))
                friend_row = await cur.fetchone()
                if friend_row:
                    friend_id, friend_name = friend_row
                    await cur.execute(insert_to_meet_sql, (schedule_id, friend_id))
                    mapped_friends.append(friend_name)

        return {
            "status": "success",
            "message": "일정이 성공적으로 등록되었습니다.",
            "data": {
                "schedule_id": schedule_id,
                "business": business,
                "mapped_friends": mapped_friends
            }
        }

async def insert_routine(conn, user_id: str, args: dict) -> dict:
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    location = args.get("location")
    business = args.get("business")
    day_of_week = args.get("day_of_week")  # 요일 (0=일요일, 1=월요일, ..., 6=토요일)
    end_date = args.get("end_date", None)  # 종료 날짜

    # 삽입 전 루틴 간 충돌만 가볍게 필터링
    combined_conflicts = await check_conflicts_opt(conn, user_id, start_time, end_time, day_of_week)
    routine_conflicts = [c for c in combined_conflicts if c["type"] == "routine"]
    
    if routine_conflicts:
        return {
            "status": "error",
            "message": "해당 요일에 이미 고정 루틴이 존재합니다.",
            "conflicts": routine_conflicts
        }

    async with conn.cursor() as cur:
        await cur.execute(insert_routine_sql, (user_id, business, day_of_week, start_time, end_time, end_date, location))
        routine_id = cur.lastrowid

        return {
            "status": "success",
            "message": "반복 일정이 성공적으로 등록되었습니다.",
            "data": {
                "routine_id": routine_id,
                "business": business
            }
        }

async def update_schedule(conn, user_id: str, args: dict) -> dict:
    schedule_id = args.get("schedule_id")
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    location = args.get("location")
    business = args.get("business")

    target_dt = parse_to_datetime(start_time)
    python_weekday = target_dt.weekday()
    db_day_of_week = (python_weekday + 1) % 7

    # 업데이트 전 최적화된 충돌 검사 (현재 수정할 일정 ID는 검색 대상에서 자동 필터링)
    combined_conflicts = await check_conflicts_opt(conn, user_id, start_time, end_time, db_day_of_week, exclude_schedule_id=schedule_id)
    
    if combined_conflicts:
        return {
            "status": "error",
            "message": "해당 시간대에 이미 일정이 존재합니다.",
            "conflicts": combined_conflicts
        }

    async with conn.cursor() as cur:
        await cur.execute(update_schedule_sql, (start_time, end_time, location, business, schedule_id, user_id))
        return {
            "status": "success",
            "message": "일정이 성공적으로 수정되었습니다.",
            "data": {
                "schedule_id": schedule_id,
                "business": business
            }
        }

async def trace_friend(conn, user_id: str, args: dict) -> dict:
    loc = args.get('location')
    biz = args.get('business')
    
    # [방어 로직] 필수 검색용 단서가 전혀 없으면 쿼리를 타지 않음 (%% 현상 방지)
    if not loc and not biz:
        return {"status": "success", "found": False, "message": "유효한 검색 단서(장소 또는 목적)가 필요합니다."}
        
    location_clue = f"%{loc or ''}%"
    business_clue = f"%{biz or ''}%"

    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute(trace_friend_by_schedule_sql, (user_id, location_clue, business_clue))
        friend = await cur.fetchone()
        
        if friend:
            return {"status": "success", "found": True, "friend_id": friend["Friend_ID"], "name": friend["name"]}
        else:
            return {"status": "success", "found": False, "message": "해당 조건의 과거 일정에서 지인을 찾지 못했습니다."}


# ==========================================
# 4. 통합 엔트리 포인트 및 정기 청소
# ==========================================

async def process_db_query(user_id: str, query_type: int, query_args: dict) -> dict:
    async with db_pool.acquire() as conn:
        try:
            if query_type == 0:    # 0: 유동적 시점 기반 남은 일정 타임라인 조회 (핵심 기능)
                result = await select_flexible_schedule(conn, user_id, query_args)
            elif query_type == 1:  # 1: 특정 날짜 캘린더 전용 하루 전체 통합 조회 
                result = await select_integrated_schedule(conn, user_id, query_args)
            elif query_type == 2:     # 단발성 일정 삽입
                result = await insert_schedule(conn, user_id, query_args)
            elif query_type == 3:     # 반복 일정 삽입
                result = await insert_routine(conn, user_id, query_args)
            elif query_type == 4:     # 단발성 일정 수정
                result = await update_schedule(conn, user_id, query_args)
            elif query_type == 5:     # 지인 추적
                result = await trace_friend(conn, user_id, query_args)
            else:
                result = {"status": "error", "message": "알 수 없는 쿼리 타입입니다."}

            await conn.commit()
            return result
        except Exception as e:
            await conn.rollback()
            return {"status": "error", "message": f"DB 처리 중 에러 발생: {str(e)}"}

async def cleanup_expired_data() -> dict:
    """백그라운드에서 정기적으로 실행되어 만료된 일정 및 루틴을 청소하는 함수"""
    async with db_pool.acquire() as conn:
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
                    "deleted_routines": deleted_routines
                }
            except Exception as e:
                await conn.rollback()
                return {"status": "error", "message": f"정기 청소 중 에러 발생: {str(e)}"}