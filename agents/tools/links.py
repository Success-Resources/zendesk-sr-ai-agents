"""Approved MMI registration, factsheet, Facebook and WhatsApp links by city/country."""

from __future__ import annotations

import re

REGISTER_URL = "https://millionairemind.live/"

# Place aliases → (city_key, country_key)
_PLACES: list[tuple[tuple[str, ...], str, str]] = [
    (("brussels", "bruxelles", "belgie", "belgië", "belgium"), "brussels", "belgium"),
    (("munich", "munchen", "münchen"), "munich", "germany"),
    (("cluj",), "cluj", "romania"),
    (("amsterdam",), "amsterdam", "netherlands"),
    (("krakow", "kraków", "cracow"), "krakow", "poland"),
    (("warsaw", "warszawa"), "warsaw", "poland"),
    (("gdansk", "gdańsk"), "gdansk", "poland"),
    (("manchester",), "manchester", "uk"),
    (("hamburg",), "hamburg", "germany"),
    (("barcelona",), "barcelona", "spain"),
    (("zurich", "zürich", "zurich"), "zurich", "switzerland"),
    (("ljubljana", "slovenia"), "ljubljana", "slovenia"),
    (("frankfurt",), "frankfurt", "germany"),
    (("bucharest", "bucuresti", "bucurești"), "bucharest", "romania"),
    (("hague", "den haag", "the hague"), "hague", "netherlands"),
    (("rotterdam",), "rotterdam", "netherlands"),
    (("london",), "london", "uk"),
    (("birmingham",), "birmingham", "uk"),
    (("dublin", "ireland"), "dublin", "ireland"),
    (("cologne", "koln", "köln", "koeln"), "cologne", "germany"),
    (("dusseldorf", "düsseldorf"), "dusseldorf", "germany"),
    (("stockholm", "sweden"), "stockholm", "sweden"),
    (("geneva", "genève", "geneve"), "geneva", "switzerland"),
    (("berlin",), "berlin", "germany"),
    (("madrid",), "madrid", "spain"),
    (("vienna", "wien", "austria"), "vienna", "austria"),
    (("oslo", "norway"), "oslo", "norway"),
    (("romania",), "", "romania"),
    (("poland", "polska"), "", "poland"),
    (("netherlands", "holland", "nederland"), "", "netherlands"),
    (("germany", "deutschland"), "", "germany"),
    (("spain", "espana", "españa"), "", "spain"),
    (("switzerland", "schweiz"), "", "switzerland"),
    (("united kingdom", "great britain", "england", "scotland", "wales", "uk"), "", "uk"),
    (("belgium",), "", "belgium"),
]

_FACTSHEETS = {
    "brussels": ("Belgium, Brussels", "https://sr-event.com/bru-factsheet"),
    "munich": ("Munich, Germany Holiday Inn City Centre", "https://sr-event.com/mun-factsheet"),
    "cluj": ("Cluj, Romania", "https://sr-event.com/clu-factsheet"),
    "amsterdam": ("Amsterdam, Netherlands", "https://sr-event.com/ams-factsheet"),
    "krakow": ("Krakow, Poland", "https://sr-event.com/kra-factsheet"),
    "manchester": ("Manchester, United Kingdom", "https://sr-event.com/man-factsheet"),
    "hamburg": ("Hamburg, Germany", "https://sr-event.com/ham-factsheet"),
    "barcelona": ("Barcelona, Spain", "https://sr-event.com/bar-factsheet"),
    "zurich": ("Zurich, Switzerland", "https://sr-event.com/zur-factsheet"),
    "ljubljana": ("Ljubljana, Slovenia", "https://sr-event.com/lju-factsheet"),
    "frankfurt": ("Frankfurt, Germany", "https://sr-event.com/fra-factsheet"),
    "bucharest": ("Bucharest, Romania", "https://sr-event.com/mal-factsheet"),
    "hague": ("The Hague, Netherlands", "https://sr-event.com/tha-factsheet"),
    "london": ("London, United Kingdom", "https://sr-event.com/lon-factsheet"),
    "cologne": ("Cologne, Germany", "https://sr-event.com/col-factsheet"),
    "stockholm": ("Stockholm, Sweden", "https://sr-event.com/sto-factsheet"),
    "geneva": ("Geneva, Switzerland", "https://sr-event.com/gen-factsheet"),
    "berlin": ("Berlin, Germany", "https://sr-event.com/ber-factsheet"),
    "madrid": ("Madrid, Spain", "https://sr-event.com/mad-factsheet"),
    "birmingham": ("Birmingham, United Kingdom", "https://sr-event.com/bir-factsheet"),
}

