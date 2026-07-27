import json
import sys
import types
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

if "aiomysql" not in sys.modules:
    aiomysql_stub = types.ModuleType("aiomysql")
    aiomysql_stub.DictCursor = object()

    async def create_pool(**_kwargs):
        raise RuntimeError("테스트에서는 실제 DB 풀을 생성하지 않습니다.")

    aiomysql_stub.create_pool = create_pool
    sys.modules["aiomysql"] = aiomysql_stub

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda: None
    sys.modules["dotenv"] = dotenv_stub

from service import db_process


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.lastrowid = connection.lastrowid
        self.rowcount = connection.rowcount
        self.rows = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))
        result_queue = self.connection.results.get(sql, [])
        self.rows = result_queue.pop(0) if result_queue else []

    async def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, *, results=None, lastrowid=0, rowcount=1):
        self.results = results or {}
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def cursor(self, *_args):
        return FakeCursor(self)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return FakeAcquire(self.connection)


class TimelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_zero_includes_previous_day_schedule_and_routine(self):
        schedule_row = {
            "Schedule_ID": 11,
            "start_time": datetime(2026, 7, 27, 23, 0),
            "end_time": datetime(2026, 7, 28, 1, 0),
            "location": None,
            "business": "야간 작업",
            "who": '["철수"]',
        }
        routine_row = {
            "Routine_ID": 21,
            "start_time": timedelta(hours=23),
            "end_time": timedelta(hours=1),
            "location": "헬스장",
            "business": "야간 운동",
            "who": None,
            "occurrence_date": date(2026, 7, 27),
            "day_offset": -1,
        }
        conn = FakeConnection(
            results={
                db_process.select_schedule_by_date_sql: [[schedule_row]],
                db_process.select_routine_sql: [[routine_row]],
            }
        )

        result = await db_process.select_day(
            conn,
            "user-1",
            {"target_date": "2026-07-28"},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["timeline"]), 2)
        self.assertEqual(result["timeline"][0]["start_time"], "2026-07-27 23:00:00")
        schedule_item = next(
            item for item in result["timeline"] if item["type"] == "schedule"
        )
        self.assertEqual(schedule_item["who"], ["철수"])
        self.assertEqual(
            conn.calls[0][1],
            (
                "user-1",
                datetime(2026, 7, 29, 0, 0),
                datetime(2026, 7, 28, 0, 0),
            ),
        )
        self.assertEqual(conn.calls[1][1], (date(2026, 7, 28), "user-1"))

    async def test_query_one_deduplicates_cross_midnight_routine(self):
        routine_row = {
            "Routine_ID": 31,
            "start_time": time(23, 0),
            "end_time": time(1, 0),
            "location": None,
            "business": "배치 작업",
            "who": None,
            "occurrence_date": date(2026, 7, 27),
            "day_offset": 0,
        }
        carried_row = dict(routine_row, day_offset=-1)
        conn = FakeConnection(
            results={
                db_process.select_schedule_range_sql: [[]],
                db_process.select_routine_sql: [[routine_row], [carried_row]],
            }
        )

        result = await db_process.select_range(
            conn,
            "user-1",
            {
                "start_time": "2026-07-27 22:00:00",
                "end_time": "2026-07-28 02:00:00",
            },
        )

        self.assertEqual(len(result["timeline"]), 1)
        self.assertEqual(result["timeline"][0]["start_time"], "2026-07-27 23:00:00")
        self.assertEqual(result["timeline"][0]["end_time"], "2026-07-28 01:00:00")


class CrudBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_bindings_and_null_defaults(self):
        schedule_conn = FakeConnection(lastrowid=101)
        schedule_result = await db_process.insert_schedule(
            schedule_conn,
            "user-1",
            {
                "start_time": "2026-07-28 10:00:00",
                "business": "회의",
                "who": ["철수", "영희"],
            },
        )
        self.assertEqual(schedule_result["data"]["schedule_id"], 101)
        self.assertEqual(
            schedule_conn.calls[0][1],
            (
                "user-1",
                "2026-07-28 10:00:00",
                None,
                None,
                "회의",
                json.dumps(["철수", "영희"], ensure_ascii=False),
            ),
        )

        routine_conn = FakeConnection(lastrowid=202)
        routine_result = await db_process.insert_routine(
            routine_conn,
            "user-1",
            {
                "start_time": "23:00:00",
                "end_time": "01:00:00",
                "business": "야간 운동",
                "day_of_week": 1,
                "start_date": "2026-07-27",
            },
        )
        self.assertEqual(routine_result["data"]["routine_id"], 202)
        self.assertEqual(
            routine_conn.calls[0][1],
            (
                "user-1",
                "23:00:00",
                "01:00:00",
                None,
                "야간 운동",
                None,
                1,
                "2026-07-27",
                None,
            ),
        )

    async def test_update_and_delete_bindings(self):
        schedule_conn = FakeConnection()
        await db_process.update_schedule(
            schedule_conn,
            "user-1",
            {
                "schedule_id": 10,
                "start_time": "2026-07-28 13:00:00",
                "business": "수정 회의",
            },
        )
        self.assertEqual(
            schedule_conn.calls[0][1],
            (
                "2026-07-28 13:00:00",
                None,
                None,
                "수정 회의",
                None,
                10,
                "user-1",
            ),
        )

        routine_conn = FakeConnection()
        await db_process.update_routine(
            routine_conn,
            "user-1",
            {
                "routine_id": 20,
                "business": "수정 운동",
                "day_of_week": 2,
                "start_time": "22:00:00",
            },
        )
        self.assertEqual(
            routine_conn.calls[0][1],
            (
                "수정 운동",
                2,
                "22:00:00",
                None,
                None,
                None,
                None,
                None,
                20,
                "user-1",
            ),
        )

        delete_schedule_conn = FakeConnection()
        await db_process.delete_schedule(
            delete_schedule_conn,
            "user-1",
            {"schedule_id": 10},
        )
        self.assertEqual(delete_schedule_conn.calls[0][1], (10, "user-1"))

        delete_routine_conn = FakeConnection()
        await db_process.delete_routine(
            delete_routine_conn,
            "user-1",
            {"routine_id": 20},
        )
        self.assertEqual(delete_routine_conn.calls[0][1], (20, "user-1"))

    async def test_process_db_query_routes_zero_through_seven(self):
        original_pool = db_process.connection.db_pool
        try:
            for query_type in range(8):
                conn = FakeConnection(lastrowid=100 + query_type)
                db_process.connection.db_pool = FakePool(conn)
                if query_type == 0:
                    args = {"target_date": "2026-07-28"}
                elif query_type == 1:
                    args = {
                        "start_time": "2026-07-28 10:00:00",
                        "end_time": "2026-07-28 11:00:00",
                    }
                elif query_type == 2:
                    args = {
                        "start_time": "2026-07-28 10:00:00",
                        "business": "일정",
                    }
                elif query_type == 3:
                    args = {
                        "start_time": "10:00:00",
                        "business": "루틴",
                        "day_of_week": 2,
                    }
                elif query_type in (4, 6):
                    args = {
                        "schedule_id": 1,
                        "start_time": "2026-07-28 10:00:00",
                        "business": "일정",
                    }
                else:
                    args = {
                        "routine_id": 1,
                        "start_time": "10:00:00",
                        "business": "루틴",
                        "day_of_week": 2,
                    }

                result = await db_process.process_db_query("user-1", query_type, args)
                self.assertEqual(result["status"], "success", query_type)
                self.assertTrue(conn.committed, query_type)
                self.assertFalse(conn.rolled_back, query_type)
        finally:
            db_process.connection.db_pool = original_pool


if __name__ == "__main__":
    unittest.main()
