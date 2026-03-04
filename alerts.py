"""
Daily alert checker — low stock and expiry notifications.

Run manually:    python alerts.py
Schedule daily:  Windows Task Scheduler → python alerts.py at 08:00
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date
from dotenv import load_dotenv

load_dotenv()

ALERT_EMAIL_TO       = os.getenv("ALERT_EMAIL_TO")
ALERT_EMAIL_FROM     = os.getenv("ALERT_EMAIL_FROM")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
SMTP_HOST            = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT            = int(os.getenv("SMTP_PORT", 587))

WARN_30_DAYS = 30
WARN_60_DAYS = 60


def check_alerts() -> tuple[list, list, list]:
    from sheets import get_all_items
    today     = date.today()
    low_stock, expiring_30, expiring_60 = [], [], []

    for item in get_all_items():
        # Low stock
        if item["low_stock_threshold"] > 0 and item["quantity"] <= item["low_stock_threshold"]:
            low_stock.append(item)

        # Expiry
        if item["expiration_date"]:
            try:
                days = (date.fromisoformat(item["expiration_date"]) - today).days
                if days <= WARN_30_DAYS:
                    expiring_30.append((item, "EXPIRED" if days < 0 else f"{days}d left"))
                elif days <= WARN_60_DAYS:
                    expiring_60.append((item, f"{days}d left"))
            except ValueError:
                pass

    return low_stock, expiring_30, expiring_60


def _html_report(low_stock, expiring_30, expiring_60) -> str:
    today = date.today().isoformat()

    def tbl(headers, rows, bg):
        ths = "".join(f"<th style='padding:8px 14px;text-align:left'>{h}</th>" for h in headers)
        return f"<table style='width:100%;border-collapse:collapse;margin-bottom:20px;font-size:14px'><tr style='background:{bg}'>{ths}</tr>{rows}</table>"

    def row(item, extra=""):
        extra_td = (f"<td style='padding:7px 14px;color:#c0392b'><b>{extra}</b></td>" if extra
                    else f"<td style='padding:7px 14px'>{item.get('low_stock_threshold','')} {item.get('unit','')}</td>")
        return (f"<tr style='border-bottom:1px solid #eee'>"
                f"<td style='padding:7px 14px'>{item['id']}</td>"
                f"<td style='padding:7px 14px'><b>{item['name']}</b></td>"
                f"<td style='padding:7px 14px'>{item.get('location','—')}</td>"
                f"<td style='padding:7px 14px'>{item['quantity']} {item.get('unit','')}</td>"
                f"{extra_td}</tr>")

    html = (f"<html><body style='font-family:Segoe UI,Arial,sans-serif;color:#333;max-width:800px;margin:0 auto;padding:24px'>"
            f"<div style='background:#0f172a;color:white;padding:20px 24px;border-radius:10px;margin-bottom:24px'>"
            f"<h2 style='margin:0'>🧪 Lab Inventory Alert</h2>"
            f"<p style='margin:4px 0 0;opacity:.6;font-size:13px'>{today}</p></div>")

    if low_stock:
        rows = "".join(row(i) for i in low_stock)
        html += f"<h3 style='color:#d97706'>⚠️ Low Stock — {len(low_stock)} item(s)</h3>"
        html += tbl(["ID","Name","Location","Qty","Threshold"], rows, "#fef3c7")

    if expiring_30:
        rows = "".join(row(i, s) for i, s in expiring_30)
        html += f"<h3 style='color:#dc2626'>🗓️ Expiring ≤30 days — {len(expiring_30)} item(s)</h3>"
        html += tbl(["ID","Name","Location","Qty","Status"], rows, "#fee2e2")

    if expiring_60:
        rows = "".join(row(i, s) for i, s in expiring_60)
        html += f"<h3 style='color:#a16207'>🗓️ Expiring ≤60 days — {len(expiring_60)} item(s)</h3>"
        html += tbl(["ID","Name","Location","Qty","Days Left"], rows, "#fef9c3")

    if not low_stock and not expiring_30 and not expiring_60:
        html += "<div style='background:#dcfce7;border-radius:8px;padding:20px;color:#16a34a'>✅ All inventory levels normal. No alerts today.</div>"

    return html + "</body></html>"


def _send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = ALERT_EMAIL_FROM
    msg["To"]      = ALERT_EMAIL_TO
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(ALERT_EMAIL_FROM, ALERT_EMAIL_PASSWORD)
        s.sendmail(ALERT_EMAIL_FROM, ALERT_EMAIL_TO, msg.as_string())


def run_daily_check():
    low, e30, e60 = check_alerts()
    total   = len(low) + len(e30) + len(e60)
    subject = (f"🚨 Lab Inventory: {total} Alert(s) — {date.today().isoformat()}"
               if total else
               f"✅ Lab Inventory: All Clear — {date.today().isoformat()}")
    html = _html_report(low, e30, e60)

    if ALERT_EMAIL_TO and ALERT_EMAIL_FROM and ALERT_EMAIL_PASSWORD:
        _send_email(subject, html)
        print(f"Alert email sent → {ALERT_EMAIL_TO}")
    else:
        print(f"[Dry run] Low: {len(low)} | Exp 30d: {len(e30)} | Exp 60d: {len(e60)}")


if __name__ == "__main__":
    run_daily_check()
