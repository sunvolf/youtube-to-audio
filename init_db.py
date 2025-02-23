import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import logging
from dotenv import load_dotenv

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 加载环境变量
load_dotenv()

# 数据库连接池
try:
    connection_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        dbname=os.getenv('PGDATABASE'),
        user=os.getenv('PGUSER'),
        password=os.getenv('PGPASSWORD'),
        host=os.getenv('PGHOST'),  # AWS RDS 主机名
        port=os.getenv('PGPORT', 5432),  # 默认端口为 5432
        sslmode='require'  # 使用 SSL 连接
    )
    logging.info("Database connection pool initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize database connection pool: {e}")
    raise

def get_db_connection():
    return connection_pool.getconn()

def release_db_connection(conn):
    connection_pool.putconn(conn)

def init_db():
    """初始化数据库表结构（如果不存在）"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # 创建API密钥表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id SERIAL PRIMARY KEY,
                    key VARCHAR(36) UNIQUE NOT NULL,
                    expiry_time TIMESTAMPTZ NOT NULL
                )
            ''')
            # 创建任务记录表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS conversions (
                    id SERIAL PRIMARY KEY,
                    task_id VARCHAR(255) UNIQUE NOT NULL,
                    youtube_id VARCHAR(11) NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            conn.commit()
        logging.info("Database tables initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize database tables: {e}")
    finally:
        if conn:
            release_db_connection(conn)

if __name__ == '__main__':
    try:
        init_db()
    finally:
        if connection_pool:
            connection_pool.closeall()
            logging.info("Database connection pool closed.")