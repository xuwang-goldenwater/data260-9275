-- DATA 260 HW4 - schema for database s9275_rel (PREFIX = s9275)
-- Applied by:  make db-init   (python code/db_init.py)
-- Re-running drops and recreates every table, so it is also the reset script.

CREATE DATABASE IF NOT EXISTS s9275_rel
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE s9275_rel;

DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS recall_notices;
DROP TABLE IF EXISTS firms;
DROP TABLE IF EXISTS users;

-- ---- authentication ------------------------------------------------------

CREATE TABLE users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(100) NOT NULL,
  email         VARCHAR(255) NOT NULL,
  password_hash CHAR(60)     NOT NULL,
  CONSTRAINT uq_users_email UNIQUE (email)
) ENGINE=InnoDB;

-- id is the opaque session token the browser holds in its HTTP-only cookie.
-- Nothing about the user is in the cookie; the server looks the token up here.
CREATE TABLE sessions (
  id          VARCHAR(64) PRIMARY KEY,
  user_id     INT      NOT NULL,
  created_at  DATETIME NOT NULL,
  expires_at  DATETIME NOT NULL,
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---- domain --------------------------------------------------------------

-- Related entity for Part 3 (200 seeded rows; full CRUD comes in a later HW).
CREATE TABLE firms (
  id     INT AUTO_INCREMENT PRIMARY KEY,
  name   VARCHAR(150) NOT NULL,
  state  CHAR(2)      NOT NULL
) ENGINE=InnoDB;

-- Primary entity: primary field = product_name, secondary field = category.
-- InnoDB automatically indexes firm_id because of the foreign key.
-- recall_date is deliberately NOT indexed here: code/sql/hw04_add_index.sql
-- adds that index in Part 3 step 8 so EXPLAIN can be compared before/after.
CREATE TABLE recall_notices (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  product_name  VARCHAR(255) NOT NULL,
  category      VARCHAR(40)  NOT NULL,
  firm_id       INT          NULL,
  recall_date   DATE         NOT NULL,
  CONSTRAINT fk_notices_firm FOREIGN KEY (firm_id) REFERENCES firms (id) ON DELETE SET NULL,
  CONSTRAINT ck_notices_category CHECK (category IN
    ('Undeclared Allergen', 'Bacterial Contamination', 'Foreign Material', 'Mislabeling'))
) ENGINE=InnoDB;
