import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

from config import EMAIL_ACCOUNT, EMAIL_PASSWORD

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def send_order_email(to_email, order_no, total):

    subject = "訂單付款成功"

    body = f"""
您好：

您的訂單已付款成功。

訂單編號：
{order_no}

付款金額：
NT${total}

感謝您的支持。
"""

    msg = MIMEMultipart()

    msg["From"] = EMAIL_ACCOUNT
    msg["To"] = to_email

    # ===== 中文標題 UTF-8 =====
    msg["Subject"] = Header(subject, "utf-8")

    # ===== 中文內容 UTF-8 =====
    msg.attach(MIMEText(body, "plain", "utf-8"))

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)

    server.starttls()

    # print("EMAIL_ACCOUNT =", EMAIL_ACCOUNT)
    # print("EMAIL_PASSWORD =", EMAIL_PASSWORD[:4] + "****")

    server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)

    server.send_message(msg)

    server.quit()


def send_welcome_email(email, username, points):

    subject = "歡迎加入錦蚨豐國際準提商城"

    body = f"""
您好 {username}：

恭喜您已成功完成會員註冊。

會員帳號：
{username}

入會贈送：

🎁 準提金 {points} 點
🎁 大金袋 x2

立即登入體驗：

✓ 錦蚨豐國際準提商城

祝您順心如意。

錦蚨豐國際準提商城
"""

    msg = MIMEMultipart()

    msg["From"] = EMAIL_ACCOUNT
    msg["To"] = email
    msg["Subject"] = Header(subject, "utf-8")

    msg.attach(MIMEText(body, "plain", "utf-8"))

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)

    server.starttls()

    server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)

    server.send_message(msg)

    server.quit()

def send_admin_order_email(
    order_no,
    name,
    phone,
    total,
    payment_type
):

    subject = f"🔔 新訂單通知 {order_no}"

    body = f"""
【商城新訂單通知】

訂單編號：
{order_no}

收件人：
{name}

電話：
{phone}

付款方式：
{payment_type}

訂單金額：
NT${total}

請登入後台查看訂單。
"""

    msg = MIMEMultipart()

    msg["From"] = EMAIL_ACCOUNT
    msg["To"] = "lonertz@gmail.com"
    msg["Subject"] = Header(subject, "utf-8")

    msg.attach(
        MIMEText(body, "plain", "utf-8")
    )

    server = smtplib.SMTP(
        SMTP_SERVER,
        SMTP_PORT
    )

    server.starttls()

    server.login(
        EMAIL_ACCOUNT,
        EMAIL_PASSWORD
    )

    server.send_message(msg)

    server.quit()
