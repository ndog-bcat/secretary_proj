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
        if (
            self.connection.fail_on_call is not None
            and len(self.connection.calls) == self.connection.fail_on_call
        ):
            raise RuntimeError("의도한 테스트 DB 오류")

        lastrowid_queue = self.connection.lastrowids.get(sql, [])
        if lastrowid_queue:
            self.lastrowid = lastrowid_queue.pop(0)

        rowcount_queue = self.connection.rowcounts.get(sql, [])
        if rowcount_queue:
            self.rowcount = rowcount_queue.pop(0)

        result_queue = self.connection.results.get(sql, [])
        self.rows = result_queue.pop(0) if result_queue else []

    async def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(
        self,
        *,
        results=None,
        lastrowid=0,
        rowcount=1,
        lastrowids=None,
        rowcounts=None,
        fail_on_call=None,
    ):
        self.results = results or {}
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self.lastrowids = lastrowids or {}
        self.rowcounts = rowcounts or {}
        self.fail_on_call = fail_on_call
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

        routine_conn = FakeConnection(
            lastrowids={db_process.insert_routine_sql: [202, 203]}
        )
        routine_result = await db_process.insert_routine(
            routine_conn,
            "user-1",
            {
                "routine_group_id": "group-1",
                "start_time": "23:00:00",
                "end_time": "01:00:00",
                "business": "야간 운동",
                "days_of_week": [4, 2, 2],
                "start_date": "2026-07-27",
            },
        )
        self.assertEqual(routine_result["data"]["routine_group_id"], "group-1")
        self.assertEqual(routine_result["data"]["routine_ids"], [202, 203])
        self.assertEqual(
            routine_conn.calls[0][1],
            (
                "group-1",
                "user-1",
                "23:00:00",
                "01:00:00",
                None,
                "야간 운동",
                None,
                2,
                "2026-07-27",
                None,
            ),
        )
        self.assertEqual(routine_conn.calls[1][1][7], 4)

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

        routine_conn = FakeConnection(
            lastrowids={db_process.insert_routine_sql: [301, 302]},
            rowcounts={db_process.delete_routine_group_sql: [2]},
        )
        routine_result = await db_process.update_routine(
            routine_conn,
            "user-1",
            {
                "routine_group_id": "group-20",
                "business": "수정 운동",
                "days_of_week": [2, 4],
                "start_time": "22:00:00",
            },
        )
        self.assertEqual(
            routine_conn.calls[0][1],
            ("group-20", "user-1"),
        )
        self.assertEqual(routine_conn.calls[1][0], db_process.insert_routine_sql)
        self.assertEqual(routine_conn.calls[1][1][0], "group-20")
        self.assertEqual(routine_conn.calls[1][1][7], 2)
        self.assertEqual(routine_conn.calls[2][1][7], 4)
        self.assertEqual(routine_result["data"]["deleted_rows"], 2)
        self.assertEqual(routine_result["data"]["routine_ids"], [301, 302])

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
            {"routine_group_id": "group-20"},
        )
        self.assertEqual(
            delete_routine_conn.calls[0][1],
            ("group-20", "user-1"),
        )

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
                        "routine_group_id": "group-3",
                        "start_time": "10:00:00",
                        "business": "루틴",
                        "days_of_week": [2],
                    }
                elif query_type in (4, 6):
                    args = {
                        "schedule_id": 1,
                        "start_time": "2026-07-28 10:00:00",
                        "business": "일정",
                    }
                else:
                    args = {
                        "routine_group_id": f"group-{query_type}",
                        "start_time": "10:00:00",
                        "business": "루틴",
                        "days_of_week": [2],
                    }

                result = await db_process.process_db_query("user-1", query_type, args)
                self.assertEqual(result["status"], "success", query_type)
                self.assertTrue(conn.committed, query_type)
                self.assertFalse(conn.rolled_back, query_type)
        finally:
            db_process.connection.db_pool = original_pool

    async def test_routine_replace_rolls_back_as_one_transaction(self):
        original_pool = db_process.connection.db_pool
        try:
            conn = FakeConnection(
                lastrowids={db_process.insert_routine_sql: [401]},
                rowcounts={db_process.delete_routine_group_sql: [2]},
                fail_on_call=3,
            )
            db_process.connection.db_pool = FakePool(conn)

            result = await db_process.process_db_query(
                "user-1",
                5,
                {
                    "routine_group_id": "group-rollback",
                    "days_of_week": [1, 3],
                    "start_time": "10:00:00",
                    "business": "원자적 교체",
                },
            )

            self.assertEqual(result["status"], "error")
            self.assertFalse(conn.committed)
            self.assertTrue(conn.rolled_back)
            self.assertEqual(conn.calls[0][0], db_process.delete_routine_group_sql)
            self.assertEqual(conn.calls[1][0], db_process.insert_routine_sql)
            self.assertEqual(conn.calls[2][0], db_process.insert_routine_sql)
        finally:
            db_process.connection.db_pool = original_pool

    async def test_multi_day_routine_insert_rolls_back_as_one_transaction(self):
        original_pool = db_process.connection.db_pool
        try:
            conn = FakeConnection(
                lastrowids={db_process.insert_routine_sql: [501]},
                fail_on_call=2,
            )
            db_process.connection.db_pool = FakePool(conn)

            result = await db_process.process_db_query(
                "user-1",
                3,
                {
                    "routine_group_id": "group-insert-rollback",
                    "days_of_week": [2, 4],
                    "start_time": "10:00:00",
                    "business": "다중 요일 삽입",
                },
            )

            self.assertEqual(result["status"], "error")
            self.assertFalse(conn.committed)
            self.assertTrue(conn.rolled_back)
            self.assertEqual(len(conn.calls), 2)
            self.assertTrue(
                all(call[0] == db_process.insert_routine_sql for call in conn.calls)
            )
        finally:
            db_process.connection.db_pool = original_pool

    async def test_routine_replace_rejects_missing_target_group(self):
        conn = FakeConnection(
            rowcounts={db_process.delete_routine_group_sql: [0]},
        )

        with self.assertRaises(LookupError):
            await db_process.update_routine(
                conn,
                "user-1",
                {
                    "routine_group_id": "missing-group",
                    "days_of_week": [1],
                    "start_time": "10:00:00",
                    "business": "없는 루틴",
                },
            )

        self.assertEqual(len(conn.calls), 1)


