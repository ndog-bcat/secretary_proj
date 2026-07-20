# Database

이 폴더는 서버가 사용하는 MySQL 데이터베이스 연결과 스키마 정의를 담당합니다. 일정 관리 서비스의 핵심 정보를 저장하기 위해 사용자, 친구, 일정, 반복 일정, 일정-친구 매핑 테이블을 구성합니다.

## 파일 설명
### connection.py
- aiomysql 기반의 연결 풀을 초기화하고 종료하는 모듈입니다.
- 서버 시작 시 MySQL 커넥션 풀을 생성하고, 종료 시 안전하게 닫습니다.
- 환경 변수로 DB_PASSWORD를 읽어 사용합니다.

### schema.sql
- meeting_DB 데이터베이스를 생성하고, 아래 테이블을 초기화합니다.
  - User: 사용자 정보
  - Friend: 친구/지인 정보
  - Nickname: 친구의 별칭
  - Schedule: 단발성 일정
  - Routine: 반복 일정
  - To_meet: 일정과 친구의 관계 매핑

## 테이블 요약
- User: 사용자 식별자와 이름을 저장합니다.
- Friend: 특정 사용자의 친구 목록을 저장합니다.
- Nickname: 친구를 찾기 위한 별칭을 저장합니다.
- Schedule: 특정 날짜와 시간대의 단발성 일정을 저장합니다.
- Routine: 요일 기반 반복 일정을 저장합니다.
- To_meet: 일정에 포함된 친구를 연결합니다.

## 초기화 방법
MySQL 서버가 실행 중이라면 아래처럼 스키마를 적용할 수 있습니다.

```bash
mysql -u root -p < database/schema.sql
```

## 연결 설정
서버는 localhost:3306의 MySQL에 접속하며, 데이터베이스 이름은 meeting_DB입니다. 실행 전 .env 파일에 DB_PASSWORD를 설정해야 합니다.

```env
DB_PASSWORD=your_password
```