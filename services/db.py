import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHOP_DB = os.path.join(BASE_DIR, "data", "shop.db")
LOTTERY_DB = os.path.join(BASE_DIR, "data", "lottery_v2.db")


def get_shop_db():    

    os.makedirs(
        os.path.dirname(SHOP_DB),
        exist_ok=True
    )

    print("========== SHOP DB ==========")
    print(os.path.abspath(SHOP_DB))
    print("=============================")

    conn = sqlite3.connect(SHOP_DB, timeout=30)

    conn.execute("PRAGMA journal_mode=WAL")

    conn.row_factory = sqlite3.Row

    return conn


def get_lottery_db():

    os.makedirs(
        os.path.dirname(LOTTERY_DB),
        exist_ok=True
    )

    print("======= LOTTERY DB =======")
    print(os.path.abspath(LOTTERY_DB))
    print("==========================")

    conn = sqlite3.connect(LOTTERY_DB, timeout=30)

    conn.execute("PRAGMA journal_mode=WAL")

    conn.row_factory = sqlite3.Row

    return conn