class TargetingAndConflictCandidateTests(unittest.IsolatedAsyncioTestCase):
    async def test_future_schedule_dates_binding_and_normalization(self):
        conn = FakeConnection(
            results={
                db_process.select_future_schedule_dates_sql: [[
                    {"target_date": date(2026, 8, 5)},
                    {"target_date": date(2026, 8, 6)},
                ]]
            }
        )

        result = await db_process.select_future_schedule_dates(
            conn,
            "user-1",
            "2026-08-05 13:30:00",
        )

        self.assertEqual(result, ["2026-08-05", "2026-08-06"])
        self.assertEqual(
            conn.calls[0][1],
            (datetime(2026, 8, 5, 13, 30), "user-1"),
        )

    async def test_active_weekdays_and_weekday_target_binding(self):
        active_conn = FakeConnection(
            results={
                db_process.select_active_routine_weekdays_sql: [[
                    {"target_day": 2},
                    {"target_day": 4},
                ]]
            }
        )
        active_days = await db_process.select_active_routine_weekdays(
            active_conn,
            "user-1",
            "2026-08-05 13:30:00",
        )
        self.assertEqual(active_days, [2, 4])
        self.assertEqual(
            active_conn.calls[0][1],
            (datetime(2026, 8, 5, 13, 30), "user-1"),
        )

        routine_row = {
            "Routine_ID": 10,
            "Routine_Group_ID": "group-10",
            "day_of_week": 2,
            "start_time": time(10),
            "end_time": time(12),
            "business": "수업",
            "location": None,
            "who": '["동기"]',
            "start_date": date(2026, 8, 1),
            "end_date": None,
        }
        target_conn = FakeConnection(
            results={db_process.select_routines_by_weekdays_sql: [[routine_row]]}
        )
        rows = await db_process.select_routines_by_weekdays(
            target_conn,
            "user-1",
            [4, 2, 2],
            "2026-08-05 13:30:00",
        )
        self.assertEqual(rows[0]["who"], ["동기"])
        self.assertEqual(
            target_conn.calls[0][1],
            (
                "[2, 4]",
                datetime(2026, 8, 5, 13, 30),
                "user-1",
            ),
        )

    async def test_weekday_target_keeps_routine_with_future_start_date(self):
        future_row = {
            "Routine_ID": 99,
            "Routine_Group_ID": "future-semester-group",
            "day_of_week": 2,
            "start_time": time(10),
            "end_time": time(12),
            "business": "다음 학기 수업",
            "location": None,
            "who": None,
            "start_date": date(2026, 9, 1),
            "end_date": date(2026, 12, 18),
        }
        conn = FakeConnection(
            results={db_process.select_routines_by_weekdays_sql: [[future_row]]}
        )

        result = await db_process.select_routines_by_weekdays(
            conn,
            "user-1",
            [2],
            "2026-08-05 13:30:00",
        )

        self.assertEqual(result[0]["Routine_Group_ID"], "future-semester-group")
        self.assertEqual(result[0]["start_date"], date(2026, 9, 1))

    async def test_concrete_overlap_helpers_bind_excluded_targets(self):
        schedule_conn = FakeConnection(
            results={db_process.select_overlapping_schedules_sql: [[]]}
        )
        await db_process.select_overlapping_schedules(
            schedule_conn,
            "user-1",
            "2026-08-05 10:00:00",
            None,
            excluded_schedule_id=50,
        )
        self.assertEqual(
            schedule_conn.calls[0][1],
            (
                "user-1",
                datetime(2026, 8, 5, 12, 0),
                datetime(2026, 8, 5, 10, 0),
                50,
            ),
        )

        routine_conn = FakeConnection(
            results={db_process.select_overlapping_routines_sql: [[]]}
        )
        await db_process.select_overlapping_routines(
            routine_conn,
            "user-1",
            "2026-08-05",
            "23:00:00",
            "01:00:00",
            excluded_group_id="group-50",
        )
        self.assertEqual(
            routine_conn.calls[0][1],
            (
                date(2026, 8, 5),
                time(23, 0),
                time(1, 0),
                "user-1",
                "group-50",
            ),
        )

    async def test_recurrence_conflict_candidate_bindings(self):
        schedule_conn = FakeConnection(
            results={db_process.select_schedules_for_routine_conflict_sql: [[]]}
        )
        await db_process.select_schedules_for_routine_conflict(
            schedule_conn,
            "user-1",
            "2026-09-01",
            "2026-12-18",
        )
        self.assertEqual(
            schedule_conn.calls[0][1],
            (date(2026, 9, 1), date(2026, 12, 18), "user-1"),
        )

        routine_conn = FakeConnection(
            results={db_process.select_routines_for_recurrence_conflict_sql: [[]]}
        )
        await db_process.select_routines_for_recurrence_conflict(
            routine_conn,
            "user-1",
            "2026-09-01",
            None,
            excluded_group_id="group-20",
        )
        self.assertEqual(
            routine_conn.calls[0][1],
            (date(2026, 9, 1), None, "user-1", "group-20"),
        )

    def test_sql_contracts_include_required_exclusions_and_validity(self):
        self.assertIn("Schedule_ID <=> %s", db_process.select_overlapping_schedules_sql)
        self.assertIn(
            "Routine_Group_ID <=> %s",
            db_process.select_routines_for_recurrence_conflict_sql,
        )
        self.assertIn(
            "COALESCE(r.start_date, DATE(p.reference_time))",
            db_process.select_routines_by_weekdays_sql,
        )
        self.assertIn(
            "r.end_date >= r.candidate_date",
            db_process.select_routines_by_weekdays_sql,
        )
        self.assertIn(
            "COALESCE(r.start_date, DATE(p.reference_time))",
            db_process.select_active_routine_weekdays_sql,
        )
        self.assertIn("TIMESTAMPADD", db_process.delete_expired_routine_sql)
        self.assertNotIn("end_date < CURDATE()", db_process.delete_expired_routine_sql)
        self.assertFalse(hasattr(db_process, "update_routine_sql"))
        self.assertFalse(hasattr(db_process, "delete_routine_sql"))

    def test_days_of_week_validation(self):
        self.assertEqual(db_process.normalize_days_of_week([4, 2, 4]), [2, 4])
        for invalid in ([], [7], [-1], [True], ["2"], 2, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    db_process.normalize_days_of_week(invalid)

    async def test_cleanup_uses_actual_routine_occurrence_end(self):
        original_pool = db_process.connection.db_pool
        try:
            conn = FakeConnection(
                rowcounts={
                    db_process.delete_expired_schedule_sql: [3],
                    db_process.delete_expired_routine_sql: [4],
                }
            )
            db_process.connection.db_pool = FakePool(conn)

            result = await db_process.cleanup_expired_data()

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["deleted_schedules"], 3)
            self.assertEqual(result["deleted_routines"], 4)
            self.assertEqual(conn.calls[1][0], db_process.delete_expired_routine_sql)
            self.assertTrue(conn.committed)
            self.assertFalse(conn.rolled_back)
        finally:
            db_process.connection.db_pool = original_pool


if __name__ == "__main__":
    unittest.main()
