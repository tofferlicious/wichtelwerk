"""English translations for application-owned backend messages only."""
EN = {
    'Zu viele Versuche. Bitte später erneut probieren.':'Too many attempts. Please try again later.',
    'Sicherheitsprüfung fehlgeschlagen. Seite neu laden.':'Security check failed. Please reload the page.',
    'Ungültige Herkunft.':'Invalid request origin.',
    'Bitte zuerst per E-Mail anmelden.':'Please sign in by email first.',
    'Nur freigegebene Konten dürfen Runden erstellen oder kopieren. Du kannst an eingeladenen Runden teilnehmen.':'Only approved accounts may create or copy rounds. You can still join rounds you are invited to.',
    'Ungültige Anfrage.':'Invalid request.',
    'Ungültiges Feld: ':'Invalid field: ',
    'Bitte ausfüllen: ':'Please complete: ',
    'Ungültige E-Mail-Adresse.':'Invalid email address.',
    'E-Mail konnte nicht übergeben werden. Bitte später erneut versuchen.':'The email could not be submitted. Please try again later.',
    'Der Anmeldelink wurde an den Mailserver übergeben. Bitte auch den Spamordner prüfen.':'The sign-in link was submitted to the mail server. Please also check your spam folder.',
    'Dieser Link ist abgelaufen oder wurde bereits benutzt. Fordere einen neuen Anmeldelink an.':'This link has expired or has already been used. Please request a new sign-in link.',
    'Runde nicht gefunden.':'Round not found.',
    'Nach der Auslosung bleibt die Teilnehmerliste unverändert.':'The participant list cannot be changed after the draw.',
    'Ungültiges Datum.':'Invalid date.',
    'Bitte ein Datum in den nächsten zehn Jahren wählen.':'Please choose a date within the next ten years.',
    'Ungültige Aufbewahrung.':'Invalid retention period.',
    'Maximal 30 Runden pro Konto.':'A maximum of 30 rounds is allowed per account.',
    'Maximal 100 Personen pro Runde.':'A maximum of 100 people is allowed per round.',
    'Diese Person ist bereits eingeladen.':'This person has already been invited.',
    'Du nimmst noch nicht teil.':'You are not participating yet.',
    'Ungültige Antwort.':'Invalid response.',
    'Ungültige Ausschlüsse.':'Invalid exclusions.',
    'Ausschlüsse müssen zwei verschiedene Personen dieser Runde betreffen.':'Exclusions must refer to two different people in this round.',
    'Bitte bestätigen: Es werden nur Zusagen ausgelost. Die Auslosung ist endgültig.':'Please confirm: only accepted participants take part. The draw is final.',
    'Keine gültige Auslosung möglich. Zusagen und Ausschlüsse prüfen.':'No valid draw is possible. Please check responses and exclusions.',
    'Ausgelost. Benachrichtigungen werden automatisch im Hintergrund versendet; die Zuordnungen stehen ausschließlich im persönlichen Konto.':'Draw complete. Notifications will be sent automatically in the background; assignments are available only in each personal account.',
    'Die Runde ist voll.':'This round is full.',
    'Anmeldelink nicht gefunden.':'Invitation link not found.',
    'Ungültige Person.':'Invalid participant.',
    'Bitte eine Person wählen.':'Please select a participant.',
    'Person nicht gefunden.':'Participant not found.',
    'Ungültige Teilnehmerauswahl.':'Invalid participant selection.',
    'Kopie erstellt. Keine Wünsche, Adressen oder Zusagen übernommen. Einladungen über „Erinnerung senden“ verschicken.':'Copy created. Wishes, addresses and responses were not copied. Use “Send reminder” to send invitations.',
    'Bitte LÖSCHEN bestätigen.':'Please type DELETE to confirm.',
    'Ungültige Sprache.':'Invalid language.',
    'Dein Zugang zu Wichtelwerk':'Your Wichtelwerk sign-in link',
    'Willkommen zurück – oder schön, dass du dabei bist! Dieser Link gilt 30 Minuten.':'Welcome back — or welcome to Wichtelwerk! This link is valid for 30 minutes.',
    'Einladung: ':'Invitation: ',
    'Erinnerung: ':'Reminder: ',
    'Ausgelost: ':'Draw complete: ',
    'Du bist zu „{title}“ eingeladen. Bitte im Konto zu- oder absagen. Zugang gilt 7 Tage.':'You are invited to “{title}”. Please accept or decline in your account. Your sign-in link is valid for 7 days.',
    'Die Auslosung ist fertig. Dein Wichtelkind findest du ausschließlich in deinem Konto.':'The draw is complete. You can see your recipient only in your account.',
    'Bitte antworte auf die Einladung und ergänze deine Wünsche.':'Please respond to the invitation and add your wishes.',
    'Zugang gilt 7 Tage.':'Your sign-in link is valid for 7 days.',
    'Die Auslosung ist fertig. Dein Wichtelkind findest du ausschließlich in deinem Konto. Zugang gilt 7 Tage.':'The draw is complete. You can see your recipient only in your account. Your sign-in link is valid for 7 days.',
    'Dein persönlicher, einmaliger Zugang:':'Your personal, single-use sign-in link:',
    'Bitte nicht weitergeben. Wichtelwerk fragt nie nach deinem E-Mail-Passwort.':'Please do not share this link. Wichtelwerk will never ask for your email password.',
}


def translate(message, language):
    if language != 'en':
        return message
    if message in EN:
        return EN[message]
    for prefix in ('Ungültiges Feld: ', 'Bitte ausfüllen: '):
        if message.startswith(prefix):
            return EN[prefix]+message[len(prefix):]
    return message
