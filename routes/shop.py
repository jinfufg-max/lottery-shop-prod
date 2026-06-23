from flask import *
from services.db import *
import sqlite3
import random
import uuid
from datetime import datetime, timedelta

from services.mail_service import (
    send_order_email,
    send_admin_order_email
)

from flask import Blueprint, session

shop_bp = Blueprint("shop", __name__)

ADMIN_USERS = ["admin"]

# =========================
# 商城規則
# =========================

SHIPPING_FEE = 100

CASH_FREE_SHIPPING = 3000
CASH_DISCOUNT = 6000

POINT_FREE_SHIPPING = 1500

POINT_DISCOUNT = 3000

POINT_DISCOUNT_RATE = 0.95


def is_admin():
    return session.get("user") in ADMIN_USERS


def clear_expired_orders():

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    limit_time = (
        datetime.utcnow() + timedelta(hours=8) - timedelta(minutes=30)
    ).strftime("%Y-%m-%d %H:%M:%S")

    # 找過期 pending
    c.execute(
        """
        SELECT id, product_id, qty
        FROM orders
        WHERE status='pending'
        AND created_at < ?
        """,
        (limit_time,),
    )

    rows = c.fetchall()

    for row in rows:

        # 補回庫存
        c.execute(
            """
            UPDATE products
            SET stock = stock + ?
            WHERE id=?
            """,
            (row["qty"], row["product_id"]),
        )

        # 改 expired
        c.execute(
            """
            UPDATE orders
            SET status='expired'
            WHERE id=?
            """,
            (row["id"],),
        )

    conn.commit()
    conn.close()


@shop_bp.route("/shop")
def shop():
    # clear_expired_orders()
    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    keyword = request.args.get("q", "").strip()

    if keyword:

        like = f"%{keyword}%"

        food = c.execute(
            """
            SELECT *
            FROM products
            WHERE category_id=1
            AND status=1
            AND (
                name LIKE ?
                OR desc LIKE ?
            )
            """,
            (like, like)
        ).fetchall()

        accessory = c.execute(
            """
            SELECT *
            FROM products
            WHERE category_id=2
            AND status=1
            AND (
                name LIKE ?
                OR desc LIKE ?
            )
            """,
            (like, like)
        ).fetchall()

        ritual = c.execute(
            """
            SELECT *
            FROM products
            WHERE category_id=3
            AND status=1
            AND (
                name LIKE ?
                OR desc LIKE ?
            )
            """,
            (like, like)
        ).fetchall()

    else:

        food = c.execute(
            """
            SELECT *
            FROM products
            WHERE category_id=1
            AND status=1
            """
        ).fetchall()

        accessory = c.execute(
            """
            SELECT *
            FROM products
            WHERE category_id=2
            AND status=1
            """
        ).fetchall()

        ritual = c.execute(
            """
            SELECT *
            FROM products
            WHERE category_id=3
            AND status=1
            """
        ).fetchall()

    user_id = session.get("user_id")

    user_points = 0

    if user_id:

        c.execute("SELECT points FROM users WHERE id=?", (user_id,))

        user = c.fetchone()

        if user:
            user_points = user["points"]

    conn.close()

    return render_template(
        "shop.html",
        food=food,
        accessory=accessory,
        ritual=ritual,
        user_points=user_points,
    )


