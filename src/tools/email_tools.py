import smtplib
from email.message import EmailMessage
from typing import List, Dict
from src.config import Config as settings

class EmailTool:
    def __init__(self):
        self.host =settings.SMTP_SERVER
        self.port = settings.SMTP_PORT
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD
        self.from_address = settings.SMTP_FROM

    def send_email(self, sender: str, recipient: str, subject: str, body: str, attachments: List[Dict[str, bytes]] = None) -> Dict[str, str]:
        """
        Envoie un email via SMTP, avec pièces jointes optionnelles.
        attachments: [{ 'filename': str, 'content': bytes }]
        """
        msg = EmailMessage()
        msg['From'] = sender
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.set_content(body)
        if attachments:
            for att in attachments:
                msg.add_attachment(att['content'], maintype='application',
                                   subtype='octet-stream', filename=att['filename'])
        with smtplib.SMTP(self.host, self.port) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
        return {'status': 'sent'}
