import psycopg2
from psycopg2.extras import RealDictCursor
import os
import socket
from urllib.parse import urlparse
def get_db_connection():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("❌ DATABASE_URL not set")
        return None

    try:
        # Parse hostname
        parsed = urlparse(dsn)
        hostname = parsed.hostname

        # Force IPv4 lookup
        ipv4_addr = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]

        # Append hostaddr safely
        connector_dsn = dsn
        if "hostaddr" not in connector_dsn:
            if "?" in connector_dsn:
                connector_dsn += f"&hostaddr={ipv4_addr}"
            else:
                connector_dsn += f"?hostaddr={ipv4_addr}"

        conn = psycopg2.connect(connector_dsn)
        return conn

    except Exception as e:
        print("❌ Database connection failed:", e)
        return None


def db_reset():
    conn = None
    cursor = None  # Initialize cursor to None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DROP SCHEMA public CASCADE;")
        cursor.execute("CREATE SCHEMA public;")
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print("Database reset error:", e)
    finally:
       print("delete db")
       if cursor is not None:
            try:
                cursor.close()
            except Exception as e:
                print("cursor.close() error:", e) 
    if conn is not None:
            try:
                conn.close()
            except Exception as e:
                print("conn.close() error:", e)
def db_init():
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS purification_zones (
            id SERIAL PRIMARY KEY,
            image_urls JSONB,
            serial TEXT NOT NULL,
            year TEXT NOT NULL,
            district TEXT NOT NULL,
            type TEXT NOT NULL,
            project_name TEXT NOT NULL,
            maintain_unit TEXT,
            adopt_unit TEXT ,
            area FLOAT,
            length FLOAT,
            subsidy_source TEXT,
            maintain_start_date DATE,
            maintain_end_date DATE,
            gps TEXT,
            annotation TEXT, 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS green_walls (
            id SERIAL PRIMARY KEY,
            image_urls JSONB,
            serial TEXT NOT NULL,
            year TEXT NOT NULL,
            district TEXT NOT NULL,
            type TEXT NOT NULL,
            project_name TEXT NOT NULL,
            maintain_unit TEXT,
            adopt_unit TEXT,
            area FLOAT,
            length FLOAT,
            subsidy_source TEXT,
            maintain_start_date DATE,
            maintain_end_date DATE,
            gps TEXT,
            annotation TEXT, 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS greenifications (
            id SERIAL PRIMARY KEY,
            image_urls JSONB,
            serial TEXT NOT NULL,
            year TEXT NOT NULL,
            district TEXT NOT NULL,
            type TEXT NOT NULL,
            project_name TEXT ,
            maintain_unit TEXT ,
            adopt_unit TEXT NOT NULL,
            area FLOAT,
            length FLOAT,
            subsidy_source TEXT,
            maintain_start_date DATE,
            maintain_end_date DATE,
            gps TEXT,
            annotation TEXT, 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tree_intros (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,     
            scientific_name TEXT NOT NULL,
            plant_phenology TEXT NOT NULL,
            features TEXT NOT NULL,
            natural_distribution TEXT, 
            usage TEXT, 
            other_usage TEXT, 
            breeding_intro TEXT, 
            source TEXT, 
            image_url TEXT
        );

        CREATE TABLE IF NOT EXISTS result (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            date DATE NOT NULL,
            content TEXT NOT NULL,
            image_url TEXT
        );

        CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            date DATE NOT NULL,
            note TEXT NOT NULL,
            file_url TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            id SERIAL PRIMARY KEY,
            section VARCHAR(50) UNIQUE NOT NULL,
            visible BOOLEAN NOT NULL DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS site_sections (
            key TEXT PRIMARY KEY,         
            label TEXT NOT NULL,          
            is_visible BOOLEAN NOT NULL DEFAULT TRUE
        );

        INSERT INTO site_sections (key, label, is_visible) VALUES
        ('purification',  '空氣品質淨化區', TRUE),
        ('green_wall',    '清淨綠牆',     FALSE),
        ('greenification','綠美化',       TRUE)
        ON CONFLICT (key) DO NOTHING;

  
        INSERT INTO settings (section, visible) VALUES ('greenifications', TRUE);
        INSERT INTO settings (section, visible) VALUES ('green wall', TRUE);
        INSERT INTO settings (section, visible) VALUES ('purification_zones', TRUE);

    """)
    cursor.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public';
    """)
    
    tables = cursor.fetchall()
    print("🧾 現有資料表：", tables)
    cursor.execute("""
    INSERT INTO users (username, password_hash)
    VALUES ('admin', %s)
    ON CONFLICT (username) DO NOTHING;
""", (
    "$2b$12$mWDTduoWmB3EEjk8zP1hgenkaCLO1I5xfm13A3RtwsTjr9xAzVa6S",  # bcrypt('admin123')
))



    # cursor.execute("SELECT * FROM users WHERE username = %s;", ('admin',))
    # if cursor.fetchone() is None:
    #     cursor.execute(
    #         "INSERT INTO users (username, password_hash) VALUES (%s, %s);",
    #         ('admin', '$2b$12$T99dG6zszENfIoAhu7JMTuAAy7YYQ5m8B5eGFt7LzC2OhR7W7X3gq') 
    #     )
    #     print("[✅] 預設 admin 帳號已建立")
    # else:
    #     print("[ℹ️] admin 帳號已存在，略過建立")
    conn.commit()
    cursor.close()
    conn.close()

