-- ============================================================
-- GYM DATASET (4 TABLES)
-- Fictional gym: "PulseFit"
-- Tables: trainers, members, gym_classes, bookings
-- ============================================================

DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS gym_classes;
DROP TABLE IF EXISTS members;
DROP TABLE IF EXISTS trainers;

-- ============================================================
-- 1. TRAINERS
-- ============================================================
CREATE TABLE trainers (
    trainer_id  INT PRIMARY KEY,
    first_name  VARCHAR(50) NOT NULL,
    last_name   VARCHAR(50) NOT NULL,
    specialty   VARCHAR(50),
    email       VARCHAR(100),
    hire_date   DATE
);

INSERT INTO trainers (trainer_id, first_name, last_name, specialty, email, hire_date) VALUES
(1, 'Marcus', 'Reyes',     'Strength & Conditioning', 'marcus.reyes@pulsefit.com',    '2021-03-15'),
(2, 'Elena',  'Novak',     'Yoga & Mobility',         'elena.novak@pulsefit.com',     '2020-06-01'),
(3, 'Jamal',  'Whitfield', 'Boxing & HIIT',           'jamal.whitfield@pulsefit.com', '2022-01-10'),
(4, 'Sophie', 'Turner',    'Pilates',                 'sophie.turner@pulsefit.com',   '2019-11-20'),
(5, 'Daniel', 'Kaya',      'Powerlifting',            'daniel.kaya@pulsefit.com',     '2023-02-05'),
(6, 'Priya',  'Desai',     'Spin & Cardio',           'priya.desai@pulsefit.com',     '2022-08-18');

-- ============================================================
-- 2. MEMBERS
-- ============================================================
CREATE TABLE members (
    member_id       INT PRIMARY KEY,
    first_name      VARCHAR(50) NOT NULL,
    last_name       VARCHAR(50) NOT NULL,
    email           VARCHAR(100),
    date_of_birth   DATE,
    gender          VARCHAR(10),
    join_date       DATE NOT NULL,
    membership_type VARCHAR(20) NOT NULL,   -- Basic / Standard / Premium / Student
    monthly_fee     DECIMAL(8,2) NOT NULL
);

INSERT INTO members (member_id, first_name, last_name, email, date_of_birth, gender, join_date, membership_type, monthly_fee) VALUES
(1,  'Alex',   'Morgan',    'alex.morgan@mail.com',    '1994-05-12', 'M', '2024-01-10', 'Premium',  64.99),
(2,  'Beth',   'Carter',    'beth.carter@mail.com',    '1998-09-23', 'F', '2024-02-14', 'Standard', 44.99),
(3,  'Chris',  'Nolan',     'chris.nolan@mail.com',    '1990-12-01', 'M', '2023-11-05', 'Standard', 44.99),
(4,  'Diana',  'Ferreira',  'diana.ferreira@mail.com', '2001-03-19', 'F', '2024-03-22', 'Basic',    29.99),
(5,  'Ethan',  'Blake',     'ethan.blake@mail.com',    '1996-07-08', 'M', '2023-09-17', 'Premium',  64.99),
(6,  'Farah',  'Hussain',   'farah.hussain@mail.com',  '1999-01-30', 'F', '2024-04-02', 'Standard', 44.99),
(7,  'George', 'Patel',     'george.patel@mail.com',   '2002-11-11', 'M', '2024-01-25', 'Student',  19.99),
(8,  'Hana',   'Kowalski',  'hana.kowalski@mail.com',  '1993-06-27', 'F', '2023-08-14', 'Premium',  64.99),
(9,  'Ivan',   'Petrov',    'ivan.petrov@mail.com',    '1988-02-15', 'M', '2022-12-01', 'Standard', 44.99),
(10, 'Julia',  'Santos',    'julia.santos@mail.com',   '1995-10-05', 'F', '2024-05-19', 'Standard', 44.99),
(11, 'Kabir',  'Sharma',    'kabir.sharma@mail.com',   '2000-04-09', 'M', '2024-02-28', 'Basic',    29.99),
(12, 'Lena',   'Fischer',   'lena.fischer@mail.com',   '1997-08-16', 'F', '2023-10-10', 'Premium',  64.99),
(13, 'Marco',  'Ricci',     'marco.ricci@mail.com',    '1992-01-22', 'M', '2024-03-03', 'Premium',  64.99),
(14, 'Nadia',  'Osei',      'nadia.osei@mail.com',     '1999-05-30', 'F', '2024-04-15', 'Student',  19.99),
(15, 'Owen',   'Bright',    'owen.bright@mail.com',    '1991-09-02', 'M', '2023-07-21', 'Standard', 44.99);

