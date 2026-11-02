"""Tests des alertes WhatsApp (faux Twilio). Lancer : python3 test_notifier.py"""
import io
import logging
import threading
import time
from datetime import datetime, timezone, timedelta

import moteur as m
import notifier as n

OK = True


def check(label, got, want):
    global OK
    good = got == want
    OK &= good
    print(("OK  " if good else "FAIL"), label, "->", got if not good else "")


NOW = datetime(2026, 10, 19, 6, 0, 0, tzinfo=timezone.utc)
SID, TOKEN = "AC0123456789abcdef", "tok_SECRET_9876"
CFG = m.Config(twilio_account_sid=SID, twilio_auth_token=TOKEN,
               twilio_from="whatsapp:+14155238886", notify_to="+261340000000", notify_max_per_hour=3)


class Recorder:
    """Faux Twilio + collecte des résultats."""
    def __init__(self, reply=(201, {"sid": "SM777", "status": "queued"}), error=None, delay=0.0):
        self.calls, self.results, self.reply, self.error, self.delay = [], [], reply, error, delay

    def post(self, url, data, auth, timeout):
        time.sleep(self.delay)
        self.calls.append({"url": url, "data": data, "auth": auth, "timeout": timeout})
        if self.error: raise self.error
        return self.reply

    def on_result(self, *args): self.results.append(args)


def make(cfg=CFG, rec=None, clock=None, sync=True):
    rec = rec or Recorder()
    return n.WhatsAppNotifier(cfg, on_result=rec.on_result, http_post=rec.post, clock=clock or (lambda: NOW), sync=sync), rec


# --- sans identifiants : le message est enregistré, rien n'est envoyé ---
nt, rec = make(cfg=m.Config())
check("non configuré : statut disabled", nt.submit("msg", "g1", "cause:x", ["a"]), "disabled")
check("non configuré : aucun appel réseau, message conservé", (rec.calls, rec.results), ([], [("g1", "cause:x", "disabled", "msg", ["a"], None, None)]))
check("configuration partielle = non configurée", n.WhatsAppNotifier(m.Config(twilio_account_sid=SID, twilio_auth_token=TOKEN)).configured, False)

# --- envoi réussi ---
nt, rec = make()
check("configuré : demande acceptée", nt.submit("Cause : postgres", "g1", "cause:postgres", ["student", "enrollment"]), "queued")
call = rec.calls[0]
check("URL du compte Twilio", call["url"], f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json")
check("authentification par compte et jeton (jamais dans l'URL ni le corps)", (call["auth"], TOKEN in str(call["url"]), TOKEN in str(call["data"])), ((SID, TOKEN), False, False))
check("expéditeur, destinataire (préfixe whatsapp: ajouté), texte", call["data"],
      {"From": "whatsapp:+14155238886", "To": "whatsapp:+261340000000", "Body": "Cause : postgres"})
check("délai d'attente de 5 s", call["timeout"], 5)
check("résultat : envoyé, identifiant Twilio conservé", rec.results[0], ("g1", "cause:postgres", "sent", "Cause : postgres", ["student", "enrollment"], None, "SM777"))
nt, rec = make(); nt.submit("x" * 5000, "g", "k", [])
check("texte borné à 1500 caractères", len(rec.calls[0]["data"]["Body"]), 1500)

# --- échecs : journalisés, enregistrés, jamais d'exception, secrets expurgés ---
nt, rec = make(rec=Recorder(reply=(400, {"code": 63016, "message": "Outside the 24h window", "status": 400})))
nt.submit("m", "g1", "k", [])
check("refus de Twilio : statut failed avec le motif", (rec.results[0][2], "63016" in rec.results[0][5], "24h" in rec.results[0][5]), ("failed", True, True))
nt, rec = make(rec=Recorder(error=ConnectionError(f"Max retries url: /Accounts/{SID}/Messages.json auth {TOKEN}")))
nt.submit("m", "g1", "k", [])
check("réseau coupé : statut failed", rec.results[0][2], "failed")
check("identifiant et jeton expurgés de l'erreur enregistrée", (SID in rec.results[0][5], TOKEN in rec.results[0][5], "***" in rec.results[0][5]), (False, False, True))
nt, rec = make(rec=Recorder(reply=(500, {})))
nt.submit("m", "g1", "k", [])
check("réponse sans détail", "HTTP 500" in rec.results[0][5], True)

logbuf = io.StringIO(); h = logging.StreamHandler(logbuf); n.logger.addHandler(h); n.logger.setLevel(logging.INFO)
nt, rec = make(rec=Recorder(error=ConnectionError(f"echec {TOKEN} {SID}"))); nt.submit("Texte secret du message", "g1", "k", [])
nt, rec = make(); nt.submit("Texte secret du message", "g2", "k", [])
n.logger.removeHandler(h)
logs = logbuf.getvalue()
check("jamais le jeton, l'identifiant, le numéro ni le texte dans les logs", any(s in logs for s in (TOKEN, SID, "261340000000", "Texte secret")), False)
import json as _json
decoded = " ".join(_json.loads(l) for l in logs.splitlines() if l.strip())   # les accents sont échappés dans le JSON
check("les deux issues sont journalisées", ("en échec" in decoded, "envoyée" in decoded), (True, True))

# --- garde-fou : 3 par heure ---
clock = {"now": NOW}
nt, rec = make(clock=lambda: clock["now"])
statuses = [nt.submit("m", f"g{i}", "k", []) for i in range(5)]
check("au plus 3 envois par heure", (statuses, len(rec.calls)), (["queued"] * 3 + ["throttled"] * 2, 3))
check("les envois bloqués sont enregistrés (throttled)", [r[2] for r in rec.results], ["sent"] * 3 + ["throttled"] * 2)
clock["now"] = NOW + timedelta(minutes=61)
check("une heure plus tard : de nouveau possible", nt.submit("m", "g9", "k", []), "queued")

# --- non bloquant : l'envoi se fait dans un fil à part ---
nt, rec = make(rec=Recorder(delay=0.3), sync=False)
start = time.time()
status = nt.submit("m", "g1", "k", [])
check("submit rend la main tout de suite", (status, time.time() - start < 0.1, rec.results), ("queued", True, []))
nt.wait(2)
check("l'envoi aboutit en arrière-plan", [r[2] for r in rec.results], ["sent"])

# --- l'enregistrement ne fait pas échouer l'alerte ---
def boom(*args): raise RuntimeError("base en panne")
nt = n.WhatsAppNotifier(CFG, on_result=boom, http_post=lambda *a: (201, {"sid": "SM1"}), sync=True, clock=lambda: NOW)
try:
    nt.submit("m", "g1", "k", []); raised = False
except Exception:
    raised = True
check("on_result en erreur : aucune exception", raised, False)

print("\nTOUS LES TESTS PASSENT" if OK else "\nDES TESTS ÉCHOUENT")