_FACEBOOK = {
    "uk": ("UK (Birmingham and London)", "https://www.facebook.com/groups/mmi.uk"),
    "ireland": ("Ireland / Dublin", "https://www.facebook.com/groups/191091810715204"),
    "romania": ("Romania (Cluj and Bucharest)", "https://www.facebook.com/groups/310045161828229"),
    "poland": ("Poland (Krakow, Warsaw, Gdansk)", "https://www.facebook.com/groups/mmipl/"),
    "belgium": ("Belgium / Brussels", "https://www.facebook.com/groups/387608201005090"),
    "netherlands": ("The Netherlands (The Hague, Amsterdam, Rotterdam, Den Haag)", "https://www.facebook.com/groups/987653195761616"),
    "switzerland": ("Switzerland / Geneva", "https://www.facebook.com/groups/7153704451344118"),
    "spain": ("Spain (Madrid and Barcelona)", "https://www.facebook.com/groups/mmies"),
    "austria": ("Austria / Vienna", "https://www.facebook.com/groups/mmiaustria"),
    "germany": ("Germany (Frankfurt, Cologne, Hamburg, Munich, Düsseldorf)", "https://www.facebook.com/groups/922702168837589"),
    "sweden": ("Sweden / Stockholm", "https://www.facebook.com/groups/mmi.sweden"),
}

_WHATSAPP = {
    "switzerland": "https://chat.whatsapp.com/EUNr0eJlIuX6tzv9VT8QCp",
    "slovenia": "https://chat.whatsapp.com/I48pGSZUs9Y5UjmsdOXRUS",
    "uk": "https://chat.whatsapp.com/KBkhv9Q63AhAwAxA4fJwgh",
    "sweden": "https://chat.whatsapp.com/CQ6DohUyhyUGZdXAuwTmAG",
    "norway": "https://chat.whatsapp.com/Dt7tZ7CdiO87AHrrVWyHbh",
    "poland": "https://chat.whatsapp.com/JLY8rd4OT5pIZTdZei4N95",
    "germany": "https://chat.whatsapp.com/GqsCmWBDiK4GVHyrm10uTX",
    "netherlands": "https://chat.whatsapp.com/GgKLw88o4DM5TQP6KJmvA6",
    "spain": "https://chat.whatsapp.com/DFeaxBg3vZEIYYN4GAOtU7",
    "belgium": "https://chat.whatsapp.com/DrfHO1DaaqSEL9OMLZyX3p",
    "romania": "https://chat.whatsapp.com/CPeorlY8GadLqBl0E0WZxP",
}

_CITIES_BY_COUNTRY: dict[str, list[str]] = {}
for _aliases, city, country in _PLACES:
    if city:
        _CITIES_BY_COUNTRY.setdefault(country, [])
        if city not in _CITIES_BY_COUNTRY[country]:
            _CITIES_BY_COUNTRY[country].append(city)


def _blob(query: str) -> str:
    return re.sub(r"[^a-z0-9äöüéè\s]", " ", (query or "").lower())


def _place(query: str) -> tuple[str, str]:
    blob = f" {_blob(query)} "
    # Longer aliases first so "the hague" wins over "hague" and "united kingdom" over "uk".
    ranked = sorted(_PLACES, key=lambda item: max(len(a) for a in item[0]), reverse=True)
    for aliases, city, country in ranked:
        for alias in aliases:
            if f" {alias} " in blob:
                return city, country
    return "", ""