-- ============================================================
-- 3. GYM CLASSES
-- ============================================================
CREATE TABLE gym_classes (
    class_id      INT PRIMARY KEY,
    class_name    VARCHAR(50) NOT NULL,
    trainer_id    INT,
    category      VARCHAR(30),
    duration_mins INT,
    max_capacity  INT,
    FOREIGN KEY (trainer_id) REFERENCES trainers(trainer_id)
);

INSERT INTO gym_classes (class_id, class_name, trainer_id, category, duration_mins, max_capacity) VALUES
(1, 'Vinyasa Flow',        2, 'Yoga',     60, 20),
(2, 'Boxing Fundamentals', 3, 'Combat',   45, 15),
(3, 'HIIT Blast',          3, 'Cardio',   30, 18),
(4, 'Pilates Core',        4, 'Pilates',  50, 16),
(5, 'Powerlifting 101',    5, 'Strength', 60, 10),
(6, 'Spin Express',        6, 'Cardio',   40, 22),
(7, 'Strength Circuits',   1, 'Strength', 55, 14),
(8, 'Mobility & Stretch',  2, 'Recovery', 30, 25);

-- ============================================================
-- 4. BOOKINGS (member <-> class attendance)
-- ============================================================
CREATE TABLE bookings (
    booking_id   INT PRIMARY KEY,
    member_id    INT NOT NULL,
    class_id     INT NOT NULL,
    booking_date DATE NOT NULL,
    status       VARCHAR(20) NOT NULL,   -- Attended / No-show / Cancelled
    FOREIGN KEY (member_id) REFERENCES members(member_id),
    FOREIGN KEY (class_id) REFERENCES gym_classes(class_id)
);

INSERT INTO bookings (booking_id, member_id, class_id, booking_date, status) VALUES
(1,  1,  5, '2026-08-14', 'Attended'),
(2,  4,  3, '2026-08-15', 'Attended'),
(3,  5,  7, '2026-08-15', 'Attended'),
(4,  6,  1, '2026-08-15', 'Attended'),
(5,  8,  2, '2026-08-16', 'No-show'),
(6,  10, 6, '2026-08-17', 'Attended'),
(7,  11, 4, '2026-08-17', 'Attended'),
(8,  12, 5, '2026-08-18', 'Attended'),
(9,  14, 8, '2026-08-18', 'Cancelled'),
(10, 2,  6, '2026-08-19', 'Attended'),
(11, 3,  2, '2026-08-19', 'Attended'),
(12, 7,  1, '2026-08-20', 'Attended'),
(13, 9,  5, '2026-08-20', 'No-show'),
(14, 13, 2, '2026-08-20', 'Attended'),
(15, 15, 6, '2026-08-13', 'Attended'),
(16, 1,  8, '2026-08-12', 'Attended'),
(17, 6,  4, '2026-08-12', 'Cancelled'),
(18, 9,  7, '2026-08-11', 'Attended'),
(19, 12, 1, '2026-08-11', 'Attended'),
(20, 8,  3, '2026-08-10', 'Attended');

-- ============================================================
-- END OF DATASET
-- ============================================================
