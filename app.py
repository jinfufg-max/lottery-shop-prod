from flask import Flask, render_template, request, redirect, session, flash, Response

from services.db import get_shop_db, get_lottery_db
from routes.bag import generate_numbers

from routes.auth import auth_bp
from routes.check import check_bp

from services.init_db import *
from services.init_all import init_all
from services.ai_tools import *
from ai.engine import (
    get_lottery_data,
    special_analysis_with_score,
    generate_analysis_data,
    get_ai_numbers,
    AI_STATE,
    HIT_CACHE,
    update_ai_background,
    refresh_ai_cache,
)

import sqlite3
import os
import json
import pandas as pd
import random

import hashlib
from urllib.parse import quote_plus
from services.mail_service import send_welcome_email

from collections import Counter
from datetime import datetime, timedelta

from routes.bag import bag_bp, settle_lottery
from routes.shop import shop_bp
from routes.payment import payment_bp
from routes.analysis import analysis_bp
from routes.admin import admin_bp
from routes.page import page_bp

# =========================
# 綠界設定
# =========================

from config import (
    ECPAY_MERCHANT_ID,
    ECPAY_HASH_KEY,
    ECPAY_HASH_IV,
    EMAIL_ACCOUNT,
    EMAIL_PASSWORD,
)

ECPAY_API_URL = "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"


# =========================
# 綠界 CheckMacValue
# =========================


def generate_check_mac_value(params):

    sorted_params = sorted(params.items())

    raw = f"HashKey={ECPAY_HASH_KEY}"

    for key, value in sorted_params:
        raw += f"&{key}={value}"

    raw += f"&HashIV={ECPAY_HASH_IV}"

    raw = quote_plus(raw).lower()

    replace_map = {
        "%21": "!",
        "%28": "(",
        "%29": ")",
        "%2a": "*",
        "%2d": "-",
        "%2e": ".",
        "%5f": "_",
    }

    for k, v in replace_map.items():
        raw = raw.replace(k, v)

    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


import logging

import config

app = Flask(__name__)

logging.basicConfig(filename="error.log", level=logging.ERROR)

init_all()

app.permanent_session_lifetime = timedelta(hours=1)

