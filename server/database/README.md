# Database

이 폴더는 서버가 사용하는 MySQL 데이터베이스 연결과 스키마 정의를 담당합니다. 일정 관리 서비스의 핵심 정보를 저장하기 위해 사용자, 일정, 루틴 테이블을 구성합니다.

## 파일 설명
### connection.py
- aiomysql 기반의 연결 풀을 초기화하고 종료하는 모듈입니다.
- 서버 시작 시 MySQL 커넥션 풀을 생성하고, 종료 시 안전하게 닫습니다.
- 환경 변수로 DB_PASSWORD를 읽어 사용합니다.

### schema.sql
- meeting_DB 데이터베이스를 생성하고, 아래 테이블을 초기화합니다.
  - User: 사용자 정보
  - Schedule: 단발성 일정
  - Routine: 반복 일정

## 테이블 설명
### User: 사용자 식별자와 이름을 저장합니다.
- ID: 로그인 시 입력되는 ID
- name: 사용자 이름

### Schedule: 특정 날짜와 시간대의 단발성 일정을 저장합니다.
- Schedule_ID: 일정 ID. 자동 생성
- User_ID: 사용자 ID
- start_time: 시작 날짜 및 시간. (ex. 2026-07-27 00:00:00)
- end_time: 종료 날짜 및 시간. (ex. 2026-07-27 00:00:00). NULL이면 조회와 충돌 검사에서 시작 후 2시간을 종료 시각으로 간주
- location: 일정 장소
- business: 일정 내용. (ex. 팀 회의, 프로젝트 미팅)
- who: 일정 동반 인원 (ex. ["철수", "짱구"])
- 자동 생성 인자: Schedule_ID
- 필수 입력 인자: User_ID, start_time, business
- nullable 인자: end_time, location, who

### Routine: 요일 기반 반복 일정을 저장합니다.
- Routine_ID: 루틴 ID. 자동 생성
- User_ID: 사용자 ID
- start_time: 시작 시간. (ex. 00:00:01)
- end_time: 종료 시간. (ex. 00:00:01). NULL이면 시작 후 2시간을 종료 시각으로 간주
- location: 루틴 장소
- business: 루틴 내용. (ex. 시스템프로그래밍 수업, 등 운동)
- who: 루틴 동반 인원 (ex. ["철수", "짱구"])
- day_of_week: 루틴이 시작하는 요일. 0=일요일, 1=월요일, ..., 6=토요일
- start_date: 루틴 시작일의 유효 범위 하한. NULL이면 하한 없음
- end_date: 루틴 시작일의 유효 범위 상한. NULL이면 무기한
- 자동 생성 인자: Routine_ID
- 필수 입력 인자: User_ID, start_time, business, day_of_week
- nullable 인자: end_time, location, who, start_date, end_date

#### 자정을 넘는 루틴
- `end_time > start_time`: 시작한 당일에 종료
- `end_time < start_time`: 다음 날에 종료
- `end_time = start_time`: 허용하지 않음
- `start_time`과 `end_time`은 `00:00:00` 이상 `24:00:00` 미만의 시각이며, 루틴 길이는 24시간 미만
- `day_of_week`, `start_date`, `end_date`는 모두 루틴이 시작하는 날짜를 기준으로 판단
- 예를 들어 `day_of_week=1`, `start_time=23:00:00`, `end_time=01:00:00`은 월요일 23시에 시작해 화요일 1시에 종료되는 루틴

### end_time NULLABLE
- end_time이 NULL이라면 해당 일정은 2시간 동안 유지된다고 가정함

## 초기화 방법
MySQL 8.0.16 이상 서버가 실행 중이라면 아래처럼 스키마를 적용할 수 있습니다.
`schema.sql`은 기존 테이블을 삭제한 뒤 다시 생성하므로 기존 데이터가 모두 삭제됩니다.

```bash
mysql -u root -p < database/schema.sql
```

## 연결 설정
서버는 localhost:3306의 MySQL에 접속하며, 데이터베이스 이름은 meeting_DB입니다. 실행 전 .env 파일에 DB_PASSWORD를 설정해야 합니다.

```env
DB_PASSWORD=your_password
```
