# Secretary Server

이 디렉터리는 클라이언트로부터 전달된 텍스트/음성 데이터를 받아, 일정 관리와 관련된 자연어 요청을 처리하는 FastAPI 서버입니다. 서버는 사용자 요청을 분류한 뒤 데이터베이스 조회·삽입·수정 작업을 수행하고, 필요 시 LLM을 통해 결과를 자연어로 정리해 반환합니다.

## 주요 기능
- FastAPI 기반 HTTP API 제공
- 텍스트/음성 업로드 수신
- 자연어 질의 분류 및 DB 처리 라우팅
- 일정, 반복 일정, 친구/지인 정보 관리
- 만료된 데이터 정기 삭제 배치 처리

## 프로젝트 구조
- server.py: FastAPI 앱 진입점, 라우트 정의, 서버 생명주기 관리
- database/: MySQL 연결 설정과 스키마 정의
- service/: 텍스트 처리, 음성 처리, DB 처리 로직

## 실행 전 준비
1. Python 패키지 설치
   - pip install -r requirements.txt
2. MySQL 서버 실행
   - 로컬 MySQL이 실행 중이어야 합니다.
3. 데이터베이스 초기화
   - database/schema.sql 을 실행해 meeting_DB를 생성합니다.
4. 환경 변수 설정
   - 프로젝트 루트에 .env 파일을 만들고 DB_PASSWORD를 설정합니다.
   - 예: DB_PASSWORD=your_password
5. Ollama 실행 (텍스트 처리 기능 사용 시)
   - Ollama가 로컬에서 실행 중이어야 하며, qwen2.5-coder:7b 모델이 준비되어 있어야 합니다.

## 실행 방법
서버 디렉터리에서 아래 명령으로 실행합니다.

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

## API 개요
### 1) 파일 업로드
- 경로: POST /upload
- Form 데이터
  - data_type: text 또는 audio
  - client_id: 클라이언트 식별자
  - sent_time: 전송 시간
  - file: 업로드 파일

### 2) 결과 조회
- 경로: GET /results/{client_id}
- 클라이언트별 처리 결과 확인용 엔드포인트입니다.

## 처리 흐름
1. 클라이언트가 텍스트/음성 파일과 메타데이터를 전송합니다.
2. 서버는 업로드 데이터를 수신합니다.
3. 텍스트 요청은 service/text_process.py에서 LLM 기반으로 질의 유형을 분석합니다.
4. DB 처리는 service/db_process.py에서 수행됩니다.
5. 결과는 다시 자연어 응답 형태로 정리되어 반환됩니다.

## 참고 사항
- 현재 음성 처리 모듈은 기본 골격만 존재하며, 실제 STT 기능은 이후 확장 예정입니다.
- 서버 실행 중에는 12시간 간격으로 만료된 일정/루틴 데이터를 정리하는 백그라운드 작업이 동작합니다.
- 실제 운영 환경에서는 DB 계정 정보와 모델 실행 환경을 별도로 관리하는 것이 좋습니다.