app.register_blueprint(shop_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(bag_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(check_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(page_bp)


@app.context_processor
def inject_user():
    user_id = session.get("user_id")
    balance = 0

    if user_id:
        conn = None
        try:
            conn = get_shop_db()
            c = conn.cursor()

            c.execute("SELECT points FROM users WHERE id=?", (user_id,))
            row = c.fetchone()

            if row:
                balance = row[0]

        except Exception as e:
            print("inject_user error:", e)

        finally:
            if conn:
                conn.close()

    return dict(global_money=balance)


@app.before_request
def make_session_permanent():
    session.permanent = True


# ===== 註冊設定（核心）=====
IS_REGISTER_FREE = True  # 🔥 現在免費（測試用）
REGISTER_PRICE = 100  # 未來價格
REGISTER_BONUS = 150  # 註冊送點
app.secret_key = "xup6g/4q/6bp4vul4rm0 xup6504d93xup65p 2u4xup6u.4w/6"
ALLOW_CUSTOM_TOPUP = True  # 🔥 測試用開關

# ===== 首頁 =====


@app.route("/")
def index():

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # ===== 熱銷商品 =====

    hot_products = c.execute("""
        SELECT *
        FROM products
        WHERE status=1
        LIMIT 4
    """).fetchall()

    # ===== 本週時間 =====
    start = datetime.now() - timedelta(days=7)

    end = datetime.now()

    # ===== 本週開袋總數 =====
    c.execute(
        """
        SELECT COUNT(*)
        FROM user_bags
        WHERE status='settled'
        AND date(settled_at) BETWEEN ? AND ?
    """,
        (
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        ),
    )

    row = c.fetchone()

    weekly_opened = row[0] if row else 0

    # ===== 歷史最高 =====
    c.execute("""
        SELECT MAX(hit_count)
        FROM user_bags
        WHERE status='settled'
    """)

    best_row = c.fetchone()

    history_best = best_row[0] if best_row and best_row[0] else 0

    # ===== 本週資料 =====
    c.execute(
        """
        SELECT hit_count
        FROM user_bags
        WHERE status='settled'
        AND date(settled_at) BETWEEN ? AND ?
    """,
        (
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        ),
    )

    rows = c.fetchall()

    # ===== 補0 =====
    dist = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    for r in rows:
        hit = r["hit_count"]
        if hit in dist:
            dist[hit] += 1

    # ===== 命中統計 =====
    hit3 = dist.get(3, 0)

    hit4 = dist.get(4, 0)

    hit5 = max([k for k, v in dist.items() if v > 0], default=0)

    # ===== 本週總數 =====
    total = sum(dist.values())

    conn.close()

    # ===== 原本資料 =====
    now = datetime.now()
    today = now.strftime("%Y/%m/%d")
    current_time = now.strftime("%H:%M")

    conn2 = get_lottery_db()
    c2 = conn2.cursor()

    c2.execute("SELECT COUNT(*) FROM lottery_results")
    total_periods = c2.fetchone()[0]

    conn2.close()

    total_runs = total_periods * 50

   # ===== AI首頁資料 =====
    analysis_data = AI_STATE.get("analysis_data", {})

    ai_data = {
        "hot": " / ".join(f"{n:02d}" for n in analysis_data.get("hot", [])),
        "cold": " / ".join(f"{n:02d}" for n in analysis_data.get("cold", [])),
        "hit_rate": analysis_data.get("hit_rate", "計算中"),
    }

    main_data = get_lottery_data()

    print("MAIN_DATA =", main_data)
    print("LEN =", len(main_data) if main_data else 0)

    flat = [n for row in main_data for n in row]

    count = Counter(flat)

    if not count:
        hot_score = 0
    else:
        sorted_hot = sorted(count.items(), key=lambda x: (-x[1], x[0]))

        top5_total = sum(v for _, v in sorted_hot[:5])

        all_total = sum(count.values())

        hot_score = round((top5_total / all_total) * 100, 1)
        
    # ===== 回傳 =====
    return render_template(
        "index.html",
        # ===== 基本 =====
        total_runs=total_runs,
        total_periods=total_periods,
        today=today,
        current_time=current_time,
        # ===== 開獎速報 =====
        weekly_opened=weekly_opened,
        hit5=hit5,
        total=total,
        hit3=hit3,
        hit4=hit4,

        hot_products=hot_products,
        history_best=history_best,
        tracking_periods=total_periods,
        # ===== AI分析 =====
        hot_score=hot_score,
        hot=ai_data["hot"],
        cold=ai_data["cold"],
        hit_rate=ai_data["hit_rate"],
    )


# =========================
# 🔥 讀取 AI 快取
# =========================
@app.route("/ai", methods=["GET", "POST"])
def ai_page():

    # =========================
    # 🔷 GET：只顯示舊結果
    # =========================
    if request.method == "GET":

        return render_template(
            "ai.html",
            numbers=session.get("ai_numbers"),
            special=session.get("ai_special"),
            remaining=session.get("ai_remaining"),
            is_member=session.get("ai_is_member"),
            error=session.get("ai_error"),
        )

    # =========================
    # 🔷 身分判斷
    # =========================
    if "user" in session:
        identifier = session["user"]
        is_member = True

    else:
        identifier = request.remote_addr
        is_member = False

    remaining = None

    # =========================
    # 🔷 使用限制
    # =========================

    today = datetime.now().strftime("%Y-%m-%d")

    can_use = can_use_ai(identifier)

    # ===== 非會員 =====
    if not is_member:

        remaining = 1 if can_use else 0

        if not can_use:

            session["ai_error"] = "今日已使用AI推薦"
            session["ai_numbers"] = None
            session["ai_special"] = None
            session["ai_remaining"] = remaining
            session["ai_is_member"] = False

            return redirect("/ai")

    # ===== 會員 =====
    else:
        user_id = session.get("user_id")

        conn = get_shop_db()
        c = conn.cursor()

        # 今日使用次數
        c.execute(
            """
            SELECT COUNT(*)
            FROM ai_usage
            WHERE identifier=?
            AND date(created_at)=?
        """,
            (identifier, today),
        )

        used_count = c.fetchone()[0]

        free_left = max(0, 5 - used_count)

        remaining = free_left

        # ===== 超過5次 =====
        if used_count >= 6:

            # 查點數
            c.execute("SELECT points FROM users WHERE id=?", (user_id,))

            row = c.fetchone()

            points = row[0] if row else 0

            # 點數不足
            if points < 1:

                conn.close()

                session["ai_error"] = "準提金不足"
                session["ai_numbers"] = None
                session["ai_special"] = None
                session["ai_remaining"] = 0
                session["ai_is_member"] = True

                return redirect("/ai")

            # 扣1點
            c.execute(
                """
                UPDATE users
                SET points = points - 1
                WHERE id=?
            """,
                (user_id,),
            )

            conn.commit()

        conn.close()

    # =========================
    # 🔷 AI產號
    # =========================
    history = get_lottery_data()

    main_numbers = get_ai_numbers(history)

    special = random.choice([n for n in range(1, 50) if n not in main_numbers])

    # =========================
    # 🔷 紀錄使用
    # =========================
    record_ai_use(identifier)

    # =========================
    # 🔷 存進 session
    # =========================
    session["ai_numbers"] = main_numbers
    session["ai_special"] = special
    session["ai_remaining"] = remaining
    session["ai_is_member"] = is_member
    session["ai_error"] = None

    # =========================
    # 🔷 超重要：PRG
    # =========================
    return redirect("/ai")

    UPLOAD_FOLDER = "static/uploads"


@app.route("/register_after_pay", methods=["GET", "POST"])
def register_after_pay():

    print("===== register_after_pay =====")

    order_no = request.args.get("order_no")

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM orders WHERE order_no=?", (order_no,))

    order = c.fetchone()

    if not order:
        return "訂單不存在"

    if order["status"] != "paid":
        conn.close()
        return "訂單尚未付款"

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")
        email = request.form.get("email")
        phone = request.form.get("phone")
        address = request.form.get("address")

        from werkzeug.security import generate_password_hash

        password_hash = generate_password_hash(password)

        # 防重複帳號
        c.execute("SELECT id FROM users WHERE username=?", (username,))

        exist = c.fetchone()

        if exist:
            return "帳號已存在"

        # 建立會員
        c.execute(
            """
            INSERT INTO users (
                username,
                password,
                name,
                email,
                phone,
                address,
                points
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (username, password_hash, order["name"], email, phone, address, 150),
        )

        user_id = c.lastrowid

        print("開始送福袋")
        print(user_id)

        # 送大金袋 x2

        try:
            send_welcome_email(
                email=email,
                username=username,
                points=150,
            )
        except Exception as e:
            print("歡迎信失敗:", e)



        for _ in range(2):

            print("送出第", _)

            c.execute(
                """
                INSERT INTO user_bags
                (
                    user_id,
                    bag_type,
                    numbers,
                    is_opened,
                    created_at,
                    hit_count,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    "gold",
                    "",
                    0,
                    (datetime.utcnow() + timedelta(hours=8)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    0,
                    "pending",
                ),
            )

        c.execute(
            """
            UPDATE orders
            SET is_registered=1
            WHERE id=?
            AND is_registered=0
            """,
            (order["id"],),
        )

        if c.rowcount == 0:
            conn.close()
            return redirect("/login")

        conn.commit()
        conn.close()

        return redirect("/login")

    return render_template("register_after_pay.html", order_no=order_no)


# ===== 啟動 =====
if __name__ == "__main__":

    # 先建立 AI_STATE
    refresh_ai_cache()

    # 啟動AI生命週期
    # update_ai_background()

    # 啟動 Flask
    app.run(debug=False)
