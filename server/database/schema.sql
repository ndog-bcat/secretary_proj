-- 1. 데이터베이스(스키마) 생성 및 선택
CREATE DATABASE IF NOT EXISTS meeting_DB;
USE meeting_DB;

-- 2. 기존 테이블이 있다면 의존성 역순으로 삭제 (초기화용)
DROP TABLE IF EXISTS Nickname;
DROP TABLE IF EXISTS To_meet;
DROP TABLE IF EXISTS Schedule;
DROP TABLE IF EXISTS Friend;
DROP TABLE IF EXISTS User;

-- 3. User (사용자) 테이블
CREATE TABLE User (
    ID VARCHAR(50) NOT NULL,
    name VARCHAR(50) NOT NULL,
    PRIMARY KEY (ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Friend (친구/지인) 테이블
CREATE TABLE Friend (
    Friend_ID INT NOT NULL AUTO_INCREMENT,
    User_ID VARCHAR(50) NOT NULL,
    name VARCHAR(50) NOT NULL,
    PRIMARY KEY (Friend_ID),
    FOREIGN KEY (User_ID) REFERENCES User(ID) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Nickname (
    nickname VARCHAR(50) NOT NULL,
    Friend_ID INT NOT NULL,
    PRIMARY KEY (nickname, Friend_ID), -- 복합키(Composite Key)
    FOREIGN KEY (Friend_ID) REFERENCES Friend(Friend_ID) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Schedule (일정) 테이블
CREATE TABLE Schedule (
    Schedule_ID INT NOT NULL AUTO_INCREMENT,
    User_ID VARCHAR(50) NOT NULL,
    start_time DATETIME NOT NULL,      -- MySQL은 날짜 관리를 위해 DATETIME 사용
    end_time DATETIME DEFAULT NULL,
    location VARCHAR(255) DEFAULT NULL,
    business VARCHAR(255) NOT NULL,    -- 일정 내용 (예: 스벅에서 커피)
    PRIMARY KEY (Schedule_ID),
    FOREIGN KEY (User_ID) REFERENCES User(ID) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. To_meet (일정-지인 매핑 테이블, N:M 관계 해소)
CREATE TABLE To_meet (
    Schedule_ID INT NOT NULL,
    Friend_ID INT NOT NULL,
    PRIMARY KEY (Schedule_ID, Friend_ID), -- 복합키(Composite Key)
    FOREIGN KEY (Schedule_ID) REFERENCES Schedule(Schedule_ID) ON DELETE CASCADE,
    FOREIGN KEY (Friend_ID) REFERENCES Friend(Friend_ID) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 시간 검색 속도 향상을 위한 인덱스
CREATE INDEX idx_schedule_start ON Schedule(start_time);

-- "스벅 갔던" 같은 텍스트 패턴 검색 속도 향상을 위한 인덱스
CREATE INDEX idx_schedule_location ON Schedule(location);