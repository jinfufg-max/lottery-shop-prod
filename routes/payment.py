from flask import Blueprint, render_template, request, redirect
import hashlib
import urllib.parse
from datetime import datetime, timedelta
from services.mail_service import send_admin_order_email

from flask import *
from services.db import get_shop_db
import sqlite3
import bcrypt

from config import (
    ECPAY_MERCHANT_ID,
    ECPAY_HASH_KEY,
    ECPAY_HASH_IV,
)

payment_bp = Blueprint("payment", __name__)


@payment_bp.route("/ecpay_checkout/<order_no>")
def ecpay_checkout(order_no):

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute(
        """
        SELECT
            *,
            (
                SELECT SUM(total)
                FROM orders
                WHERE order_no = ?
            ) AS total_amount
        FROM orders
        WHERE order_no = ?
        LIMIT 1
        """,
        (order_no, order_no),
    )

    order = c.fetchone()

    conn.close()

    print("order_no =", order_no)
    print("order =", order)

    if not order:
        return "訂單不存在"

    # 綠界限制 20 字
    merchant_trade_no = order["order_no"]

    data = {
        "MerchantID": ECPAY_MERCHANT_ID,
        "MerchantTradeNo": merchant_trade_no,
        "MerchantTradeDate": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio",
        "TotalAmount": str(int(order["total_amount"])),
        "TradeDesc": "商品訂單",
        "ItemName": "商品訂單",
        "ReturnURL": "https://lottery-shop-prod.onrender.com/payment_return",        
        "ChoosePayment": "Credit",
        "EncryptType": 1,
    }

    data["CheckMacValue"] = generate_check_mac_value(
        data, ECPAY_HASH_KEY, ECPAY_HASH_IV
    )

    print(data)

    return render_template("ecpay_submit.html", data=data)


def generate_check_mac_value(params, hash_key, hash_iv):

    sorted_params = sorted(params.items())

    encoded_list = []

    for key, value in sorted_params:
        encoded_list.append(f"{key}={value}")

    raw = f"HashKey={hash_key}&" + "&".join(encoded_list) + f"&HashIV={hash_iv}"

    # URL Encode
    encoded = urllib.parse.quote_plus(raw, safe="-_.!*()").lower()

    # 綠界特殊轉換
    encoded = (
        encoded.replace("%2d", "-")
        .replace("%5f", "_")
        .replace("%2e", ".")
        .replace("%21", "!")
        .replace("%2a", "*")
        .replace("%28", "(")
        .replace("%29", ")")
    )

    print("raw =", raw)
    print("encoded =", encoded)

    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