def _wants_register(query: str) -> bool:
    q = query.lower()
    if re.search(r"\b(already registered|am i booked|did i (get|register)|confirmation email)\b", q):
        return False
    return bool(
        re.search(
            r"\b(registration link|sign[- ]?up|where (do i|can i) register|"
            r"how (do i|can i) register|register online|buy (a |my )?ticket|"
            r"link to register)\b",
            q,
        )
    )


def _wants_factsheet(query: str) -> bool:
    return bool(re.search(r"\bfact\s*sheet\b|\bfactsheet\b", query, re.I))


def _wants_facebook(query: str) -> bool:
    return bool(re.search(r"\bfacebook\b|\bfb group\b|\bfacebook group\b", query, re.I))


def _wants_whatsapp(query: str) -> bool:
    return bool(re.search(r"\bwhats?app\b|\bwa group\b", query, re.I))


def lookup_links(query: str) -> str:
    """Return the approved MMI link for this ticket, or tell Maya which city to ask for."""
    q = (query or "").strip()
    city, country = _place(q)
    wants = []
    if _wants_register(q):
        wants.append("register")
    if _wants_factsheet(q):
        wants.append("factsheet")
    if _wants_facebook(q):
        wants.append("facebook")
    if _wants_whatsapp(q):
        wants.append("whatsapp")
    if not wants:
        wants = ["register", "factsheet", "facebook", "whatsapp"]

    lines = ["APPROVED MMI LINKS. Use only these URLs. Do not invent a group or factsheet."]
    if city or country:
        lines.append(f"Detected place: city={city or '(none)'} country={country or '(none)'}")

    if "register" in wants:
        if country or city:
            lines.append(
                f"REGISTRATION: they named a location. Tell them they can register on "
                f"the official MMI website: {REGISTER_URL}"
            )
        else:
            lines.append(
                "REGISTRATION: city/country missing. Ask which country they want to attend, "
                f"then tell them they can register on {REGISTER_URL}"
            )

    if "factsheet" in wants:
        if city and city in _FACTSHEETS:
            label, url = _FACTSHEETS[city]
            lines.append(f"FACTSHEET for {label}: {url}")
        elif country:
            cities = [c for c in _CITIES_BY_COUNTRY.get(country, []) if c in _FACTSHEETS]
            if len(cities) == 1:
                label, url = _FACTSHEETS[cities[0]]
                lines.append(f"FACTSHEET for {label}: {url}")
            elif cities:
                names = ", ".join(_FACTSHEETS[c][0] for c in cities)
                lines.append(
                    f"FACTSHEET: they named {country} but not a city. Ask which city "
                    f"({names}), then send the matching sr-event.com factsheet. Do not guess."
                )
            else:
                lines.append(
                    f"FACTSHEET: no listed factsheet for {country}. Ask which city they will "
                    "attend. If it is not on the list, set needs_human true."
                )
        else:
            lines.append(
                "FACTSHEET: city missing. Ask which city they will attend, then send the "
                "matching https://sr-event.com/…-factsheet from this list only."
            )

    if "facebook" in wants:
        key = country
        if key and key in _FACEBOOK:
            label, url = _FACEBOOK[key]
            lines.append(f"FACEBOOK group {label}: {url}")
        elif key:
            lines.append(
                f"FACEBOOK: no listed group for {key}. Ask a person. Do not invent a group URL."
            )
        else:
            lines.append(
                "FACEBOOK: city/country missing. Ask which city or country they will attend, "
                "then send the matching country Facebook group from this list only."
            )

    if "whatsapp" in wants:
        key = country
        if key and key in _WHATSAPP:
            lines.append(f"WHATSAPP group {key.title()}: {_WHATSAPP[key]}")
        elif key:
            lines.append(
                f"WHATSAPP: no listed group for {key}. Ask a person. Do not invent an invite link."
            )
        else:
            lines.append(
                "WHATSAPP: country missing. Ask which country they want, then send the matching "
                "chat.whatsapp.com link from this list only."
            )

    return "\n".join(lines)
