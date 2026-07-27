# Service

이 폴더는 서버의 실제 비즈니스 로직을 담당합니다. 사용자 요청을 DB 작업으로 연결하고, 필요 시 언어 모델을 통해 자연어 응답을 생성합니다.

## 모듈 설명
### db_process.py
- 데이터베이스 접근과 검증 완료된 일정 CRUD를 담당합니다.
- 충돌 검사와 자연어 기반 튜플 타겟팅은 앞단 파이프라인에서 처리합니다.
- INSERT와 UPDATE에서 전달되지 않은 선택 인자는 SQL NULL로 저장합니다.

#### 쿼리 유형

0. 특정 일자의 전체 일정과 루틴 조회
- `target_date`: 필수, `YYYY-MM-DD`
- 해당 날짜와 겹치는 전날 시작 일정·루틴도 포함

1. 특정 기간의 전체 일정과 루틴 조회
- `start_time`: 선택. 없으면 쿼리 요청 시점
- `end_time`: 선택. 없으면 쿼리 요청일 다음 날 `00:00:00`
- 조회 범위는 `[start_time, end_time)`의 반열린 구간

2. 충돌 검사가 끝난 일정 삽입
- 필수: `start_time`, `business`
- 선택: `end_time`, `location`, `who`

3. 충돌 검사가 끝난 루틴 삽입
- 필수: `start_time`, `business`, `day_of_week`
- 선택: `end_time`, `location`, `who`, `start_date`, `end_date`

4. 타겟팅과 충돌 검사가 끝난 일정 수정
- 필수: `schedule_id`, `start_time`, `business`
- 선택: `end_time`, `location`, `who`
- 전체 교체 방식이므로 누락된 선택 인자는 NULL로 변경

5. 타겟팅과 충돌 검사가 끝난 루틴 수정
- 필수: `routine_id`, `start_time`, `business`, `day_of_week`
- 선택: `end_time`, `location`, `who`, `start_date`, `end_date`
- 전체 교체 방식이므로 누락된 선택 인자는 NULL로 변경

6. 타겟팅이 끝난 일정 삭제
- `schedule_id`: 필수

7. 타겟팅이 끝난 루틴 삭제
- `routine_id`: 필수

### text_process.py
- 사용자의 자연어 질문을 분석해 DB 쿼리 인자를 생성하고, DB 결과를 다시 자연어로 변환합니다.
- 현재는 Ollama를 통해 LLM 응답을 받아 처리하는 구조입니다.

### audio_process.py
- 음성 입력을 자연어 텍스트로 변환해주는 파일

## 처리 흐름
1. 텍스트 요청이 들어오면 text_process.py가 질의 유형을 분석합니다.
2. 분석 결과는 db_process.py로 전달됩니다.
3. db_process.py가 MySQL을 통해 일정 정보를 조회하거나 수정합니다.
4. 결과를 다시 자연어 형태로 정리해 클라이언트에 반환합니다.

## 참고 사항
- DB 작업은 aiomysql 커넥션 풀을 사용해 비동기 처리됩니다.
