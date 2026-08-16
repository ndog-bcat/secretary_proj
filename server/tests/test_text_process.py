import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch
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


class ParameterExtractionRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_query_updates_only_current_parameters(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-13 09:00:00",
            user_text="내일 오후 2시에 회의를 추가해줘",
            query_type=2,
            current_parameters=deepcopy(query_context.parameter_templates[2]),
        )

        response = {
            "extract_result": {
                "start_time": "2026-08-14 14:00:00",
                "business": "회의",
                "unknown": "ignored",
            }
        }
        with patch.object(
            text_process,
            "extract_parameters_from_text",
            new=AsyncMock(return_value=response),
        ):
            result = await text_process.update_query_context_parameters(
                context,
                ["start_time", "business"],
            )

        self.assertEqual(result, 1)
        self.assertEqual(
            context.current_parameters["start_time"],
            "2026-08-14 14:00:00",
        )
        self.assertEqual(context.current_parameters["business"], "회의")
        self.assertNotIn("unknown", context.current_parameters)
        self.assertEqual(context.targeting_parameters, {})
        self.assertEqual(context.update_parameters, {})

    async def test_update_query_separates_target_and_changed_values(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-13 09:00:00",
            user_text="내일 회의를 3시로 바꾸고 장소는 지워줘",
            query_type=4,
            current_parameters=deepcopy(query_context.parameter_templates[4]),
            targeting_parameters=deepcopy(
                query_context.targeting_parameter_templates[4]
            ),
            update_parameters=deepcopy(
                query_context.update_parameter_templates[4]
            ),
        )

        response = {
            "target": {
                "target_date": "2026-08-14",
                "business": "회의",
                "schedule_id": 999,
            },
            "update_information": {
                "start_time": "2026-08-14 15:00:00",
                "location": None,
                "schedule_id": 999,
            },
        }
        with patch.object(
            text_process,
            "extract_parameters_from_text",
            new=AsyncMock(return_value=response),
        ):
            result = await text_process.update_query_context_parameters(
                context,
                ["target_date"],
            )

        self.assertEqual(result, 1)
        self.assertEqual(
            context.targeting_parameters["target_date"],
            "2026-08-14",
        )
        self.assertNotIn("business", context.targeting_parameters)
        self.assertNotIn("schedule_id", context.targeting_parameters)
        self.assertEqual(
            context.update_parameters["start_time"],
            "2026-08-14 15:00:00",
        )
        self.assertIn("location", context.update_parameters)
        self.assertIsNone(context.update_parameters["location"])
        self.assertNotIn("schedule_id", context.update_parameters)
        self.assertTrue(text_process.has_update_parameters(context))
        self.assertTrue(
            all(value is None for value in context.current_parameters.values())
        )

    async def test_delete_query_updates_only_targeting_parameters(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-13 09:00:00",
            user_text="월수금 운동 루틴을 삭제해줘",
            query_type=7,
            current_parameters=deepcopy(query_context.parameter_templates[7]),
            targeting_parameters=deepcopy(
                query_context.targeting_parameter_templates[7]
            ),
        )

        response = {
            "target": {
                "days_of_week": [1, 3, 5],
                "business": "운동",
            }
        }
        with patch.object(
            text_process,
            "extract_parameters_from_text",
            new=AsyncMock(return_value=response),
        ):
            result = await text_process.update_query_context_parameters(
                context,
                ["days_of_week"],
            )

        self.assertEqual(result, 1)
        self.assertEqual(context.targeting_parameters["days_of_week"], [1, 3, 5])
        self.assertNotIn("business", context.targeting_parameters)
        self.assertEqual(context.update_parameters, {})
        self.assertFalse(text_process.has_update_parameters(context))
        self.assertIsNone(context.current_parameters["routine_group_id"])

    async def test_update_values_accumulate_across_user_responses(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-13 09:00:00",
            user_text="내일 일정을 3시로 바꿔줘",
            query_type=4,
            current_parameters=deepcopy(query_context.parameter_templates[4]),
            targeting_parameters=deepcopy(
                query_context.targeting_parameter_templates[4]
            ),
            update_parameters=deepcopy(
                query_context.update_parameter_templates[4]
            ),
        )
        responses = [
            {
                "target": {"target_date": "2026-08-14"},
                "update_information": {
                    "start_time": "2026-08-14 15:00:00"
                },
            },
            {
                "target": {"target_date": None},
                "update_information": {"location": "홍대"},
            },
        ]

        with patch.object(
            text_process,
            "extract_parameters_from_text",
            new=AsyncMock(side_effect=responses),
        ):
            await text_process.update_query_context_parameters(
                context,
                ["target_date"],
            )
            context.user_text = "두 번째 일정이고 장소는 홍대로 바꿔줘"
            await text_process.update_query_context_parameters(context, [])

        self.assertEqual(
            context.update_parameters,
            {
                "start_time": "2026-08-14 15:00:00",
                "location": "홍대",
            },
        )
        self.assertEqual(
            context.targeting_parameters,
            {"target_date": "2026-08-14"},
        )


