# app/email_utils.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app

def send_verification_email(recipient_email, code, purpose='register'):
    """
    Отправляет код подтверждения.
    purpose: 'register' или 'reset'
    """
    if purpose == 'register':
        subject = "Код подтверждения регистрации"
        body_intro = "Для завершения регистрации на сайте «Петербургская Атмосфера» введите код:"
        body_footer = "Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо."
    else:  # reset
        subject = "Код для сброса пароля"
        body_intro = "Вы запросили сброс пароля на сайте «Петербургская Атмосфера». Ваш код подтверждения:"
        body_footer = "Если вы не запрашивали смену пароля, просто проигнорируйте это письмо."

    body = f"""
    <html>
      <body>
        <h2>{subject}</h2>
        <p>{body_intro}</p>
        <h1 style="font-size: 32px; letter-spacing: 5px;">{code}</h1>
        <p>Код действителен в течение 10 минут.</p>
        <p>{body_footer}</p>
      </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = current_app.config['MAIL_DEFAULT_SENDER']
    msg['To'] = recipient_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP(
            current_app.config['MAIL_SERVER'],
            current_app.config['MAIL_PORT']
        )
        if current_app.config['MAIL_USE_TLS']:
            server.starttls()
        server.login(
            current_app.config['MAIL_USERNAME'],
            current_app.config['MAIL_PASSWORD']
        )
        server.send_message(msg)
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)