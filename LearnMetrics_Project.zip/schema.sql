CREATE DATABASE IF NOT EXISTS elearning_course_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE elearning_course_analytics;
CREATE TABLE students (
 id INT AUTO_INCREMENT PRIMARY KEY, student_code VARCHAR(40) NOT NULL UNIQUE, full_name VARCHAR(120) NOT NULL,
 email VARCHAR(190) NOT NULL UNIQUE, department VARCHAR(100) NOT NULL DEFAULT 'CSE', semester INT NOT NULL DEFAULT 1,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, CONSTRAINT chk_semester CHECK (semester BETWEEN 1 AND 8)
) ENGINE=InnoDB;
CREATE TABLE staff (
 id INT AUTO_INCREMENT PRIMARY KEY, staff_code VARCHAR(40) NOT NULL UNIQUE, full_name VARCHAR(120) NOT NULL,
 email VARCHAR(190) NOT NULL UNIQUE, department VARCHAR(100), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
CREATE TABLE users (
 id INT AUTO_INCREMENT PRIMARY KEY, full_name VARCHAR(120) NOT NULL, email VARCHAR(190) NOT NULL UNIQUE,
 password_hash VARCHAR(255) NOT NULL, role ENUM('admin','staff','student') NOT NULL,
 active TINYINT NOT NULL DEFAULT 1, student_id INT NULL UNIQUE, staff_id INT NULL UNIQUE,
 must_change_password TINYINT NOT NULL DEFAULT 0, last_login DATETIME NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
 FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE courses (
 id INT AUTO_INCREMENT PRIMARY KEY, course_code VARCHAR(40) NOT NULL UNIQUE, title VARCHAR(180) NOT NULL, description TEXT,
 category VARCHAR(60) NOT NULL DEFAULT 'General', difficulty ENUM('Beginner','Intermediate','Advanced') NOT NULL DEFAULT 'Beginner',
 instructor_id INT NULL, duration_hours DECIMAL(6,1) NOT NULL DEFAULT 0, published TINYINT NOT NULL DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (instructor_id) REFERENCES staff(id) ON DELETE SET NULL
) ENGINE=InnoDB;
CREATE TABLE lessons (
 id INT AUTO_INCREMENT PRIMARY KEY, course_id INT NOT NULL, title VARCHAR(180) NOT NULL,
 content_type ENUM('video','document','text','link') NOT NULL DEFAULT 'video', content_url VARCHAR(500), body TEXT,
 position INT NOT NULL, duration_minutes INT NOT NULL DEFAULT 0, UNIQUE KEY uq_lesson_pos (course_id, position),
 FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE enrollments (
 id INT AUTO_INCREMENT PRIMARY KEY, student_id INT NOT NULL, course_id INT NOT NULL, enrolled_at DATETIME NOT NULL,
 status ENUM('active','dropped') NOT NULL DEFAULT 'active', UNIQUE KEY uq_enrollment (student_id, course_id),
 FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
 FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE RESTRICT
) ENGINE=InnoDB;
CREATE TABLE lesson_progress (
 id INT AUTO_INCREMENT PRIMARY KEY, student_id INT NOT NULL, lesson_id INT NOT NULL, completed TINYINT NOT NULL DEFAULT 0,
 completed_at DATETIME NULL, seconds_spent INT NOT NULL DEFAULT 0, last_activity DATETIME NULL,
 UNIQUE KEY uq_progress (student_id, lesson_id),
 FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
 FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE quizzes (
 id INT AUTO_INCREMENT PRIMARY KEY, course_id INT NOT NULL, title VARCHAR(180) NOT NULL, pass_percent INT NOT NULL DEFAULT 40,
 FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE questions (
 id INT AUTO_INCREMENT PRIMARY KEY, quiz_id INT NOT NULL, question_text TEXT NOT NULL, option_a VARCHAR(255) NOT NULL,
 option_b VARCHAR(255) NOT NULL, option_c VARCHAR(255), option_d VARCHAR(255), correct_option ENUM('A','B','C','D') NOT NULL,
 marks INT NOT NULL DEFAULT 1, FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE attempts (
 id INT AUTO_INCREMENT PRIMARY KEY, quiz_id INT NOT NULL, student_id INT NOT NULL, score INT NOT NULL, max_marks INT NOT NULL,
 percentage DECIMAL(5,2) NOT NULL, attempted_at DATETIME NOT NULL, CONSTRAINT chk_score CHECK (score >= 0 AND score <= max_marks),
 FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE RESTRICT,
 FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT
) ENGINE=InnoDB;
CREATE TABLE attempt_answers (
 id INT AUTO_INCREMENT PRIMARY KEY, attempt_id INT NOT NULL, question_id INT NOT NULL, chosen CHAR(1) NULL,
 FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
 FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE activity_logs (
 id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NULL, action VARCHAR(60) NOT NULL, details VARCHAR(255),
 created_at DATETIME NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;
CREATE INDEX idx_progress_activity ON lesson_progress (student_id, last_activity);
CREATE INDEX idx_attempt_student ON attempts (student_id);
CREATE INDEX idx_enroll_course ON enrollments (course_id, status)
