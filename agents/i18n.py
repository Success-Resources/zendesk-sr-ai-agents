"""Holding texts in the customer's language (v11).

Maya's holding replies are fixed sentences. When the customer writes clearly in Dutch, German,
French, Spanish, Italian or Portuguese, those fixed sentences are sent in that language. Anything
else, or any doubt, stays English. Only a reply made entirely of known fixed sentences is
translated, so a drafted answer never ends up half in one language and half in another.
The greeting ("Hi <first name>," / "Hi there,") and the brand footer are left as they are.
"""
from __future__ import annotations

import re

SUPPORTED = ("nl", "de", "fr", "es", "it", "pt")

# Function words that are common in one language and rare in the others (and in English).
_WORDS: dict[str, set[str]] = {
    "en": set("the and you your is are have has for with this that from would please thank thanks can not my we our will".split()),
    "nl": set("de het een en ik je jij u uw mijn niet wij we zijn hebben voor met dit dat van graag bedankt alvast kunt kan wil ook maar nog".split()),
    "de": set("der die das und ich sie ihr ihre mein meine nicht wir sind haben für mit diese dieser ist bitte danke können kann möchte auch aber noch einen eine".split()),
    "fr": set("le la les et je vous votre mon ma mes ne pas nous sont avons pour avec ce cette est merci pouvez peux voudrais aussi mais une des du".split()),
    "es": set("el la los las y yo usted su mi mis no nosotros somos tenemos para con este esta es gracias puede puedo quisiera también pero una del por".split()),
    "it": set("il lo la gli le e io lei suo mio mia non noi siamo abbiamo per con questo questa è grazie può posso vorrei anche ma una del sono".split()),
    "pt": set("o a os as e eu você seu sua meu minha não nós somos temos para com este esta é obrigado obrigada pode posso gostaria também mas uma do da".split()),
}
_TOKEN = re.compile(r"[a-zà-ÿ]+(?:'[a-zà-ÿ]+)?", re.I)
_QUOTE = re.compile(
    r"\n-{2,}\s*original message|\n[ \t]*(?:On|Am|Op|Le|El|Il|Em) .{0,200}(?:wrote|schrieb|schreef|écrit|escribió|scritto|escreveu)|"
    r"\nFrom:|\nVon:|\nVan:|\nDe:|\n>",
    re.I,
)


def detect_language(text: str) -> str:
    """Return one of SUPPORTED when the customer's own text is clearly in it, otherwise "en"."""
    own = _QUOTE.split("\n" + (text or ""))[0]
    own = re.sub(r"https?://\S+|\S+@\S+", " ", own)
    toks = [t.lower() for t in _TOKEN.findall(own)]
    if len(toks) < 4:
        return "en"
    score = {lang: sum(t in words for t in toks) for lang, words in _WORDS.items()}
    best = max(SUPPORTED, key=lambda lang: score[lang])
    second = max((score[lang] for lang in SUPPORTED if lang != best), default=0)
    if score[best] >= 3 and score[best] > score["en"] * 1.5 and score[best] >= second + 2:
        return best
    return "en"


HOLDING = "Thank you for your message. I have asked the team to look at this, and they will follow up from here."
ACCESS = (
    "Thank you for letting us know, and sorry for the trouble. "
    "I have asked the team to check your access and send you a working link."
)
BOOKING = (
    "Thank you for your message. I have passed your request to change your booking to the team, "
    "and they will follow up with you from here."
)
APOLOGY = "Thank you for your patience, and our sincere apologies for the long wait in getting back to you."

