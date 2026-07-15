# 텍스트 쿼리 --> DB 저장 및 검색 쿼리 변환
# analyze_text_query: 자연어쿼리의 쿼리 유형 파악 후 해당 쿼리에 해당하는 인자만을 추출하여 query_type, query_args로 db_process.py에 전달
# process_text_query: db_process.py에서 받아온 쿼리 결과를 분석하여 자연어로 변환 후 반환
import httpx
import json
from datetime import datetime
from service import db_process

OLLAMA_URL = "http://localhost:11434/api/generate"

async def analyze_text_query(user_id: str, client_time: str, user_text: str) -> dict:
    system_prompt = (
    )
    
    payload = {
        "model": "qwen2.5-coder:7b",
        "prompt": f"{system_prompt}\n\n사용자 질문: \"{user_text}\"",
        "stream": False,
        "format": "json"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(OLLAMA_URL, json=payload, timeout=30.0)
            if response.status_code == 200:
                result_str = response.json().get("response", "{}")
                return json.loads(result_str)
            return {"error": f"Ollama 에러: {response.status_code}"}
    except Exception as e:
        return {"error": f"AI 라우팅 실패: {str(e)}"}

async def process_text_query(query_type: int, query_args: dict) -> str:
    db_result = await db_process.process_db_query(query_type, query_args)
    if "error" in db_result:
        return f"DB 처리 에러: {db_result['error']}"

    system_prompt = (
    )
    
    payload = {
        "model": "qwen2.5-coder:7b",
        "prompt": f"{system_prompt}\n\nDB 결과: {json.dumps(db_result)}",
        "stream": False,
        "format": "json"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(OLLAMA_URL, json=payload, timeout=30.0)
            if response.status_code == 200:
                result_str = response.json().get("response", "{}")
                return json.loads(result_str).get("result", "")
            return f"Ollama 에러: {response.status_code}"
    except Exception as e:
        return f"AI 라우팅 실패: {str(e)}"