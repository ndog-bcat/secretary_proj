import asyncio
import json
from datetime import datetime
from pathlib import Path

from service.query_context import (
    DIRECT_PARAMETER_SPECS,
    TARGETING_PARAMETER_SPECS,
    UPDATE_PARAMETER_SPECS,
)
from service.text_process import (
    extract_dayinfo_from_text,
    extract_parameters_from_text,
    extract_update_parameters,
    identify_query_type,
)


FUNCTIONS = {
    "1": "identify_query_type",
    "2": "extract_parameters_from_text",
    "3": "extract_dayinfo_from_text",
    "4": "extract_update_parameters",
}

TEST_CASES_PATH = Path(__file__).with_name("ollama_test_cases.json")


def format_spec(spec: dict, allow_partial: bool = False) -> str:
    fields = {}
    for key, rule in spec.items():
        type_names = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        description = " | ".join(type_names)
        if rule.get("format"):
            description += f" ({rule['format']})"
        if rule.get("items", {}).get("type"):
            description += f" of {rule['items']['type']}"
        fields[key] = description

    result = json.dumps(fields, ensure_ascii=False, indent=2)
    if allow_partial:
        result += "\n※ 말하지 않은 수정 필드는 키 자체가 없어도 됩니다."
    return result


def validate_value(value, rule: dict) -> list[str]:
    allowed_types = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
    if value is None:
        return [] if "null" in allowed_types else ["null을 허용하지 않습니다."]

    type_checks = {
        "string": lambda item: isinstance(item, str),
        "array": lambda item: isinstance(item, list),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
    }
    if not any(type_checks.get(type_name, lambda _: False)(value) for type_name in allowed_types):
        return [f"자료형이 {allowed_types} 중 하나가 아닙니다."]

    errors = []
    date_format = rule.get("format")
    python_formats = {
        "YYYY-MM-DD": "%Y-%m-%d",
        "YYYY-MM-DD HH:MM:SS": "%Y-%m-%d %H:%M:%S",
        "HH:MM:SS": "%H:%M:%S",
    }
    if date_format and isinstance(value, str):
        try:
            datetime.strptime(value, python_formats[date_format])
        except ValueError:
            errors.append(f"{date_format} 형식이 아닙니다.")

    if isinstance(value, list) and rule.get("items"):
        item_rule = rule["items"]
        for index, item in enumerate(value):
            item_errors = validate_value(item, item_rule)
            errors.extend(f"{index}번째 원소: {error}" for error in item_errors)
            if isinstance(item, int):
                if "minimum" in item_rule and item < item_rule["minimum"]:
                    errors.append(f"{index}번째 원소가 최솟값보다 작습니다.")
                if "maximum" in item_rule and item > item_rule["maximum"]:
                    errors.append(f"{index}번째 원소가 최댓값보다 큽니다.")
        if rule.get("uniqueItems") and len(value) != len(set(value)):
            errors.append("배열에 중복값이 있습니다.")
    return errors


def validate_result(result, spec: dict, allow_partial: bool = False) -> list[str]:
    if not isinstance(result, dict):
        return ["반환값이 딕셔너리가 아닙니다."]
    if result.get("result") == "extract fail":
        return ["Ollama 호출 또는 JSON 변환에 실패했습니다."]

    errors = []
    unknown_keys = set(result) - set(spec)
    if unknown_keys:
        errors.append(f"정의되지 않은 키가 있습니다: {sorted(unknown_keys)}")

    if not allow_partial:
        missing_keys = set(spec) - set(result)
        if missing_keys:
            errors.append(f"누락된 키가 있습니다: {sorted(missing_keys)}")

    for key, value in result.items():
        if key not in spec:
            continue
        errors.extend(f"{key}: {error}" for error in validate_value(value, spec[key]))
    return errors


def read_query_type(valid_types: set[int]) -> int | None:
    allowed = ", ".join(str(number) for number in sorted(valid_types))
    while True:
        value = input(f"쿼리 유형을 입력해주세요 ({allowed}, back): ").strip().lower()
        if value == "exit":
            raise SystemExit
        if value == "back":
            return None
        if value.isdigit() and int(value) in valid_types:
            return int(value)
        print("사용 가능한 쿼리 유형을 입력해주세요.")


def print_result(expected: str, actual, errors: list[str]) -> None:
    print("\n출력 형식:")
    print(expected)
    print("\n실제 출력:")
    print(json.dumps(actual, ensure_ascii=False, indent=2))
    print(f"\n형식 점검: {'PASS' if not errors else 'NON-PASS'}")
    for error in errors:
        print(f"- {error}")
    print()


async def execute_test(function_name: str, query_type: int | None, user_text: str, request_time: str):
    if function_name == "identify_query_type":
        actual = await identify_query_type(user_text)
        errors = [] if isinstance(actual, int) and actual in range(8) else ["0부터 7까지의 정수가 아닙니다."]
        return actual, errors

    if function_name == "extract_parameters_from_text":
        spec = DIRECT_PARAMETER_SPECS[query_type]
        required_args = list(spec)
        actual = await extract_parameters_from_text(
            query_type,
            user_text,
            required_args,
            request_time,
            {key: None for key in required_args},
        )
        return actual, validate_result(actual, spec)

    if function_name == "extract_dayinfo_from_text":
        spec = TARGETING_PARAMETER_SPECS[query_type]
        actual = await extract_dayinfo_from_text(query_type, user_text, request_time)
        return actual, validate_result(actual, spec)

    if function_name == "extract_update_parameters":
        spec = UPDATE_PARAMETER_SPECS[query_type]
        actual = await extract_update_parameters(
            query_type,
            user_text,
            list(spec),
            request_time,
        )
        return actual, validate_result(actual, spec, allow_partial=True)

    return None, [f"지원하지 않는 함수입니다: {function_name}"]


