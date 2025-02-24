import os
import psycopg2
from psycopg2 import pool
import logging
from dotenv import load_dotenv

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 加载环境变量
load_dotenv()

# 数据库连接池
connection_pool = None

def create_database_if_not_exists():
    """检查并创建目标数据库"""
    try:
        # 连接到默认数据库 'postgres'
        conn = psycopg2.connect(
            dbname="postgres",
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT', 5432),
            sslmode='require'
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            # 检查目标数据库是否存在
            db_name = os.getenv('PGDATABASE')
            cur.execute(f"SELECT 1 FROM pg_database WHERE datname='{db_name}'")
            if not cur.fetchone():
                logging.info(f"Database '{db_name}' does not exist. Creating it...")
                cur.execute(f'CREATE DATABASE "{db_name}"')  # 使用双引号支持特殊字符（可选）
                logging.info(f"Database '{db_name}' created successfully.")
            else:
                logging.info(f"Database '{db_name}' already exists.")
    except Exception as e:
        logging.error(f"Failed to check or create database: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()


def initialize_connection_pool():
    """初始化数据库连接池"""
    global connection_pool
    if not connection_pool:
        try:
            create_database_if_not_exists()  # 确保数据库存在
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
            if connection_pool:
                logging.info("Database connection pool initialized successfully.")
            else:
                logging.error("Failed to initialize database connection pool. Pool is None.")
                raise Exception("Database connection pool is None.")
        except Exception as e:
            logging.error(f"Failed to initialize database connection pool: {e}")
            raise


def get_db_connection():
    """获取数据库连接"""
    if not connection_pool:
        logging.error("Database connection pool is not initialized.")
        raise Exception("Database connection pool is not initialized.")
    return connection_pool.getconn()


def release_db_connection(conn):
    """释放数据库连接"""
    if not connection_pool:
        logging.error("Database connection pool is not initialized.")
        raise Exception("Database connection pool is not initialized.")
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
            logging.info("Table 'api_keys' initialized successfully.")

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
            logging.info("Table 'conversions' initialized successfully.")

            conn.commit()
    except Exception as e:
        logging.error(f"Failed to initialize database tables: {e}")
        conn.rollback()
        raise
    finally:
        if conn:
            release_db_connection(conn)


if __name__ == '__main__':
    try:
        initialize_connection_pool()  # 初始化数据库连接池
        init_db()  # 初始化数据库表结构
    finally:
        if connection_pool:
            connection_pool.closeall()
            logging.info("Database connection pool closed.")