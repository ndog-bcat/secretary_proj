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
- Routine_ID: 요일별 루틴 행 ID. DB에서 자동 생성
- Routine_Group_ID: 같은 논리적 루틴의 요일별 행이 공유하는 그룹 ID. 서비스가 UUID 문자열을 한 번 생성해 전달
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
- 프로그램 생성 인자: Routine_Group_ID
- DB 삽입 필수 인자: Routine_Group_ID, User_ID, start_time, business, day_of_week
- nullable 인자: end_time, location, who, start_date, end_date

#### 여러 요일 루틴
- Routine의 한 행은 시작 요일 하나만 저장하며, `day_of_week`은 정수 하나입니다.
- 자연어에서 추출한 여러 요일은 서비스에서 요일별 행으로 확장합니다.
- 같은 요청에서 생성된 모든 요일별 행에는 같은 `Routine_Group_ID`를 사용합니다.
- `(User_ID, Routine_Group_ID, day_of_week)` UNIQUE 제약으로 같은 그룹의 동일 요일이 중복 저장되는 것을 방지합니다.
- 요일 기반 타겟팅은 요청 요일에 시작하는 루틴뿐 아니라 전날 시작해 자정을 넘어 요청 요일에 걸치는 루틴도 포함합니다.
- 예를 들어 화요일과 목요일에 반복되는 시스템프로그래밍 수업은 아래 두 행으로 저장합니다.

|Routine_ID|Routine_Group_ID|business|day_of_week|
|:---:|:---:|:---|:---:|
|10|동일한 UUID|시스템프로그래밍 수업|2|
|11|동일한 UUID|시스템프로그래밍 수업|4|

#### 루틴 식별 범위
- `Routine_ID`는 특정 요일의 물리적인 루틴 행 하나를 식별하는 내부 ID입니다.
- `Routine_Group_ID`는 같은 논리적 루틴에 속한 모든 요일별 행을 대상으로 사용합니다.
- 그룹 전체 수정은 기존 그룹을 제외하고 새 루틴 집합의 충돌을 검사한 뒤, 같은 트랜잭션에서 기존 그룹을 삭제하고 새 행들을 삽입하는 전체 교체 방식으로 처리합니다.
- 서비스의 루틴 삭제는 `Routine_Group_ID`로 논리적 루틴 전체를 삭제합니다.

#### 자정을 넘는 루틴
- `end_time > start_time`: 시작한 당일에 종료
- `end_time < start_time`: 다음 날에 종료
- `end_time = start_time`: 허용하지 않음
- `start_time`과 `end_time`은 `00:00:00` 이상 `24:00:00` 미만의 시각이며, 루틴 길이는 24시간 미만
- `day_of_week`, `start_date`, `end_date`는 모두 루틴이 시작하는 날짜를 기준으로 판단
- 예를 들어 `day_of_week=1`, `start_time=23:00:00`, `end_time=01:00:00`은 월요일 23시에 시작해 화요일 1시에 종료되는 루틴

### end_time NULLABLE
- Schedule 또는 Routine의 end_time이 NULL이라면 시작 후 2시간을 종료 시각으로 간주합니다.

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
