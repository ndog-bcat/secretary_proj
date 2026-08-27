import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import sys
import types


if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.AsyncClient = object
    sys.modules["httpx"] = httpx_stub

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

from service import query_context, text_process


class CurrentHandlerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_parameter_request_separates_required_and_optional_fields(self):
        message = await text_process.parameter_request_message(
            2,
            ["business", "end_date", "end_clock", "location", "who"],
        )

        self.assertEqual(
            message,
            "추가할 일정의 내용을 알려주세요. "
            "종료 날짜, 종료 시간, 장소, 함께하는 사람도 있다면 함께 알려주세요.",
        )

    async def test_routine_parameter_request_uses_user_facing_names(self):
        message = await text_process.parameter_request_message(
            3,
            ["start_time", "business", "days_of_week", "location"],
        )

        self.assertEqual(
            message,
            "추가할 반복 일정의 시작 시간과 내용과 반복할 요일을 알려주세요. "
            "장소도 있다면 함께 알려주세요.",
        )

    async def test_day_query_extracts_parameters_and_reaches_db(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-18 09:00:00",
            user_text="show tomorrow",
            query_type=0,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[0]),
        )
        process_db_mock = AsyncMock(return_value={
            "status": "success",
            "target_date": "2026-08-19",
            "timeline": [],
        })

        with (
            patch.object(
                text_process,
                "extract_parameters_from_text",
                new=AsyncMock(return_value={"target_date": "2026-08-19"}),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=process_db_mock,
            ),
        ):
            result = await text_process.handle_day_query(context)

        self.assertEqual(result.pending_step, "done")
        process_db_mock.assert_awaited_once_with(
            "user-1",
            0,
            {"target_date": "2026-08-19"},
        )

    async def test_range_query_applies_defaults_and_reaches_db(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-18 09:00:00",
            user_text="show my schedule",
            query_type=1,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[1]),
        )
        process_db_mock = AsyncMock(return_value={
            "status": "success",
            "range": {
                "start_time": "2026-08-18 09:00:00",
                "end_time": "2026-08-19 00:00:00",
            },
            "timeline": [],
        })

        with (
            patch.object(
                text_process,
                "extract_parameters_from_text",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=process_db_mock,
            ),
        ):
            result = await text_process.handle_range_query(context)

        expected = {
            "start_time": "2026-08-18 09:00:00",
            "end_time": "2026-08-19 00:00:00",
        }
        self.assertEqual(result.pending_step, "done")
        self.assertEqual(result.current_parameters, expected)
        process_db_mock.assert_awaited_once_with("user-1", 1, expected)

    async def test_schedule_insert_uses_current_extraction_contract(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-18 09:00:00",
            user_text="add a meeting tomorrow at 2pm",
            query_type=2,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[2]),
        )
        process_db_mock = AsyncMock(return_value={"status": "success"})

        with (
            patch.object(
                text_process,
                "extract_parameters_from_text",
                new=AsyncMock(return_value={
                    "start_date": "2026-08-19",
                    "start_clock": "14:00:00",
                    "business": "meeting",
                    "unknown": "ignored",
                }),
            ),
            patch.object(
                text_process,
                "get_collision",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=process_db_mock,
            ),
        ):
            result = await text_process.handle_schedule_insert(context)

        self.assertEqual(result.pending_step, "done")
        self.assertEqual(
            result.current_parameters["start_time"],
            "2026-08-19 14:00:00",
        )
        self.assertIsNone(result.current_parameters["end_time"])
        self.assertEqual(result.current_parameters["business"], "meeting")
        self.assertNotIn("start_date", result.current_parameters)
        self.assertNotIn("start_clock", result.current_parameters)
        self.assertNotIn("unknown", result.current_parameters)
        process_db_mock.assert_awaited_once_with(
            "user-1",
            2,
            result.current_parameters,
        )

    async def test_schedule_insert_waits_for_clock_then_assembles_followup(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-18 09:00:00",
            user_text="내일 회의 추가해줘",
            query_type=2,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[2]),
        )
        extract_mock = AsyncMock(side_effect=[
            {
                "start_date": "2026-08-19",
                "business": "회의",
            },
            {"start_clock": "15:00:00"},
        ])
        collision_mock = AsyncMock(return_value=[])
        process_db_mock = AsyncMock(return_value={"status": "success"})

        with (
            patch.object(
                text_process,
                "extract_parameters_from_text",
                new=extract_mock,
            ),
            patch.object(
                text_process,
                "get_collision",
                new=collision_mock,
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=process_db_mock,
            ),
        ):
            first_result = await text_process.handle_schedule_insert(context)

            self.assertEqual(first_result.pending_step, "waiting_parameters")
            self.assertIn("시작 시간", first_result.response_message)
            collision_mock.assert_not_awaited()
            process_db_mock.assert_not_awaited()

            context.user_text = "오후 3시"
            final_result = await text_process.handle_schedule_insert(context)

        self.assertEqual(final_result.pending_step, "done")
        self.assertEqual(
            final_result.current_parameters["start_time"],
            "2026-08-19 15:00:00",
        )
        collision_mock.assert_awaited_once()
        process_db_mock.assert_awaited_once_with(
            "user-1",
            2,
            final_result.current_parameters,
        )

    async def test_routine_insert_generates_group_id_and_reaches_db(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-18 09:00:00",
            user_text="add a weekday exercise routine",
            query_type=3,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[3]),
        )
        process_db_mock = AsyncMock(return_value={"status": "success"})

        with (
            patch.object(
                text_process,
                "extract_parameters_from_text",
                new=AsyncMock(return_value={
                    "start_time": "09:00:00",
                    "business": "exercise",
                    "days_of_week": [1, 2, 3, 4, 5],
                }),
            ),
            patch.object(
                text_process,
                "get_collision",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=process_db_mock,
            ),
        ):
            result = await text_process.handle_routine_insert(context)

        self.assertEqual(result.pending_step, "done")
        self.assertIsNotNone(result.current_parameters["routine_group_id"])
        process_db_mock.assert_awaited_once_with(
            "user-1",
            3,
            result.current_parameters,
        )

    async def test_schedule_update_runs_from_initial_extraction_to_db(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-19 10:00:00",
            "end_time": None,
            "business": "meeting",
            "location": "office",
            "who": None,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-18 09:00:00",
            user_text="move tomorrow's meeting and clear its location",
            query_type=4,
            pending_step="waiting_initial_extraction",
            current_parameters=deepcopy(query_context.parameter_templates[4]),
        )

        with (
            patch.object(
                text_process,
                "extract_update_parameters",
                new=AsyncMock(return_value={
                    "start_clock": "15:00:00",
                    "location": None,
                }),
            ),
            patch.object(
                text_process,
                "extract_dayinfo_from_text",
                new=AsyncMock(return_value={"target_date": "2026-08-19"}),
            ),
            patch.object(
                text_process,
                "get_target_candidates",
                new=AsyncMock(return_value={
                    "status": "success",
                    "candidates": [target],
                }),
            ),
        ):
            first_result = await text_process.handle_schedule_update(context)

        self.assertEqual(first_result.pending_step, "waiting_target")
        self.assertEqual(
            first_result.targeting_parameters,
            {"target_date": "2026-08-19"},
        )
        self.assertEqual(
            first_result.update_parameters,
            {
                "start_clock": "15:00:00",
                "location": None,
            },
        )

        context.user_text = "1"
        process_db_mock = AsyncMock(return_value={"status": "success"})
        with (
            patch.object(
                text_process,
                "get_collision",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=process_db_mock,
            ),
        ):
            final_result = await text_process.handle_schedule_update(context)

        self.assertEqual(final_result.pending_step, "done")
        self.assertEqual(final_result.current_parameters["schedule_id"], 10)
        self.assertEqual(
            final_result.current_parameters["start_time"],
            "2026-08-19 15:00:00",
        )
        self.assertIsNone(final_result.current_parameters["location"])
        process_db_mock.assert_awaited_once_with(
            "user-1",
            4,
            final_result.current_parameters,
        )

    async def test_extraction_failure_reasks_without_calling_db(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-18 09:00:00",
            user_text="unparseable request",
            query_type=2,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[2]),
        )
        process_db_mock = AsyncMock()

        with (
            patch.object(
                text_process,
                "extract_parameters_from_text",
                new=AsyncMock(return_value={"result": "extract fail"}),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=process_db_mock,
            ),
        ):
            result = await text_process.handle_schedule_insert(context)

        self.assertEqual(result.pending_step, "waiting_parameters")
        process_db_mock.assert_not_awaited()


class CurrentOllamaContractTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def async_client_for(response_text):
        response = Mock(status_code=200)
        response.json.return_value = {"response": response_text}
        client = AsyncMock()
        client.post.return_value = response
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=client)
        context_manager.__aexit__ = AsyncMock(return_value=None)
        return context_manager, client

    async def test_parameter_extractor_returns_inner_result_dict(self):
        context_manager, client = self.async_client_for(
            '{"extract_result":{"target_date":"2026-08-19"}}'
        )

        with patch.object(
            text_process.httpx,
            "AsyncClient",
            return_value=context_manager,
        ):
            result = await text_process.extract_parameters_from_text(
                0,
                "show tomorrow",
                ["target_date"],
                "2026-08-18 09:00:00",
                {"target_date": None},
            )

        self.assertEqual(result, {"target_date": "2026-08-19"})
        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["format"], "json")
        self.assertFalse(payload["stream"])

    async def test_query_type_identifier_uses_current_json_contract(self):
        context_manager, client = self.async_client_for('{"query_type":7}')

        with patch.object(
            text_process.httpx,
            "AsyncClient",
            return_value=context_manager,
        ):
            result = await text_process.identify_query_type(
                "delete a recurring routine"
            )

        self.assertEqual(result, 7)
        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["format"], "json")
        self.assertFalse(payload["stream"])

    async def test_parameter_extractor_converts_invalid_json_to_failure(self):
        context_manager, _client = self.async_client_for("not-json")

        with patch.object(
            text_process.httpx,
            "AsyncClient",
            return_value=context_manager,
        ):
            result = await text_process.extract_parameters_from_text(
                0,
                "show tomorrow",
                ["target_date"],
                "2026-08-18 09:00:00",
                {"target_date": None},
            )

        self.assertEqual(result, {"result": "extract fail"})