@shop_bp.route("/admin/products", methods=["GET", "POST"])
def admin_products():

    if not is_admin():
        return "❌ 無權限"

    conn = get_shop_db()
    c = conn.cursor()

    if request.method == "POST":

        name = request.form["name"]

        try:
            stock = int(request.form["stock"])
            price = int(request.form["price"])

        except:
            conn.close()
            return "數值錯誤"

        if price <= 0:
            conn.close()
            return "價格必須大於0"

        if stock < 0:
            conn.close()
            return "庫存不可小於0"

        desc = request.form["description"]

        image1 = request.form["image1"]

        image2 = request.form["image2"]

        category_id = int(request.form["category_id"])

        c.execute(
            """
            INSERT INTO products (
                name,
                price,
                stock,
                desc,
                image1,
                image2,
                category_id,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                price,
                stock,
                desc,
                image1,
                image2,
                category_id,
                1,
            ),
        )

        conn.commit()

    products = c.execute("SELECT * FROM products").fetchall()
    conn.close()

    return render_template("admin_products.html", products=products)


@shop_bp.route("/checkout/<int:pid>")
def checkout(pid):

    flash("單品結帳已停用，請使用購物車結帳")
    return redirect("/cart")
    

# ===== 舊單商品流程（停用）=====
# checkout.html
# create_order()
# 保留備份，未來移除
@shop_bp.route("/create_order", methods=["POST"])
def create_order():

    token = request.form.get("token")

    if not token or token != session.get("checkout_token"):
        flash("請勿重複提交訂單")
        return redirect("/shop")

    session.pop("checkout_token", None)

    product_id = request.form.get("id")
    name = request.form.get("name")
    phone = request.form.get("phone")
    address = request.form.get("address")
    email = request.form.get("email")
    payment = request.form.get("payment_type")

    # ===== 數量 =====
    qty_raw = request.form.get("qty", "1")

    try:
        qty = int(qty_raw)
    except:
        return "數量格式錯誤"

    if qty < 1 or qty > 25:
        return "數量必須在 1~25"

    # ===== 基本檢查 =====
    if not product_id:
        return "缺少商品ID"

    try:
        product_id = int(product_id)
    except:
        return "商品ID錯誤"

    if not name or not phone or not address or not email:
        return "請填完整資料"

    # 👤 姓名驗證
    if len(name.strip()) < 2:
        return "姓名過短"

    if len(name) > 30:
        return "姓名過長"

    # 📞 電話驗證
    if not phone.isdigit():
        return "電話格式錯誤"

    if len(phone) < 8 or len(phone) > 15:
        return "電話長度錯誤"

    # 🏠 地址驗證
    if len(address) < 5:
        return "地址過短"

    if len(address) > 200:
        return "地址過長"

    # 💳 付款方式驗證
    allowed_payments = ["cash", "points"]

    if payment not in allowed_payments:
        return "付款方式錯誤"

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:

        # ===== 商品 =====
        c.execute("SELECT * FROM products WHERE id=?", (product_id,))
        product = c.fetchone()

        if not product:
            return "商品不存在"

        price = product["price"]
        product_name = product["name"]

        stock = product["stock"]

        if qty > stock:
            return "庫存不足"

        subtotal = price * qty

        # ===== 運費 =====
        shipping = SHIPPING_FEE

        # 現金付款：滿3000免運
        if payment == "cash" and subtotal >= CASH_FREE_SHIPPING:
            shipping = 0

        # ===== 使用者 =====
        username = session.get("user")
        is_member = username is not None

        # =========================
        # 💰 點數付款
        # =========================
        if payment == "points":

            if "user_id" not in session:
                return "請重新登入"

            if not is_member:
                return redirect("/login")

            # ===== 準提金運費 =====
            point_shipping = SHIPPING_FEE

            # 滿1500免運
            if subtotal >= POINT_FREE_SHIPPING:
                point_shipping = 0

            final_total = int(subtotal * POINT_DISCOUNT_RATE) + point_shipping

            # 🔥 原子扣款（防洗幣）
            c.execute(
                """
                UPDATE users
                SET points = points - ?
                WHERE username = ? AND points >= ?
                """,
                (final_total, username, final_total),
            )

            if c.rowcount == 0:
                return "扣款失敗（餘額不足）"

            # ===== 真扣庫存（防超賣） =====
            c.execute(
                """
                UPDATE products
                SET stock = stock - ?
                WHERE id=? AND stock >= ?
                """,
                (qty, product_id, qty),
            )

            if c.rowcount == 0:
                conn.rollback()
                return "庫存不足"

            # ===== 扣款後餘額 =====
            c.execute(
                "SELECT points FROM users WHERE username=?",
                (username,),
            )

            new_balance = c.fetchone()["points"]

            # ===== 時間 =====
            now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

            # ===== 訂單編號 =====
            order_no = (
                "ORD"
                + (datetime.utcnow() + timedelta(hours=8)).strftime("%m%d%H%M%S")
                + str(random.randint(1000, 9999))
            )

            # =========================
            # 建立訂單
            # =========================
            c.execute(
                """
                INSERT INTO orders (
                    product_id,
                    product_name,
                    price,
                    subtotal,
                    shipping,
                    total,
                    qty,
                    name,
                    phone,
                    address,
                    email,
                    payment_method,
                    status,
                    username,
                    order_no,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    product_name,
                    price,
                    subtotal,
                    point_shipping,
                    final_total,
                    qty,
                    name,
                    phone,
                    address,
                    email,
                    payment,
                    "paid",
                    username,
                    order_no,
                    now,
                ),
            )

            # 🔥 真正訂單ID
            order_id = c.lastrowid

            # =========================
            # 寫入交易紀錄
            # =========================
            c.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    type,
                    status,
                    amount,
                    balance_before,
                    balance_after,
                    source_type,
                    source_id,
                    note,
                    transaction_no,
                    order_no,
                    action_type,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["user_id"],
                    "spend",
                    "success",
                    final_total,
                    new_balance + final_total,
                    new_balance,
                    "shop_order",
                    order_id,
                    f"購買商品：{product_name}",
                    f"TXN{order_id}",
                    order_no,
                    "points_payment",
                    "{}",
                    (datetime.utcnow() + timedelta(hours=8)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                ),
            )

            # =========================
            # points 正式寫入寄送訂單成功 EMAIL
            # =========================
            conn.commit()

            send_order_email(
                to_email=email,
                order_no=order_no,
                total=final_total
            )

            send_admin_order_email(
                order_no=order_no,
                name=name,
                phone=phone,
                total=final_total,
                payment_type=payment
            )

            print("★★★★ 管理員通知信開始寄送 ★★★★")

            subject = f"🔔 新訂單通知 {order_no}"

            return render_template(
                "order_success.html",
                price=price,
                qty=qty,
                subtotal=subtotal,
                shipping=point_shipping,
                total=final_total,
                payment=payment,
                name=name,
            )

        elif payment == "cash":

            user_id = session.get("user_id", 0)

            final_total = subtotal + shipping

            # 現金付款：滿6000再95折

            if subtotal >= CASH_DISCOUNT:
                final_total = int(final_total * POINT_DISCOUNT_RATE)

            # ===== 真扣庫存（防超賣） =====
            c.execute(
                """
                UPDATE products
                SET stock = stock - ?
                WHERE id=? AND stock >= ?
                """,
                (qty, product_id, qty),
            )

            if c.rowcount == 0:
                conn.rollback()
                return "庫存不足"

            # ===== 時間 =====
            now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

            # ===== 訂單編號 =====
            order_no = (
                "ORD"
                + (datetime.utcnow() + timedelta(hours=8)).strftime("%m%d%H%M%S")
                + str(random.randint(1000, 9999))
            )

            print("order_no =", order_no)

            # =========================
            # 建立訂單
            # =========================
            c.execute(
                """
                INSERT INTO orders (
                    product_id,
                    product_name,
                    price,
                    subtotal,
                    shipping,
                    total,
                    qty,
                    name,
                    phone,
                    address,
                    email,
                    payment_method,
                    status,
                    username,
                    order_no,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    product_name,
                    price,
                    subtotal,
                    shipping,
                    final_total,
                    qty,
                    name,
                    phone,
                    address,
                    email,
                    "cash",
                    "pending",
                    username,
                    order_no,
                    now,
                ),
            )

            # 🔥 真正訂單ID
            order_id = c.lastrowid

            # =========================
            # 寫入交易紀錄
            # =========================
            c.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    type,
                    status,
                    amount,
                    balance_before,
                    balance_after,
                    source_type,
                    source_id,
                    note,
                    transaction_no,
                    order_no,
                    action_type,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    "cash_order",
                    "pending",
                    final_total,
                    0,
                    0,
                    "shop_order",
                    order_id,
                    f"現金訂單：{product_name}",
                    f"TXN{order_id}",
                    order_no,
                    "cash_payment",
                    "{}",
                    now,
                ),
            )

            conn.commit()

            return redirect(f"/ecpay_checkout/{order_no}")

        if payment == "cash":
            return redirect(f"/ecpay_checkout/{order_no}")

        if "user_id" in session:
            return redirect("/orders")

        return redirect("/")

    except Exception as e:
        conn.rollback()

        print("🔥 建立訂單失敗:", e)

        import traceback

        traceback.print_exc()

        return str(e)

    finally:

        conn.close()


@shop_bp.route("/orders")
def orders():

    if not is_admin():
        return "❌ 無權限"

    status = request.args.get("status")

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    sql = """
        SELECT
            id,
            product_name,
            qty,
            total,
            name,
            phone,
            address,
            payment_method,
            status,
            created_at
        FROM orders
    """

    if status:
        sql += " WHERE status=? "

    sql += """
        ORDER BY
        CASE
            WHEN status='paid' THEN 0
            WHEN status='shipped' THEN 1
            ELSE 2
        END,
        created_at DESC
    """

    if status:
        c.execute(sql, (status,))
    else:
        c.execute(sql)

    rows = c.fetchall()

    conn.close()

    return render_template(
        "orders.html",
        orders=rows,
        current_status=status
    )

@shop_bp.route("/product/<int:pid>")
def product(pid):
    conn = get_shop_db()
    c = conn.cursor()

    c.execute("SELECT * FROM products WHERE id=?", (pid,))
    product = c.fetchone()
    conn.close()

    if not product:
        return "商品不存在"

    if "status" in product.keys() and product["status"] == 0:
        return "商品已下架"

    return render_template("product.html", product=product)

@shop_bp.route("/cart")
def cart():

    cart = session.get("cart", {})

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    products = []
    total = 0

    for pid, qty in cart.items():

        c.execute(
            "SELECT * FROM products WHERE id=?",
            (pid,)
        )

        product = c.fetchone()

        if product:

            subtotal = product["price"] * qty

            products.append({
                "product": product,
                "qty": qty,
                "subtotal": subtotal
            })

            total += subtotal

    conn.close()

    return render_template(
        "cart.html",
        products=products,
        total=total
    )

@shop_bp.route("/checkout", methods=["GET", "POST"])
def checkout_cart():

    if request.method == "POST":

        cart = session.get("cart", {})

        if not cart:
            flash("購物車是空的")
            return redirect("/cart")

        name = request.form.get("name")
        phone = request.form.get("phone")
        email = request.form.get("email")
        address = request.form.get("address")

        payment_type = request.form.get("payment_type")

        print("=" * 50)
        print("payment_type =", payment_type)
        print("=" * 50)

        print("進入信用卡流程")

        print("payment_type =", payment_type)

        if payment_type == "cod" and not session.get("user_id"):
            flash("貨到付款限會員使用，請先註冊會員")
            return redirect("/register")

        conn = get_shop_db()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        now = (
            datetime.utcnow()
            + timedelta(hours=8)
        ).strftime("%Y-%m-%d %H:%M:%S")

        order_no = "CART" + str(uuid.uuid4())[:8]

        cart_total = 0

        items_total = 0

        for pid, qty in cart.items():

            product = conn.execute(
                "SELECT * FROM products WHERE id=?",
                (pid,)
            ).fetchone()

            if not product:
                continue

            print("商品=", product["name"])
            print("qty=", qty)
            print("stock=", product["stock"])

            # 已停售
            if product["stock"] <= -10:
                flash(f"{product['name']} 暫停販售")
                return redirect("/cart")

            # 單次購買上限
            if qty > 25:
                print("超過25件")
                flash(f"{product['name']} 單次最多購買 25 件")
                return redirect("/cart")

            # 下單後庫存不能低於 -10
            future_stock = product["stock"] - qty

            if future_stock < -10:
                flash(
                    f"{product['name']} 已超過預售上限，目前剩 {product['stock']} 件"
                )
                return redirect("/cart")

            subtotal = product["price"] * qty

            items_total += subtotal

            c.execute("""
                INSERT INTO orders (
                    product_id,
                    product_name,
                    qty,
                    price,
                    subtotal,
                    total,
                    name,
                    phone,
                    address,
                    email,
                    payment_method,
                    status,
                    order_no,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                product["id"],
                product["name"],
                qty,
                product["price"],
                subtotal,
                subtotal,
                name,
                phone,
                address,
                email,
                payment_type,
                "pending",
                order_no,
                now
            ))

        # =========================
        # 購物車交易紀錄
        # =========================

        if payment_type == "points":

            shipping = 0 if items_total >= POINT_FREE_SHIPPING else SHIPPING_FEE

            original_total = items_total + shipping
            cart_total = original_total

            if items_total >= POINT_DISCOUNT:
                cart_total = int(cart_total * POINT_DISCOUNT_RATE)

        else:

            shipping = 0 if items_total >= CASH_FREE_SHIPPING else SHIPPING_FEE

            original_total = items_total + shipping
            cart_total = original_total

            if items_total >= CASH_DISCOUNT:
                cart_total = int(cart_total * POINT_DISCOUNT_RATE)

        discount_amount = original_total - cart_total

        # =========================
        # 修正 orders 金額
        # =========================

        c.execute(
            """
            UPDATE orders
            SET total=?,
                shipping=?
            WHERE order_no=?
            """,
            (
                cart_total,
                shipping,
                order_no
            )
        )

        c.execute(
            """
            INSERT INTO transactions (
                user_id,
                type,
                status,
                amount,
                balance_before,
                balance_after,
                source_type,
                source_id,
                note,
                transaction_no,
                order_no,
                action_type,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.get("user_id", 0),
                "cash_order",
                "pending",
                cart_total,
                0,
                0,
                "shop_order",
                0,
                "現金訂單：購物車",
                f"TXN{order_no}",
                order_no,
                f"{payment_type}_payment",
                "{}",
                now,
            ),
        )

        # =========================
        # 準提金付款
        # =========================

        if payment_type == "points":

            c.execute(
                """
                UPDATE users
                SET points = points - ?
                WHERE id=? AND points >= ?
                """,
                (
                    cart_total,
                    session["user_id"],
                    cart_total
                )
            )

            if c.rowcount == 0:
                flash("準提金不足")
                return redirect("/checkout")

            c.execute(
                "SELECT points FROM users WHERE id=?",
                (session["user_id"],)
            )

            new_balance = c.fetchone()["points"]

            c.execute(
                """
                UPDATE orders
                SET status='paid',
                    total=?
                WHERE order_no=?
                """,
                (
                    cart_total,
                    order_no
                )
            )

            c.execute(
                """
                SELECT product_id, qty
                FROM orders
                WHERE order_no = ?
                """,
                (order_no,)
            )

            items = c.fetchall()

            print("items =", items)
            print("筆數 =", len(items))

            for item in items:

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

            c.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    type,
                    status,
                    amount,
                    balance_before,
                    balance_after,
                    source_type,
                    source_id,
                    note,
                    transaction_no,
                    order_no,
                    action_type,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["user_id"],
                    "spend",
                    "success",
                    cart_total,
                    new_balance + cart_total,
                    new_balance,
                    "shop_order",
                    0,
                    "購物車商品付款",
                    f"TXN{order_no}",
                    order_no,
                    "points_payment",
                    "{}",
                    now
                )
            )             
            
            conn.commit()

            session.pop("cart", None)

            conn.close()

            return render_template(
                "order_success.html",
                order_no=order_no,
                total=cart_total,
                payment="points",
                name=name
            )

            之後再研究背景寄信
                # send_order_email(
                #     to_email=email,
                #     order_no=order_no,
                #     total=cart_total
                # )

                # send_admin_order_email(
                #     order_no=order_no,
                #     name=name,
                #     phone=phone,
                #     total=cart_total,
                #     payment_type=payment_type
                # )


        # =========================
        # 信用卡 / 貨到付款
        # =========================

        conn.commit()
        conn.close()

        session.pop("cart", None)

        return redirect(
            url_for(
                "payment.ecpay_checkout",
                order_no=order_no
            )
        )      


    cart = session.get("cart", {})

    if not cart:
        flash("購物車是空的")
        return redirect("/cart")

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row

    items = []
    total = 0

    for pid, qty in cart.items():

        product = conn.execute(
            "SELECT * FROM products WHERE id=?",
            (pid,)
        ).fetchone()

        if product:

            subtotal = product["price"] * qty
            total += subtotal

            items.append({
                "product": product,
                "qty": qty,
                "subtotal": subtotal
            })

    conn.close()

    cash_shipping = 0 if total >= CASH_FREE_SHIPPING else SHIPPING_FEE

    cash_total = total + cash_shipping

    if total >= CASH_DISCOUNT:
        cash_total = int(cash_total * POINT_DISCOUNT_RATE)

    point_shipping = 0 if total >= POINT_FREE_SHIPPING else SHIPPING_FEE

    point_total = total + point_shipping

    if total >= POINT_DISCOUNT:
        point_total = int(point_total * POINT_DISCOUNT_RATE)

    return render_template(
        "checkout_cart.html",
        items=items,
        total=total,
        cash_shipping=cash_shipping,
        cash_total=cash_total,
        point_shipping=point_shipping,
        point_total=point_total,
    )


def get_product_images():
    import os

    folder = os.path.join("static", "products")

    if not os.path.exists(folder):
        return []

    return [
        f"/static/products/{f}"
        for f in os.listdir(folder)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]


@shop_bp.route("/edit_product/<int:id>", methods=["GET", "POST"])
def edit_product(id):

    if not is_admin():
        return "❌ 無權限"

    conn = get_shop_db()
    c = conn.cursor()

    if request.method == "POST":
        name = request.form["name"]

        try:
            stock = int(request.form["stock"])
            price = int(request.form["price"])
        except:
            conn.close()
            return "數值錯誤"

        if stock < 0:
            conn.close()
            return "庫存不可小於0"

        if price <= 0:
            conn.close()
            return "價格必須大於0"

        if stock < 0:
            conn.close()
            return "庫存不可小於0"

        desc = request.form["description"]  # 🔥 改這裡（對應DB）
        image1 = request.form["image1"]
        image2 = request.form["image2"]

        c.execute(
            """
            UPDATE products
            SET name=?, price=?, stock=?, image1=?, image2=?, desc=?
            WHERE id=?
        """,
            (name, price, stock, image1, image2, desc, id),
        )
        conn.commit()
        conn.close()

        return redirect("/admin/products")

    product = c.execute("SELECT * FROM products WHERE id=?", (id,)).fetchone()
    conn.close()

    images = get_product_images()
    return render_template("edit_product.html", product=product, images=images)


@shop_bp.route("/delete_product/<int:id>", methods=["POST"])
def delete_product(id):

    if not is_admin():
        return "❌ 無權限"

    conn = get_shop_db()
    c = conn.cursor()

    c.execute("DELETE FROM products WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect("/admin/products")


@shop_bp.route("/toggle_product/<int:id>/<int:status>", methods=["POST"])
def toggle_product(id, status):

    if not is_admin():
        return "❌ 無權限"

    if status not in [0, 1]:
        return "錯誤操作"

    conn = get_shop_db()
    c = conn.cursor()

    # 👉 檢查商品是否存在
    c.execute("SELECT id FROM products WHERE id=?", (id,))
    product = c.fetchone()

    if not product:
        conn.close()
        return "商品不存在"

    c.execute("UPDATE products SET status=? WHERE id=?", (status, id))

    conn.commit()
    conn.close()

    return redirect("/admin/products")


@shop_bp.route("/update_order/<int:order_id>/<status>", methods=["POST"])
def update_order(order_id, status):

    if not is_admin():
        return "❌ 無權限"

    # 暫時關閉登入驗證（先跑流程）
    # if "user" not in session:
    #     return redirect("/login")

    conn = get_shop_db()
    c = conn.cursor()

    # 🔥 一段式檢查 + 更新
    c.execute("SELECT status FROM orders WHERE id=?", (order_id,))
    row = c.fetchone()

    if not row:
        return "❌ 訂單不存在"

    current = row["status"]

    # 👉 狀態規則（核心）
    valid_flow = {
        "pending": ["paid"],
        "paid": ["shipped"],
        "shipped": [],
        "expired": [],
    }

    # 🔥 不合法直接擋掉
    if status not in ["paid", "shipped"] or status not in valid_flow.get(current, []):
        return "❌ 狀態錯誤"

    # ✅ 通過才更新
    c.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))

    conn.commit()
    conn.close()

    return redirect("/orders")

@shop_bp.route("/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):

    cart = session.get("cart", {})

    pid = str(product_id)

    qty = int(request.form.get("qty", 1))

    if pid in cart:
        cart[pid] += qty
    else:
        cart[pid] = qty

    session["cart"] = cart

    flash("商品已加入購物車")

    return redirect("/cart")

@shop_bp.route("/cart_plus/<int:pid>")
def cart_plus(pid):

    cart = session.get("cart", {})

    pid_str = str(pid)

    conn = get_shop_db()
    conn.row_factory = sqlite3.Row

    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (pid,)
    ).fetchone()

    if not product:
        return redirect("/cart")

    current_qty = cart.get(pid_str, 0)

    # 單品上限25件
    if current_qty >= 25:
        flash(f"{product['name']} 單次最多購買 25 件")
        return redirect("/cart")

    # 庫存保護
    if current_qty >= product["stock"]:
        flash(
            f"{product['name']} 庫存不足，目前剩 {product['stock']} 件"
        )
        return redirect("/cart")

    if pid_str in cart:
        cart[pid_str] += 1

    session["cart"] = cart

    return redirect("/cart")


@shop_bp.route("/cart_minus/<int:pid>")
def cart_minus(pid):

    cart = session.get("cart", {})

    pid = str(pid)

    if pid in cart:

        cart[pid] -= 1

        if cart[pid] <= 0:
            del cart[pid]

    session["cart"] = cart

    return redirect("/cart")

@shop_bp.route("/cart_remove/<int:pid>")
def cart_remove(pid):

    cart = session.get("cart", {})

    pid = str(pid)

    if pid in cart:
        del cart[pid]

    session["cart"] = cart

    return redirect("/cart")

@shop_bp.route("/send_order_emails/<order_no>")
def send_order_emails(order_no):

    print("開始寄信:", order_no)

    conn = get_shop_db()

    order = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE order_no=?
        """,
        (order_no,)
    ).fetchone()

    if not order:
        return "NOT FOUND"
    
    print("AAAA")

    try:
        send_admin_order_email(
            order_no=order["order_no"],
            name=order["name"],
            phone=order["phone"],
            total=order["total"],
            payment_type=order["payment_method"]
        )

        print("BBBB")
    except Exception as e:
        print("CCCC")
        print("管理員信失敗:", e)


        print("DDDD")

    try:
        send_order_email(
            to_email=order["email"],
            order_no=order["order_no"],
            total=order["total"]
        )

        print("EEEE")
    except Exception as e:

        print("FFFF")
        print("客戶信失敗:", e)

    conn.close()

    print("GGGG")

    return "OK"
