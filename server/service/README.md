# Service

이 폴더는 서버의 실제 비즈니스 로직을 담당합니다. 사용자 요청을 DB 작업으로 연결하고, 필요 시 언어 모델을 통해 자연어 응답을 생성합니다.

## 모듈 설명
### db_process.py
- 데이터베이스 접근과 일정 관련 비즈니스 로직을 담당합니다.

0. select_flexible_schedule: 유동적 시점 기반 남은 일정 타임라인 조회
- 받을 인자(args):
  - start_time: 선택, 시작 시점. 없으면 현재 시간 사용
  - end_time: 선택, 종료 시점. 없으면 당일 23:59:59로 자동 설정

1. select_integrated_schedule: 특정 날짜 캘린더 전용 하루 전체 통합 조회
- 받을 인자(args):
  - target_date: 필수, 조회할 날짜 (예: 2026-07-20)

2. insert_schedule: 단발성 일정 삽입
- 받을 인자(args):
  - start_time: 필수, 일정 시작 시간
  - end_time: 선택, 일정 종료 시간
  - location: 선택, 장소
  - business: 필수, 일정 내용
  - who: 선택, 친구/지인 이름 리스트

3. insert_routine: 반복 일정 삽입
- 받을 인자(args):
  - start_time: 필수, 반복 일정 시작 시간
  - end_time: 선택, 반복 일정 종료 시간
  - location: 선택, 장소
  - business: 필수, 반복 일정 내용
  - day_of_week: 필수, 요일 (0=일요일, 1=월요일, ..., 6=토요일)
  - end_date: 선택, 반복 종료 날짜

4. update_schedule: 단발성 일정 수정
- 받을 인자(args):
  - schedule_id: 필수, 수정할 일정 ID
  - start_time: 필수, 새 시작 시간
  - end_time: 선택, 새 종료 시간
  - location: 선택, 새 장소
  - business: 필수, 새 일정 내용

5. trace_friend: 지인 추적
- 받을 인자(args):
  - location: 선택, 장소 단서
  - business: 선택, 일정 내용 단서
  - 참고: location 또는 business 중 하나는 있어야 검색이 가능함

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