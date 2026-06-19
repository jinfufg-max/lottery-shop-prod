from flask import Blueprint, render_template, request, session, send_file

from datetime import datetime

from services.db import get_lottery_db

from services.db import get_shop_db

from routes.bag import settle_lottery

from ai.engine import refresh_ai_cache

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin/update_result", methods=["GET", "POST"])
def update_result():

    if session.get("user") != "admin":
        return "❌ 無權限"

    if request.method == "POST":
        date = request.form.get("date")
        raw = request.form.get("numbers", "")
        special = request.form.get("special")

        # 日期驗證
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")

        except:
            return "❌ 日期格式錯誤"

        # 只能二 / 五
        if dt.weekday() not in [1, 4]:
            return "❌ 只能登錄星期二 / 星期五開獎資料"

        # 禁止未來日期
        today_str = datetime.now().strftime("%Y-%m-%d")

        if date > today_str:
            return "❌ 不可提前登錄未來開獎"

        try:
            nums = [int(x) for x in raw.split(",")]
            special = int(special)
        except:
            return "❌ 格式錯誤"

        if len(nums) != 6:
            return "❌ 必須6個號碼"

        if len(set(nums)) != 6:
            return "❌ 重複號碼"

        if special in nums:
            return "❌ 特別號重複"

        # 號碼範圍驗證
        if not all(1 <= n <= 49 for n in nums):
            return "❌ 號碼超出範圍"

        if not 1 <= special <= 49:
            return "❌ 特別號超出範圍"

        full = ",".join(map(str, nums)) + "," + str(special)

        conn = get_lottery_db()
        c = conn.cursor()

        c.execute("SELECT numbers FROM lottery_results WHERE draw_date=?", (date,))

        row = c.fetchone()

        if row:
            conn.close()
            return "❌ 此期已存在開獎資料"

        else:
            c.execute(
                "INSERT INTO lottery_results (draw_date, numbers) VALUES (?, ?)",
                (date, full),
            )

            msg = "✅ 新增成功"

        conn.commit()
        # =========================
        # 🔥 開獎後同步全站
        # =========================

        # 只取前6碼（不要特別號）
        draw_numbers = nums[:6]

        # 福袋結算
        settle_lottery(date, draw_numbers)

        # AI立即刷新
        refresh_ai_cache()

        print("✅ 開獎同步完成")

        # 清除舊福袋
        cleanup_old_bags()

        conn.close()

        return f"""
        <script>
        alert("{msg}");
        window.location.href="/admin/update_result";
        </script>
        """

    # ✅ 關鍵：這行一定要有
    return render_template("update_result.html")


def cleanup_old_bags():

    # ===== 從 lottery DB 取得最新兩期 =====
    lottery_conn = get_lottery_db()
    lottery_c = lottery_conn.cursor()

    lottery_c.execute("""
        SELECT draw_date
        FROM lottery_results
        ORDER BY draw_date DESC
        LIMIT 2
    """)

    rows = lottery_c.fetchall()

    lottery_conn.close()

    keep_dates = [r[0] for r in rows]

    if len(keep_dates) < 2:
        return

    # ===== 刪除舊福袋 =====
    shop_conn = get_shop_db()
    shop_c = shop_conn.cursor()

    shop_c.execute(
        """
        DELETE FROM user_bags
        WHERE status != 'pending'
        AND (
            target_draw_date IS NULL
            OR target_draw_date NOT IN (?, ?)
        )
        """,
        (
            keep_dates[0],
            keep_dates[1],
        ),
    )

    deleted = shop_c.rowcount

    shop_conn.commit()
    shop_conn.close()

    print(f"✅ 已清除 {deleted} 筆舊福袋")

import os

@admin_bp.route("/admin/download/shopdb")
def download_shopdb():

    if session.get("user") != "admin":
        return "❌ 無權限"

    print("======== DOWNLOAD DB ========")
    print(os.path.abspath("data/shop.db"))
    print("============================")

    return send_file(
        "data/shop.db",
        as_attachment=True,
        download_name="shop.db"
    )


@admin_bp.route("/admin/upload/shopdb", methods=["POST"])
def upload_shopdb():

    if session.get("user") != "admin":
        return "❌ 無權限"

    file = request.files.get("dbfile")

    if not file:
        return "❌ 未選擇檔案"

    file.save("data/shop.db")

    return "✅ shop.db 上傳成功"


@admin_bp.route("/admin/download/lotterydb")
def download_lotterydb():

    if session.get("user") != "admin":
        return "❌ 無權限"

    return send_file(
        "data/lottery_v2.db",
        as_attachment=True,
        download_name="lottery_v2.db"
    )


@admin_bp.route("/admin/upload/lotterydb", methods=["POST"])
def upload_lotterydb():

    if session.get("user") != "admin":
        return "❌ 無權限"

    file = request.files.get("dbfile")

    if not file:
        return "❌ 未選擇檔案"

    file.save("data/lottery_v2.db")

    return "✅ lottery_v2.db 上傳成功"


@admin_bp.route("/admin")
def admin_home():

    if session.get("user") != "admin":
        return "❌ 無權限"

    conn = get_shop_db()
    c = conn.cursor()

    # 會員數
    c.execute("SELECT COUNT(*) FROM users")
    user_count = c.fetchone()[0]

    # 商品數
    c.execute("SELECT COUNT(*) FROM products")
    product_count = c.fetchone()[0]

    # 訂單數
    c.execute("SELECT COUNT(*) FROM orders")
    order_count = c.fetchone()[0]

    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")

    # 今日營收
    c.execute("""
        SELECT COALESCE(SUM(total),0)
        FROM orders
        WHERE status='paid'
        AND created_at LIKE ?
    """, (f"{today}%",))

    today_revenue = c.fetchone()[0]

    # 本月營收
    c.execute("""
        SELECT COALESCE(SUM(total),0)
        FROM orders
        WHERE status='paid'
        AND created_at LIKE ?
    """, (f"{month}%",))

    month_revenue = c.fetchone()[0]

    # 總營收
    c.execute("""
        SELECT COALESCE(SUM(total),0)
        FROM orders
        WHERE status='paid'
    """)

    total_revenue = c.fetchone()[0]

    # 待出貨
    c.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status='paid'
    """)

    pending_ship = c.fetchone()[0]

    conn.close()

    return render_template(
        "admin_home.html",
        user_count=user_count,
        product_count=product_count,
        order_count=order_count,
        pending_ship=pending_ship,
        today_revenue=today_revenue,
        month_revenue=month_revenue,
        total_revenue=total_revenue,
    )