@payment_bp.route("/payment_return", methods=["POST"])
def payment_return():

    print("AAAA callback進來了")

    print("====== 綠界 callback ======")
    print(request.form)

    data = request.form.to_dict()

    received_mac = data.get("CheckMacValue", "")

    data.pop("CheckMacValue", None)

    print("BBBB 驗證前")

    verify_mac = generate_check_mac_value(
        data,
        ECPAY_HASH_KEY,
        ECPAY_HASH_IV
    )

    print("CCCC 驗證通過")

    if verify_mac != received_mac:
        print("❌ CheckMacValue 驗證失敗")
        return "0|fail"

    merchant_trade_no = request.form.get("MerchantTradeNo")
    rtn_code = request.form.get("RtnCode")
    trade_amt = request.form.get("TradeAmt")

    print("trade_amt =", trade_amt)    

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # =========================
    # 付款失敗
    # =========================
    if rtn_code != "1":
        conn.close()
        print("付款失敗")
        return "0|Payment Failed"
    # =========================
    # 查詢訂單
    # =========================
    c.execute(
        """
        SELECT
            *,
            (
                SELECT SUM(total)
                FROM orders
                WHERE order_no = ?
            ) AS total_amount
        FROM orders
        WHERE order_no = ?
        LIMIT 1
        """,
        (merchant_trade_no, merchant_trade_no),
    )

    order = c.fetchone()

    print("DDDD 找到訂單")

    # 找不到訂單
    if not order:
        conn.close()
        return "0|order not found"

    # 驗證付款金額
    if int(trade_amt) != int(order["total_amount"]):
        conn.close()
        print("⚠️ 金額驗證失敗")
        return "0|Amount Error"

    # 防止重複 callback
    if order["status"] == "paid":
        print("⚠️ 重複 callback:", merchant_trade_no)
        conn.close()
        return "1|OK"
    
    print("EEEE 準備更新orders")
    print("111111111111")

    # 更新 orders
    c.execute(
        """
        UPDATE orders
        SET status='paid'
        WHERE order_no=?
        """,
        (merchant_trade_no,),
    )

    print("222222222222")

    # =========================
    # 扣庫存
    # =========================

    c.execute(
        """
        SELECT product_id, qty
        FROM orders
        WHERE order_no = ?
        """,
        (merchant_trade_no,),
    )

    items = c.fetchall()

    print("333333333333")

    print("===== 扣庫存 =====")
    print("merchant_trade_no =", merchant_trade_no)
    print("items =", items)

    for item in items:

        print(
            "扣庫存商品",
            item["product_id"],
            item["qty"]
        )

        c.execute(
            """
            UPDATE products
            SET stock = stock - ?
            WHERE id = ?
            """,
            (
                item["qty"],
                item["product_id"]
            )
        )

        print("rowcount =", c.rowcount)

    # =========================
    # 儲值訂單
    # =========================
    if order["order_type"] == "topup":

        # =====================
        # 加 points
        # =====================
        c.execute(
            """
            UPDATE users
            SET points = points + ?
            WHERE id=?
            """,
            (
                order["total"],
                order["user_id"],
            ),
        )

        # =====================
        # 儲值500送5個大金袋
        # =====================
        if order["total"] >= 500:

            now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

            for _ in range(5):

                c.execute(
                    """
                    INSERT INTO user_bags
                    (
                        user_id,
                        bag_type,
                        numbers,
                        is_opened,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        order["user_id"],
                        "gold",
                        None,
                        0,
                        now,
                    ),
                )
    
    # =========================
    # 更新 transaction
    # =========================
        c.execute(
            """
            UPDATE transactions
            SET status='success'
            WHERE order_no=?
            AND status='pending'
            """,
            (merchant_trade_no,),
        )

        print("FFFF commit前")
        conn.commit()
        print("GGGG commit完成")

        conn.close()
        print("★★★★★★★★CCC★★★★★★★★")

        print("✅ 付款成功:", merchant_trade_no)

        return "1|OK"      

    # =========================
    # 更新訂單狀態
    # =========================
    c.execute(
        """
        UPDATE orders
        SET status='paid'
        WHERE order_no = ?
        """,
        (merchant_trade_no,),
    )

    print("transaction updated =", c.rowcount)

    # =========================
    # 重新取得最新訂單
    # =========================
    c.execute(
        """
        SELECT *
        FROM orders
        WHERE order_no = ?
        """,
        (merchant_trade_no,),
    )

    order = c.fetchone()
    # =========================
    # 會員付款完成 → 建立會員
    # =========================   

    if order and order["order_type"] == "member":     

        # 防止重複建立會員
        if order["is_registered"] == 0:          

            c.execute(
                """
                SELECT id
                FROM users
                WHERE username = ?
                """,
                (order["username"],),
            )

            existing_user = c.fetchone()

            if not existing_user:

                # 建立會員
                c.execute(
                    """
                    INSERT INTO users (
                        username,
                        password,
                        name,
                        points,
                        email,
                        phone,
                        address
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order["username"],
                        order["password"],
                        order["name"],
                        150,
                        order["email"],
                        order["phone"],
                        order["address"],
                    ),
                )

                user_id = c.lastrowid

                # 台灣時間
                now = (datetime.utcnow() + timedelta(hours=8)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                # 發送兩個大金袋
                for _ in range(2):

                    c.execute(
                        """
                        INSERT INTO user_bags (
                            user_id,
                            bag_type,
                            is_opened,
                            created_at
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            "gold",
                            0,
                            now,
                        ),
                    )

            # 標記已完成註冊
            c.execute(
                """
                UPDATE orders
                SET is_registered = 1
                WHERE id = ?
                """,
                (order["id"],),
            )

    # =========================
    # 儲值成功 → 增加準提金
    # =========================
    if order and order["order_type"] == "topup":

        c.execute(
            """
            UPDATE users
            SET points = points + ?
            WHERE id = ?
            """,
            (
                order["total"],
                order["user_id"],
            ),
        )

    # =========================
    # 更新交易狀態
    # =========================
    c.execute(
        """
        UPDATE transactions
        SET status='success'
        WHERE order_no=?
        AND status='pending'
        """,
        (merchant_trade_no,),
    )

    try:
        send_admin_order_email(
            order_no=merchant_trade_no,
            name=order["name"],
            phone=order["phone"],
            total=int(trade_amt),
            payment_type="credit"
        )

        conn.commit()

        print("付款成功")
        print("更新訂單：", merchant_trade_no)
        print("更新交易：", order["id"])

        conn.close()

        return "1|OK"

    except Exception as e:

        conn.rollback()

        print("⚠️ callback commit 失敗")
        print(e)

        conn.close()

        return "0|DB Error"
