-- 1. 데이터베이스(스키마) 생성 및 선택
CREATE DATABASE IF NOT EXISTS meeting_DB;
USE meeting_DB;

-- 2. 기존 테이블이 있다면 의존성 역순으로 삭제 (초기화용)
DROP TABLE IF EXISTS Schedule;
DROP TABLE IF EXISTS Routine;
DROP TABLE IF EXISTS User;

-- 3. User (사용자) 테이블
CREATE TABLE User (
    ID VARCHAR(50) NOT NULL,
    name VARCHAR(50) NOT NULL,
    PRIMARY KEY (ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Schedule (일정) 테이블
CREATE TABLE Schedule (
    Schedule_ID INT NOT NULL AUTO_INCREMENT,
    User_ID VARCHAR(50) NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME DEFAULT NULL,
    location VARCHAR(255) DEFAULT NULL,
    business VARCHAR(255) NOT NULL,
    who JSON DEFAULT NULL,
    PRIMARY KEY (Schedule_ID),
    FOREIGN KEY (User_ID) REFERENCES User(ID) ON DELETE CASCADE,
    CONSTRAINT chk_schedule_time_range
        CHECK (end_time IS NULL OR end_time > start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Routine (반복 일정) 테이블
CREATE TABLE Routine (
    Routine_ID INT NOT NULL AUTO_INCREMENT,
    User_ID VARCHAR(50) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME DEFAULT NULL,
    location VARCHAR(255) DEFAULT NULL,
    business VARCHAR(255) NOT NULL,
    who JSON DEFAULT NULL,
    day_of_week TINYINT NOT NULL,
    start_date DATE DEFAULT NULL,
    end_date DATE DEFAULT NULL,
    PRIMARY KEY (Routine_ID),
    FOREIGN KEY (User_ID) REFERENCES User(ID) ON DELETE CASCADE,
    CONSTRAINT chk_routine_day_of_week
        CHECK (day_of_week BETWEEN 0 AND 6),
    CONSTRAINT chk_routine_clock_range
        CHECK (
            start_time >= '00:00:00'
            AND start_time < '24:00:00'
            AND (
                end_time IS NULL
                OR (end_time >= '00:00:00' AND end_time < '24:00:00')
            )
        ),
    CONSTRAINT chk_routine_time_range
        CHECK (end_time IS NULL OR end_time <> start_time),
    CONSTRAINT chk_routine_date_range
        CHECK (start_date IS NULL OR end_date IS NULL OR start_date <= end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Performance를 위한 인덱스 설정
CREATE INDEX idx_schedule_start ON Schedule(start_time);
CREATE INDEX idx_schedule_location ON Schedule(location);
CREATE INDEX idx_schedule_user_start ON Schedule(User_ID,start_time);
CREATE INDEX idx_routine_user_day ON Routine(User_ID,day_of_week,start_time);
CREATE INDEX idx_routine_end_date ON Routine(end_date);
