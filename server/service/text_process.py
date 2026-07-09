# 텍스트 쿼리 --> DB 저장 및 검색 쿼리 변환
import httpx
import json
from datetime import datetime

OLLAMA_URL = "http://localhost:11434/api/generate"

async def analyze_query(user_id: str, client_time: str, user_text: str) -> dict:
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