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


if __name__ == "__main__":
    unittest.main()
