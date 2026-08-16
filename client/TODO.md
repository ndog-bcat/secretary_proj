# Android 클라이언트 TODO

## 목표

```text
Android Flet 앱
→ 같은 와이파이의 로컬 PC FastAPI 서버
→ MySQL
```

- Android만 지원
- 서버는 로컬 PC에서 실행
- 클라이언트는 DB에 직접 연결하지 않음
- 이름 등록과 자동 로그인만 구현
- 텍스트 기능 완성 후 음성 추가

---

## 1. 필요한 서버 API

### 사용자 등록

```text
POST /users
요청: { "name": "사용자 이름" }
응답: { "status": "success", "user_id": "UUID", "name": "사용자 이름" }
```

- 서버에서 UUID 생성
- `User` 테이블에 저장
- 비밀번호 로그인은 만들지 않음

### 텍스트 요청

```text
POST /query/text
```

요청:

```json
{
  "user_id": "UUID",
  "context_id": null,
  "request_time": "2026-08-14 09:00:00",
  "user_text": "내일 일정 보여줘"
}
```

응답:

```json
{
  "status": "success",
  "context_id": "UUID",
  "pending_step": "done",
  "message": "서버 응답"
}
```

### 컨텍스트 규칙

```text
첫 요청: context_id = null
→ 서버가 ScheduleQueryContext와 context_id 생성

후속 답변: 이전 context_id 전송
→ 기존 컨텍스트의 user_text, request_time 갱신

pending_step == done
→ 서버와 클라이언트에서 context_id 제거
```

MVP에서는 서버 메모리 딕셔너리에 컨텍스트를 저장한다.

---

## 2. 휴대폰에서 로컬 PC 서버 연결

서버 실행:

```powershell
uvicorn server:app --host 0.0.0.0 --port 8000
```

PC IP 확인:

```powershell
ipconfig
```

PC IP가 `192.168.0.20`이라면:

```python
SERVER_URL = "http://192.168.0.20:8000"
```

확인할 것:

- [ ] PC와 휴대폰이 같은 와이파이
- [ ] Windows 방화벽에서 8000 포트 허용
- [ ] 휴대폰에서 `http://PC_IP:8000/docs` 접속 가능

Android 로컬 HTTP 허용 설정:

```toml
[tool.flet.android.manifest_application]
usesCleartextTraffic = "true"
```

`127.0.0.1`은 휴대폰 자신이므로 사용하지 않는다.

---

## 3. 클라이언트 파일

| 파일 | 역할 |
|---|---|
| `api/network.py` | 모든 HTTP 요청과 오류 처리 |
| `ui/login_view.py` | 이름 등록 화면 |
| `ui/upload_view.py` | 메인 채팅 화면 |
| `ui/result_view.py` | 사용자·서버·오류 메시지 UI |
| `client.py` | 앱 실행, 화면 전환, 사용자와 context_id 보관 |

### `network.py`

```python
async def create_user(name: str) -> dict:
    ...

async def send_text_query(
    user_id: str,
    user_text: str,
    request_time: str,
    context_id: str | None,
) -> dict:
    ...
```

처리할 오류:

- 서버 연결 실패
- timeout
- HTTP 오류
- JSON 파싱 실패

### 로그인 화면

- 이름 입력
- 빈 이름 차단
- 서버에서 사용자 UUID 발급
- `user_id`, `user_name`을 Flet 저장소에 저장
- 다음 실행부터 로그인 화면 생략

### 채팅 화면

- 메시지 목록
- 입력창과 전송 버튼
- 요청 중 로딩 표시 및 중복 전송 차단
- 로그아웃

전송 흐름:

```text
사용자 메시지 표시
→ send_text_query()
→ 서버 message 표시
→ context_id 갱신
→ pending_step == done이면 context_id 제거
```

---

## 4. 구현 순서

- [ ] 서버 0~7번 핸들러 완성
- [ ] `POST /users` 구현
- [ ] `POST /query/text` 구현
- [ ] 서버 컨텍스트 저장 구현
- [ ] PC에서 API 단독 테스트
- [ ] `network.py` 구현
- [ ] 로그인 화면 구현
- [ ] 채팅 화면 구현
- [ ] 휴대폰에서 로컬 서버 연결
- [ ] Android 전체 흐름 테스트
- [ ] APK 빌드
- [ ] 음성 기능 추가

---

## 5. Android 실행

실기기 테스트:

```powershell
flet run --android client.py
```

APK 빌드:

```powershell
flet build apk .
```

---

## 6. 완료 확인

- [ ] 최초 이름 등록
- [ ] 앱 재실행 후 자동 로그인
- [ ] 일정·루틴 조회·삽입·수정·삭제
- [ ] 추가 질문에 같은 context_id로 답변
- [ ] 충돌 후 `진행`·`폐기`
- [ ] 완료 후 새로운 요청 시작
- [ ] 서버가 꺼졌을 때 오류 표시
- [ ] 요청 중 중복 전송 방지

텍스트 기능이 모두 동작한 뒤 음성 녹음, 마이크 권한, UI 디자인을 추가한다.