TEXTS: dict[str, dict[str, str]] = {
    HOLDING: {
        "nl": "Bedankt voor je bericht. Ik heb het team gevraagd hiernaar te kijken, en zij nemen verder contact met je op.",
        "de": "Vielen Dank für Ihre Nachricht. Ich habe das Team gebeten, sich das anzusehen, und es meldet sich von hier aus bei Ihnen.",
        "fr": "Merci pour votre message. J'ai demandé à l'équipe d'examiner votre demande, et elle reviendra vers vous.",
        "es": "Gracias por su mensaje. He pedido al equipo que lo revise, y ellos se pondrán en contacto con usted.",
        "it": "Grazie per il suo messaggio. Ho chiesto al team di verificare, e la ricontatteranno loro.",
        "pt": "Obrigado pela sua mensagem. Pedi à equipa que analise o seu pedido, e eles entrarão em contacto consigo.",
    },
    ACCESS: {
        "nl": "Bedankt dat je het laat weten, en sorry voor het ongemak. Ik heb het team gevraagd je toegang te controleren en je een werkende link te sturen.",
        "de": "Danke für den Hinweis, und entschuldigen Sie die Umstände. Ich habe das Team gebeten, Ihren Zugang zu prüfen und Ihnen einen funktionierenden Link zu senden.",
        "fr": "Merci de nous avoir prévenus, et désolé pour la gêne occasionnée. J'ai demandé à l'équipe de vérifier votre accès et de vous envoyer un lien qui fonctionne.",
        "es": "Gracias por avisarnos, y disculpe las molestias. He pedido al equipo que revise su acceso y le envíe un enlace que funcione.",
        "it": "Grazie per avercelo segnalato, e ci scusiamo per il disagio. Ho chiesto al team di controllare il suo accesso e di inviarle un link funzionante.",
        "pt": "Obrigado por nos avisar, e pedimos desculpa pelo incómodo. Pedi à equipa que verifique o seu acesso e lhe envie um link que funcione.",
    },
    BOOKING: {
        "nl": "Bedankt voor je bericht. Ik heb je verzoek om je boeking te wijzigen doorgegeven aan het team, en zij nemen verder contact met je op.",
        "de": "Vielen Dank für Ihre Nachricht. Ich habe Ihre Bitte um Änderung der Buchung an das Team weitergegeben, und es meldet sich von hier aus bei Ihnen.",
        "fr": "Merci pour votre message. J'ai transmis votre demande de modification de réservation à l'équipe, et elle reviendra vers vous.",
        "es": "Gracias por su mensaje. He pasado su solicitud de cambio de reserva al equipo, y ellos se pondrán en contacto con usted.",
        "it": "Grazie per il suo messaggio. Ho inoltrato al team la sua richiesta di modifica della prenotazione, e la ricontatteranno loro.",
        "pt": "Obrigado pela sua mensagem. Passei o seu pedido de alteração da reserva à equipa, e eles entrarão em contacto consigo.",
    },
    APOLOGY: {
        "nl": "Bedankt voor je geduld, en onze oprechte excuses dat het zo lang heeft geduurd voordat we reageerden.",
        "de": "Vielen Dank für Ihre Geduld, und bitte entschuldigen Sie, dass unsere Antwort so lange gedauert hat.",
        "fr": "Merci pour votre patience, et toutes nos excuses pour ce long délai de réponse.",
        "es": "Gracias por su paciencia, y le pedimos sinceras disculpas por la larga espera.",
        "it": "Grazie per la pazienza, e ci scusiamo sinceramente per la lunga attesa della nostra risposta.",
        "pt": "Obrigado pela sua paciência, e as nossas sinceras desculpas pela longa espera pela nossa resposta.",
    },
}
_GREETING = re.compile(r"^(Hi [^\n,]{1,40},|Hi there,)\s*\n")


def localize_holding(body: str, customer_text: str) -> tuple[str, str]:
    """Translate a reply made only of the fixed holding sentences. Returns (body, language used)."""
    text = (body or "").strip()
    if not text:
        return body, "en"
    lang = detect_language(customer_text)
    if lang == "en":
        return body, "en"
    m = _GREETING.match(text + "\n")
    greet = m.group(1) if m else ""
    rest = text[len(greet):].strip() if greet else text
    parts = [p.strip() for p in re.split(r"\n\s*\n", rest) if p.strip()]
    if not parts or any(p not in TEXTS for p in parts):
        return body, "en"
    out = [TEXTS[p][lang] for p in parts]
    return "\n\n".join([greet, *out] if greet else out), lang