class PromptContractTests(unittest.TestCase):
    def test_classification_prompt_contains_small_model_decision_rules(self):
        prompt = text_process.build_query_type_prompt(
            "매주 월요일 운동 루틴을 없애줘"
        )

        self.assertIn("반복 루틴 삭제", prompt)
        self.assertIn("단순히 날짜가 월요일이라는 이유만으로", prompt)
        self.assertIn('{"query_type":7}', prompt)
        self.assertTrue(prompt.endswith("JSON 출력:"))

    def test_schedule_update_prompt_contains_context_and_separation_rules(self):
        prompt = text_process.build_parameter_extraction_prompt(
            query_type=4,
            user_text="3시로 바꾸고 장소는 지워줘",
            required_args=[],
            request_time="2026-08-13 09:00:00",
            context_snapshot={
                "selected_target": {
                    "schedule_id": 10,
                    "start_time": "2026-08-14 14:00:00",
                }
            },
        )

        self.assertIn('"schedule_id": 10', prompt)
        self.assertIn("target.target_date만 사용", prompt)
        self.assertIn("명시적 변경", prompt)
        self.assertIn("해당 키를 null", prompt)

    def test_routine_update_prompt_separates_old_and_new_weekdays(self):
        prompt = text_process.build_parameter_extraction_prompt(
            query_type=5,
            user_text="월수금 루틴을 화목으로 바꿔줘",
            required_args=["days_of_week"],
            request_time="2026-08-13 09:00:00",
        )

        self.assertIn("target.days_of_week=[1,3,5]", prompt)
        self.assertIn("update_information.days_of_week=[2,4]", prompt)

    def test_json_parser_accepts_fenced_or_prefixed_object(self):
        self.assertEqual(
            text_process.parse_json_object('```json\n{"query_type": 4}\n```'),
            {"query_type": 4},
        )
        self.assertEqual(
            text_process.parse_json_object('결과: {"query_type": 5}'),
            {"query_type": 5},
        )

    def test_normalizer_accepts_direct_fields_without_envelope(self):
        self.assertEqual(
            text_process.normalize_extraction_result(
                0,
                {"target_date": "2026-08-14"},
            ),
            {"extract_result": {"target_date": "2026-08-14"}},
        )


class ScheduleUpdateAssemblyTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_parameters_skips_extraction_when_update_already_exists(self):
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="이전 단계 응답",
            query_type=4,
            pending_step="waiting_parameters",
            current_parameters={
                "schedule_id": 10,
                "start_time": "2026-08-18 10:00:00",
                "end_time": None,
                "business": "회의",
                "location": "회사",
                "who": None,
            },
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
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="장소를 홍대로 바꿔줘",
            query_type=4,
            pending_step="waiting_parameters",
            current_parameters={
                "schedule_id": 10,
                "start_time": "2026-08-18 10:00:00",
                "end_time": None,
                "business": "회의",
                "location": "회사",
                "who": None,
            },
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
        context = query_context.ScheduleQueryContext(
            user_id="user-1",
            request_time="2026-08-17 09:00:00",
            user_text="잘 모르겠어",
            query_type=4,
            pending_step="waiting_parameters",
            current_parameters={
                "schedule_id": 10,
                "start_time": "2026-08-18 10:00:00",
                "end_time": None,
                "business": "회의",
                "location": None,
                "who": None,
            },
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
                "start_time": "2026-08-18 11:00:00",
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
        self.assertEqual(result.current_parameters["schedule_id"], 10)
        self.assertIsNone(result.current_parameters["end_time"])


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
            new=AsyncMock(return_value={"status": "success"}),
        ) as process_db_mock:
            final_result = await text_process.handle_schedule_delete(context)

        self.assertEqual(final_result.pending_step, "done")
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
            new=AsyncMock(return_value={"status": "success"}),
        ) as process_db_mock:
            final_result = await text_process.handle_routine_delete(context)

        self.assertEqual(final_result.pending_step, "done")
        self.assertEqual(
            final_result.current_parameters,
            {"routine_group_id": "group-10"},
        )
        process_db_mock.assert_awaited_once_with(
            "user-1",
            7,
            {"routine_group_id": "group-10"},
        )


if __name__ == "__main__":
    unittest.main()