class ScheduleUpdateAssemblyTests(unittest.IsolatedAsyncioTestCase):
    def test_schedule_insert_uses_start_date_when_end_date_is_missing(self):
        result = text_process.assemble_schedule_insert_parameters({
            "start_date": "2026-08-28",
            "start_clock": "10:00:00",
            "end_date": None,
            "end_clock": "11:00:00",
            "business": "회의",
            "location": None,
            "who": None,
        })

        self.assertEqual(result["start_time"], "2026-08-28 10:00:00")
        self.assertEqual(result["end_time"], "2026-08-28 11:00:00")

    async def test_waiting_parameters_skips_extraction_when_update_already_exists(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": None,
            "business": "회의",
            "location": "회사",
            "who": None,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="이전 단계 응답",
            query_type=4,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[4]),
            selected_targets=[target],
            update_parameters={"location": "홍대"},
        )
        extract_mock = AsyncMock(return_value={"business": "잘못된 추출"})

        with (
            patch.object(
                text_process,
                "extract_update_parameters",
                new=extract_mock,
            ),
            patch.object(
                text_process,
                "get_collision",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=AsyncMock(return_value={"status": "success"}),
            ),
        ):
            result = await text_process.handle_schedule_update(context)

        extract_mock.assert_not_awaited()
        self.assertEqual(result.pending_step, "done")
        self.assertEqual(result.current_parameters["location"], "홍대")
        self.assertEqual(result.current_parameters["business"], "회의")

    async def test_waiting_parameters_extracts_and_applies_update_values(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": None,
            "business": "회의",
            "location": "회사",
            "who": None,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="장소를 홍대로 바꿔줘",
            query_type=4,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[4]),
            selected_targets=[target],
        )

        with (
            patch.object(
                text_process,
                "extract_update_parameters",
                new=AsyncMock(return_value={"location": "홍대"}),
            ),
            patch.object(
                text_process,
                "get_collision",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=AsyncMock(return_value={"status": "success"}),
            ),
        ):
            result = await text_process.handle_schedule_update(context)

        self.assertEqual(result.pending_step, "done")
        self.assertEqual(result.update_parameters, {"location": "홍대"})
        self.assertEqual(result.current_parameters["location"], "홍대")

    async def test_waiting_parameters_reasks_when_no_update_value_is_found(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": None,
            "business": "회의",
            "location": None,
            "who": None,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="잘 모르겠어",
            query_type=4,
            pending_step="waiting_parameters",
            current_parameters=deepcopy(query_context.parameter_templates[4]),
            selected_targets=[target],
        )

        with patch.object(
            text_process,
            "extract_update_parameters",
            new=AsyncMock(return_value={}),
        ):
            result = await text_process.handle_schedule_update(context)

        self.assertEqual(result.pending_step, "waiting_parameters")
        self.assertEqual(result.response_message, "수정할 정보를 말씀해주세요.")
        self.assertEqual(result.update_parameters, {})

    async def test_selected_schedule_and_update_values_are_assembled(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": None,
            "business": "회의",
            "location": "회사",
            "who": ["민수"],
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="1번",
            query_type=4,
            pending_step="waiting_target",
            target_candidates=[target],
            update_parameters={
                "start_clock": "11:00:00",
                "location": None,
            },
        )

        with (
            patch.object(
                text_process,
                "get_collision",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=AsyncMock(return_value={"status": "success"}),
            ),
        ):
            result = await text_process.handle_schedule_update(context)

        self.assertEqual(result.pending_step, "done")
        self.assertEqual(result.selected_targets, [target])
        self.assertEqual(result.current_parameters["schedule_id"], 10)
        self.assertEqual(
            result.current_parameters["start_time"],
            "2026-08-18 11:00:00",
        )
        self.assertIsNone(result.current_parameters["end_time"])
        self.assertIsNone(result.current_parameters["location"])
        self.assertEqual(result.current_parameters["business"], "회의")

    async def test_selected_schedule_waits_when_update_values_are_empty(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": None,
            "business": "회의",
            "location": None,
            "who": None,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="1번",
            query_type=4,
            pending_step="waiting_target",
            target_candidates=[target],
        )

        result = await text_process.handle_schedule_update(context)

        self.assertEqual(result.pending_step, "waiting_parameters")
        self.assertEqual(result.response_message, "수정할 정보를 말씀해주세요.")
        self.assertEqual(result.selected_targets, [target])
        self.assertEqual(result.current_parameters, {})

    def test_schedule_update_assembles_date_only_change(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": "2026-08-18 11:00:00",
            "business": "회의",
            "location": None,
            "who": None,
        }

        result = text_process.assemble_schedule_update_parameters(
            target,
            {"start_date": "2026-08-20"},
        )

        self.assertEqual(result["start_time"], "2026-08-20 10:00:00")
        self.assertEqual(result["end_time"], "2026-08-18 11:00:00")

    def test_schedule_update_assembles_date_and_clock_change(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": None,
            "business": "회의",
            "location": None,
            "who": None,
        }

        result = text_process.assemble_schedule_update_parameters(
            target,
            {
                "start_date": "2026-08-20",
                "start_clock": "15:30:00",
            },
        )

        self.assertEqual(result["start_time"], "2026-08-20 15:30:00")

    def test_schedule_update_assembles_end_date_and_clock_parts(self):
        target = {
            "Schedule_ID": 10,
            "start_time": "2026-08-18 10:00:00",
            "end_time": "2026-08-18 11:00:00",
            "business": "회의",
            "location": None,
            "who": None,
        }
        cases = [
            (
                {"end_date": "2026-08-20"},
                "2026-08-20 11:00:00",
            ),
            (
                {"end_clock": "12:30:00"},
                "2026-08-18 12:30:00",
            ),
            (
                {
                    "end_date": "2026-08-20",
                    "end_clock": "12:30:00",
                },
                "2026-08-20 12:30:00",
            ),
        ]

        for updates, expected in cases:
            with self.subTest(updates=updates):
                result = text_process.assemble_schedule_update_parameters(
                    target,
                    updates,
                )
                self.assertEqual(result["end_time"], expected)


class RoutineUpdateAssemblyTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_routine_group_is_assembled_and_replaced(self):
        target = {
            "Routine_ID": 10,
            "Routine_Group_ID": "group-10",
            "day_of_week": 1,
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "business": "운동",
            "location": "헬스장",
            "who": None,
            "start_date": None,
            "end_date": None,
        }
        group_rows = [
            target,
            {**target, "Routine_ID": 11, "day_of_week": 3},
            {**target, "Routine_ID": 12, "day_of_week": 5},
        ]
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="1번",
            query_type=5,
            pending_step="waiting_target",
            target_candidates=[target],
            update_parameters={
                "days_of_week": [2, 4],
                "start_time": "12:00:00",
            },
        )

        with (
            patch.object(
                text_process.db_process,
                "process_routine_group_query",
                new=AsyncMock(return_value={
                    "status": "success",
                    "candidates": group_rows,
                }),
            ),
            patch.object(
                text_process,
                "get_collision",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                text_process.db_process,
                "process_db_query",
                new=AsyncMock(return_value={"status": "success"}),
            ) as process_db_mock,
        ):
            result = await text_process.handle_routine_update(context)

        self.assertEqual(result.pending_step, "done")
        self.assertEqual(result.selected_targets, group_rows)
        self.assertEqual(
            result.current_parameters["routine_group_id"],
            "group-10",
        )
        self.assertEqual(result.current_parameters["days_of_week"], [2, 4])
        self.assertEqual(result.current_parameters["start_time"], "12:00:00")
        process_db_mock.assert_awaited_once_with(
            "user-1",
            5,
            result.current_parameters,
        )

    async def test_weekday_selection_loads_group_candidates(self):
        target = {
            "Routine_ID": 10,
            "Routine_Group_ID": "group-10",
            "day_of_week": 1,
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "business": "운동",
            "location": None,
            "who": None,
            "start_date": None,
            "end_date": None,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="월",
            query_type=5,
            pending_step="waiting_to_pick_weekday",
            target_candidates=[1, 3],
        )

        with patch.object(
            text_process,
            "get_target_candidates",
            new=AsyncMock(return_value={
                "status": "success",
                "candidates": [target],
            }),
        ):
            result = await text_process.handle_routine_update(context)

        self.assertEqual(result.pending_step, "waiting_target")
        self.assertEqual(result.targeting_parameters, {"days_of_week": [1]})
        self.assertEqual(result.target_candidates, [target])


class DeleteHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_delete_targets_and_deletes_selected_schedule(self):
        target = {
            "Schedule_ID": 20,
            "start_time": "2026-08-18 10:00:00",
            "end_time": None,
            "business": "회의",
            "location": None,
            "who": None,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="내일 회의를 삭제해줘",
            query_type=6,
            pending_step="waiting_to_pick_day",
        )

        with (
            patch.object(
                text_process,
                "extract_dayinfo_from_text",
                new=AsyncMock(return_value={"target_date": "2026-08-18"}),
            ),
            patch.object(
                text_process,
                "get_target_candidates",
                new=AsyncMock(return_value={
                    "status": "success",
                    "candidates": [target],
                }),
            ),
        ):
            first_result = await text_process.handle_schedule_delete(context)

        self.assertEqual(first_result.pending_step, "waiting_target")
        context.user_text = "1번"
        with patch.object(
            text_process.db_process,
            "process_db_query",
            new=AsyncMock(return_value={
                "status": "success",
                "data": {"affected_rows": 1},
            }),
        ) as process_db_mock:
            final_result = await text_process.handle_schedule_delete(context)

        self.assertEqual(final_result.pending_step, "done")
        self.assertEqual(
            final_result.response_message,
            "일정 삭제에 성공하였습니다.",
        )
        self.assertEqual(final_result.current_parameters, {"schedule_id": 20})
        process_db_mock.assert_awaited_once_with(
            "user-1",
            6,
            {"schedule_id": 20},
        )

    async def test_routine_delete_selects_weekday_and_deletes_group(self):
        target = {
            "Routine_ID": 10,
            "Routine_Group_ID": "group-10",
            "day_of_week": 1,
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "business": "운동",
            "location": None,
            "who": None,
            "start_date": None,
            "end_date": None,
        }
        duplicate_group_row = {
            **target,
            "Routine_ID": 11,
            "day_of_week": 3,
        }
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="루틴을 삭제해줘",
            query_type=7,
            pending_step="waiting_to_pick_weekday",
        )

        with (
            patch.object(
                text_process,
                "extract_dayinfo_from_text",
                new=AsyncMock(return_value={"days_of_week": None}),
            ),
            patch.object(
                text_process.db_process,
                "process_target_day_query",
                new=AsyncMock(return_value={
                    "status": "success",
                    "candidates": [1, 3],
                }),
            ),
        ):
            weekday_result = await text_process.handle_routine_delete(context)

        self.assertEqual(weekday_result.pending_step, "waiting_to_pick_weekday")
        context.user_text = "월"
        with patch.object(
            text_process,
            "get_target_candidates",
            new=AsyncMock(return_value={
                "status": "success",
                "candidates": [target, duplicate_group_row],
            }),
        ):
            target_result = await text_process.handle_routine_delete(context)

        self.assertEqual(target_result.pending_step, "waiting_target")
        self.assertEqual(target_result.target_candidates, [target])
        context.user_text = "1번"
        with patch.object(
            text_process.db_process,
            "process_db_query",
            new=AsyncMock(return_value={
                "status": "success",
                "data": {"affected_rows": 2},
            }),
        ) as process_db_mock:
            final_result = await text_process.handle_routine_delete(context)

        self.assertEqual(final_result.pending_step, "done")
        self.assertEqual(
            final_result.response_message,
            "루틴 삭제에 성공하였습니다.",
        )
        self.assertEqual(
            final_result.current_parameters,
            {"routine_group_id": "group-10"},
        )
        process_db_mock.assert_awaited_once_with(
            "user-1",
            7,
            {"routine_group_id": "group-10"},
        )

    async def test_schedule_delete_reports_missing_target_when_no_row_changed(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="1번",
            query_type=6,
            pending_step="waiting_target",
            target_candidates=[{"Schedule_ID": 20}],
        )

        with patch.object(
            text_process.db_process,
            "process_db_query",
            new=AsyncMock(return_value={
                "status": "success",
                "data": {"affected_rows": 0},
            }),
        ):
            result = await text_process.handle_schedule_delete(context)

        self.assertEqual(result.pending_step, "done")
        self.assertEqual(
            result.response_message,
            "삭제할 일정을 찾지 못했습니다.",
        )

    async def test_routine_delete_reports_missing_target_when_no_row_changed(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="1번",
            query_type=7,
            pending_step="waiting_target",
            target_candidates=[{"Routine_Group_ID": "group-10"}],
        )

        with patch.object(
            text_process.db_process,
            "process_db_query",
            new=AsyncMock(return_value={
                "status": "success",
                "data": {"affected_rows": 0},
            }),
        ):
            result = await text_process.handle_routine_delete(context)

        self.assertEqual(result.pending_step, "done")
        self.assertEqual(
            result.response_message,
            "삭제할 루틴을 찾지 못했습니다.",
        )


if __name__ == "__main__":
    unittest.main()
