"""SMTP delivery over real local TCP, STARTTLS and implicit TLS."""
import base64
from email import message_from_bytes
import socket
import socketserver
import sqlite3
import ssl
import subprocess
import threading
import pytest
from test_creation_permissions import app_for
from test_localization import localized_post


class SMTPHandler(socketserver.StreamRequestHandler):
    def setup(self):
        if self.server.security == 'ssl':
            self.request = self.server.context.wrap_socket(self.request, server_side=True)
        super().setup()

    def reply(self, text):
        self.wfile.write(text.encode()+b'\r\n')
        self.wfile.flush()

    def handle(self):
        self.reply('220 localhost test SMTP')
        while line := self.rfile.readline():
            command = line.decode().strip()
            verb = command.split(' ', 1)[0].upper()
            if verb in ('EHLO', 'HELO'):
                self.reply('250-localhost\r\n250-STARTTLS\r\n250 AUTH PLAIN')
            elif verb == 'STARTTLS':
                self.reply('220 Ready for TLS')
                self.connection = self.server.context.wrap_socket(self.connection, server_side=True)
                self.rfile = self.connection.makefile('rb')
                self.wfile = self.connection.makefile('wb')
                self.server.encrypted = True
            elif verb == 'AUTH':
                self.server.auth = base64.b64decode(command.split()[-1])
                self.reply('235 Authenticated')
            elif verb == 'DATA':
                self.reply('354 End with dot')
                body = []
                while (part := self.rfile.readline()) != b'.\r\n':
                    if not part:
                        return
                    body.append(part[1:] if part.startswith(b'..') else part)
                self.server.messages.append(b''.join(body))
                self.reply('250 Queued')
            elif verb == 'QUIT':
                self.reply('221 Bye')
                return
            else:
                self.reply('250 OK')


@pytest.mark.parametrize('security', ['none','starttls','ssl'])
def test_real_smtp_login_email(tmp_path, monkeypatch, security):
    cert,key=tmp_path/'cert.pem',tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
                    '-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert,key)
    trusted=ssl.create_default_context(cafile=str(cert))
    monkeypatch.setattr(ssl,'create_default_context',lambda:trusted)
    with socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTPHandler) as server:
        server.daemon_threads=True
        server.security,server.context=security,context
        server.messages,server.auth,server.encrypted=[],None,security=='ssl'
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            app=app_for(tmp_path,MAIL_MODE='smtp',SMTP_HOST='localhost',SMTP_PORT=server.server_address[1],
                        SMTP_SECURITY=security,SMTP_USERNAME='demo',SMTP_PASSWORD='synthetic-test-value',
                        MAIL_FROM='sender@example.invalid')
            response=localized_post(app.test_client(),'/api/login',{'email':'guest@example.invalid'})
            assert response.status_code==200,response.json
            assert len(server.messages)==1
            message=message_from_bytes(server.messages[0])
            assert message['To']=='guest@example.invalid'
            assert message['From']=='sender@example.invalid'
            assert message['Subject']=='Your Wichtelwerk sign-in link'
            assert 'personal, single-use sign-in link' in message.get_payload(decode=True).decode()
            assert server.auth==b'\0demo\0synthetic-test-value'
            assert server.encrypted==(security!='none')
            assert app.extensions['outbox']==[]
        finally:
            server.shutdown();thread.join(timeout=5)


def test_unreachable_smtp_invalidates_new_token(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    app=app_for(tmp_path,MAIL_MODE='smtp',SMTP_HOST='127.0.0.1',SMTP_PORT=port,SMTP_SECURITY='none')
    response=localized_post(app.test_client(),'/api/login',{'email':'guest@example.invalid'})
    assert response.status_code==503
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM tokens').fetchone()[0]==0


@pytest.mark.parametrize('bad', [
    {'SMTP_HOST':''},{'SMTP_PORT':'not-a-port'},{'SMTP_PORT':0},{'SMTP_PORT':65536},
    {'SMTP_SECURITY':'insecure-maybe'},{'SMTP_USERNAME':'demo','SMTP_PASSWORD':''},
    {'SMTP_USERNAME':'','SMTP_PASSWORD':'synthetic-test-value'},
])
def test_smtp_invalid_config_fails_at_startup(tmp_path,bad):
    config={'MAIL_MODE':'smtp','SMTP_HOST':'localhost',**bad}
    with pytest.raises(ValueError,match='SMTP_'):
        app_for(tmp_path,**config)