async def run_batch_tests() -> None:
    try:
        test_cases = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"테스트 파일을 읽지 못했습니다: {error}")
        return

    runnable_cases = [case for case in test_cases if case.get("function") and case.get("input")]
    skipped_count = len(test_cases) - len(runnable_cases)
    passed_count = 0

    print(f"\n고정 테스트 {len(runnable_cases)}개를 실행합니다. 빈칸 {skipped_count}개는 건너뜁니다.\n")
    for index, case in enumerate(runnable_cases, start=1):
        name = case.get("name") or f"테스트 {index}"
        expected = case.get("expected")
        print(f"[{index}/{len(runnable_cases)}] {name}")
        print(f"입력: {case['input']}")

        try:
            actual, format_errors = await execute_test(
                case["function"],
                case.get("query_type"),
                case["input"],
                case.get("request_time") or "2026-08-20 12:00:00",
            )
        except (KeyError, TypeError, ValueError) as error:
            actual = None
            format_errors = [f"테스트 설정이 잘못되었습니다: {error}"]

        value_matches = actual == expected
        errors = list(format_errors)
        if not value_matches:
            errors.append("기대 출력과 실제 출력이 다릅니다.")

        print("기대 출력:")
        print(json.dumps(expected, ensure_ascii=False, indent=2))
        print("실제 출력:")
        print(json.dumps(actual, ensure_ascii=False, indent=2))
        print(f"결과: {'PASS' if not errors else 'NON-PASS'}")
        for error in errors:
            print(f"- {error}")
        print()

        if not errors:
            passed_count += 1

    print(
        f"고정 테스트 결과: {len(runnable_cases)}개 중 "
        f"{passed_count}개 PASS, {len(runnable_cases) - passed_count}개 NON-PASS"
    )


async def run_selected(function_number: str, request_time: str) -> None:
    query_type = None
    spec = None
    allow_partial = False

    if function_number == "1":
        expected = "0부터 7까지의 정수"
        print("\nidentify_query_type 함수입니다. 일정 관리 요청을 입력해주세요.")
    elif function_number == "2":
        query_type = read_query_type(set(DIRECT_PARAMETER_SPECS))
        if query_type is None:
            return
        spec = DIRECT_PARAMETER_SPECS[query_type]
        expected = format_spec(spec)
        print("\nextract_parameters_from_text 함수입니다. 조회 또는 삽입 요청을 입력해주세요.")
    elif function_number == "3":
        query_type = read_query_type(set(TARGETING_PARAMETER_SPECS))
        if query_type is None:
            return
        spec = TARGETING_PARAMETER_SPECS[query_type]
        expected = format_spec(spec)
        print("\nextract_dayinfo_from_text 함수입니다. 수정/삭제할 일정의 날짜 또는 루틴의 요일이 담긴 요청을 입력해주세요.")
    else:
        query_type = read_query_type(set(UPDATE_PARAMETER_SPECS))
        if query_type is None:
            return
        spec = UPDATE_PARAMETER_SPECS[query_type]
        allow_partial = True
        expected = format_spec(spec, allow_partial=True)
        print("\nextract_update_parameters 함수입니다. 일정 또는 루틴에서 바꿀 내용을 입력해주세요.")

    print(f"기준 시각: {request_time}")
    while True:
        user_text = input("입력 (back: 함수 선택, exit: 종료): ").strip()
        if user_text.lower() == "exit":
            raise SystemExit
        if user_text.lower() == "back":
            return
        if not user_text:
            print("내용을 입력해주세요.")
            continue

        if function_number == "1":
            actual = await identify_query_type(user_text)
            errors = [] if isinstance(actual, int) and actual in range(8) else ["0부터 7까지의 정수가 아닙니다."]
        elif function_number == "2":
            required_args = list(spec)
            current_parameters = {key: None for key in required_args}
            actual = await extract_parameters_from_text(
                query_type,
                user_text,
                required_args,
                request_time,
                current_parameters,
            )
            errors = validate_result(actual, spec)
        elif function_number == "3":
            actual = await extract_dayinfo_from_text(query_type, user_text, request_time)
            errors = validate_result(actual, spec)
        else:
            required_args = list(spec)
            actual = await extract_update_parameters(
                query_type,
                user_text,
                required_args,
                request_time,
            )
            errors = validate_result(actual, spec, allow_partial=allow_partial)

        print_result(expected, actual, errors)


async def main() -> None:
    request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("Ollama 프롬프트 수동 테스트")
    print("Ollama와 qwen2.5-coder:7b 모델을 먼저 실행해주세요.")

    while True:
        print("\n1. identify_query_type")
        print("2. extract_parameters_from_text")
        print("3. extract_dayinfo_from_text")
        print("4. extract_update_parameters")
        print("5. 고정 테스트 일괄 실행")
        function_number = input("테스트할 함수 번호 (exit: 종료): ").strip().lower()
        if function_number == "exit":
            return
        if function_number == "5":
            await run_batch_tests()
            continue
        if function_number not in FUNCTIONS:
            print("1~5 또는 exit를 입력해주세요.")
            continue
        try:
            await run_selected(function_number, request_time)
        except SystemExit:
            return


if __name__ == "__main__":
    asyncio.run(main())
