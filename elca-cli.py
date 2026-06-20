#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: str | Path = ".env"):
    p = Path(path).expanduser()
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(Path(__file__).parent / ".env")

import requests

BASE = "https://areaclienti.elcasas.it"
SESSDIR = Path.home() / ".elca-cli"
SESSFILE = SESSDIR / "session.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
    "Content-Type": "application/x-www-form-urlencoded",
}

MENU = {
    "7":  "AnagraficaUtenti",
    "1":  "DatiUtenza",
    "3":  "domiciliazione",
    "4":  "Password",
    "8":  "Fatture",
    "9":  "Consumi",
    "11": "Contatori",
    "14": "Autoletture",
    "10": "Volture",
    "13": "CessazioneUtenze",
    "12": "Email",
    "2":  "invio_file",
}


@dataclass
class ElcaSession:
    cookies: dict
    viewstate: str | None
    viewstategen: str | None
    eventvalidation: str | None
    last_url: str
    session_path: str
    user: str
    password: str
    last_page: str | None = None
    menu_page: str | None = None
    last_body: str | None = None

    def save(self):
        SESSDIR.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in self.__dict__.items()}
        with open(SESSFILE, "w") as f:
            json.dump(data, f, indent=2, default=str)


def load_session() -> ElcaSession | None:
    if not SESSFILE.exists():
        return None
    try:
        with open(SESSFILE) as f:
            return ElcaSession(**json.load(f))
    except Exception:
        return None


def _hidden(html: str, field: str) -> str | None:
    m = re.search(rf'name="{re.escape(field)}"[^>]*value="([^"]*)"', html)
    if m:
        return m.group(1)
    m = re.search(rf'id="{re.escape(field)}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else None


def _hidden_sq(html: str, field: str) -> str | None:
    m = re.search(rf"name='{re.escape(field)}'[^>]*value='([^']*)'", html)
    return m.group(1) if m else None


def _vs(html: str) -> dict:
    return {
        "viewstate": _hidden(html, "__VIEWSTATE"),
        "viewstategen": _hidden(html, "__VIEWSTATEGENERATOR"),
        "eventvalidation": _hidden(html, "__EVENTVALIDATION"),
    }


def _session_from_url(url: str) -> str:
    m = re.search(r"/\(S\(([a-z0-9]+)\)\)/", url)
    return m.group(1) if m else ""


def _fkey_post(session: ElcaSession, key: str, map_: str = "101000000000000000000000001100") -> dict:
    maps = {"F6": "101001000110000000000000000000"}
    page = session.last_page or "WEA500V"
    data = {
        "__VIEWSTATE": session.viewstate or "",
        "__VIEWSTATEGENERATOR": session.viewstategen or "",
        "__EVENTVALIDATION": session.eventvalidation or "",
        "__isDspF__": "1",
        "__atKMap__": maps.get(key, map_),
        "__atCursor__": "",
        "__submitField__": "",
        "__atField__": "",
        "__atRecord__": "",
        "__focusID__": "",
        "__csrLocPos__": "0",
        "__ss__": "",
        "__atSubfile__": "",
        f"ctl00$FKeyPH${page}Control": key,
        "__atSflRRN__": "",
        "__SflLowestRRN__": "",
        "__SessionInfo__": json.dumps({"s": session.session_path}),
    }
    tb = {"F1": "ctl00$TBarPH$F1_Button", "F3": "ctl00$TBarPH$F3_Button",
          "PgUp": "ctl00$TBarPH$pgup_button", "PgDn": "ctl00$TBarPH$pgdw_button"}
    if key in tb:
        data[tb[key]] = "x"
    return data


def _post(session: ElcaSession, url: str, data: dict) -> requests.Response:
    r = requests.post(url, data=data, headers={**HEADERS, "Referer": url},
                      cookies=session.cookies, allow_redirects=True, timeout=60)
    if r.cookies:
        session.cookies.update(r.cookies)
    if r.history:
        for hist in r.history:
            if hist.cookies:
                session.cookies.update(hist.cookies)
    sp = _session_from_url(r.url)
    if sp:
        session.session_path = sp
    session.last_url = r.url
    return r


def _get(session: ElcaSession, url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, cookies=session.cookies, timeout=30)
    if r.cookies:
        session.cookies.update(r.cookies)
    sp = _session_from_url(r.url)
    if sp:
        session.session_path = sp
    session.last_url = r.url
    return r


def _parse_readings(html: str) -> tuple[dict, list[dict]]:
    readings = []
    info = {}
    for label, field in [("Utente", r"Utente:\s*(\d+)"),
                          ("Nome", r"([A-ZÀ-Ú]+)\s+(?:Locale|Loc)"),
                          ("Locale", r"Locale:\s*(\d+)"),
                          ("Indirizzo", r"Indirizzo:\s*([^<]+)"),
                          ("Tipologia", r"Tipologia:\s*([^<]+)"),
                          ("Contatore", r"Contatore:\s*(\d+)")]:
        m = re.search(field, html)
        if m:
            info[label] = m.group(1).strip()
    m = re.search(r'Contatore:\s*\d+\s*([A-ZÀ-Ú\s]+?)(?:<|$)', html)
    if m:
        info["Fornitura"] = m.group(1).strip()
    dates = re.findall(r'W1DATA\.\d+[^>]*>([^<]+)', html)
    values = re.findall(r'W1LETT\.\d+[^>]*>([^<]+)', html)
    types = re.findall(r'W1DLET\.\d+[^>]*>([^<]+)', html)
    for i in range(min(len(dates), len(values), len(types))):
        val = values[i].replace("&nbsp;", "").strip()
        readings.append({"data": dates[i].strip(), "lettura": val, "tipo": types[i].strip()})
    return info, readings


def _print_readings(html: str):
    info, readings = _parse_readings(html)
    if info:
        print(f"  📍 {info.get('Utente', '?')} - {info.get('Nome', '?')}")
        print(f"  🏠 {info.get('Indirizzo', '?')} - {info.get('Locale', '?')}")
        print(f"  💧 {info.get('Fornitura', '?')}  (contatore {info.get('Contatore', '?')})")
    print()
    if readings:
        print(f"  {'Data':<12} {'Lettura':<12} {'Tipo':<40}")
        print(f"  {'─'*12} {'─'*12} {'─'*40}")
        for r in readings:
            print(f"  {r['data']:<12} {r['lettura']:<12} {r['tipo']:<40}")
    else:
        print("  Nessuna lettura trovata.")


def _extract_menu(html: str) -> list[str]:
    items = []
    for num, label in MENU.items():
        if f"Images/{label}.png" in html:
            items.append(f"[{num:>2}] {label}")
    return items


def _nav_to(session: ElcaSession, image_button: str) -> requests.Response:
    if session.last_page and session.last_page != "WEA500V":
        fk = _fkey_post(session, "F3")
        _post(session, session.last_url, fk)
    menu = session.menu_page or session.last_url
    r = _get(session, menu)
    vs = _vs(r.text)
    session.viewstate = vs["viewstate"]
    session.viewstategen = vs["viewstategen"]
    session.eventvalidation = vs["eventvalidation"]
    post_data = {
        "__VIEWSTATE": session.viewstate or "",
        "__VIEWSTATEGENERATOR": session.viewstategen or "",
        "__EVENTVALIDATION": session.eventvalidation or "",
        f"ctl00$CenPH$ImageButton{image_button}.x": "66",
        f"ctl00$CenPH$ImageButton{image_button}.y": "78",
        "__isDspF__": "1",
        "__atKMap__": "101000000000000000000000001100",
        "__atCursor__": "",
        "__submitField__": "",
        "__atField__": "",
        "__atRecord__": "",
        "__focusID__": "",
        "__csrLocPos__": "0",
        "__ss__": "",
        "__atSubfile__": "",
        "ctl00$FKeyPH$WEA500VControl": "Enter",
        "__atSflRRN__": "",
        "__SflLowestRRN__": "",
        "__SessionInfo__": json.dumps({"s": session.session_path}),
    }
    return _post(session, menu, post_data)



def _signon_enter(session: ElcaSession, url: str) -> tuple[requests.Response, str]:
    vs = _vs(session.last_body)
    session.viewstate = vs["viewstate"]
    session.viewstategen = vs["viewstategen"]
    session.eventvalidation = vs["eventvalidation"]
    session_info = _hidden_sq(session.last_body, "__SessionInfo__") or json.dumps({"s": session.session_path})
    data = {
        "__VIEWSTATE": session.viewstate or "",
        "__VIEWSTATEGENERATOR": session.viewstategen or "",
        "__EVENTVALIDATION": session.eventvalidation or "",
        "ctl00$CenPH$WHXTAG": "",
        "ctl00$CenPH$WHXTIPD": "",
        "ctl00$CenPH$WHXSISO": "",
        "ctl00$CenPH$WHXMARC": "",
        "ctl00$CenPH$WHXMOD": "",
        "ctl00$CenPH$WHXVERS": "",
        "ctl00$CenPH$WHXNOMD": "",
        "ctl00$CenPH$Button_access_Click": "Accedi",
        "ctl00$FKeyPH$SignOnControl": "Enter",
        "__isDspF__": "1",
        "__atKMap__": "000000000000000000000000000000",
        "__submitField__": "ctl00$CenPH$Button_access_Click",
        "__focusID__": "ctl00$CenPH$WHTAG",
        "__csrLocPos__": "0",
        "__SessionInfo__": session_info,
    }
    return _post(session, url, data), session_info


def cmd_login(args):
    username = args.username or os.environ.get("USERNAME") or os.environ.get("ELCA_USER")
    password = args.password or os.environ.get("PASSWORD") or os.environ.get("ELCA_PASS")
    if not username or not password:
        print("Servono username e password. Mettili nel .env o passali come argomenti.")
        sys.exit(1)

    sess = ElcaSession(cookies={}, viewstate=None, viewstategen=None,
                       eventvalidation=None, last_url="", session_path="",
                       user=username, password=password)
    print(f"Login come {username}...", end=" ", flush=True)

    r = _get(sess, f"{BASE}/portale/")
    if "SiteDown" in r.url:
        print("Portale in manutenzione.")
        sys.exit(1)
    sess.last_body = r.text

    r, _ = _signon_enter(sess, sess.last_url)
    if "SiteDown" in r.url:
        print("Portale in manutenzione.")
        sys.exit(1)
    if "WEA000V" not in r.url:
        print(f"SignOn fallito (su {r.url[-50:]}).")
        sys.exit(1)

    sess.last_page = "WEA000V"
    sess.last_body = r.text
    vs = _vs(r.text)
    sess.viewstate = vs["viewstate"]
    sess.viewstategen = vs["viewstategen"]
    sess.eventvalidation = vs["eventvalidation"]

    post_data = {
        "__VIEWSTATE": sess.viewstate or "",
        "__VIEWSTATEGENERATOR": sess.viewstategen or "",
        "__EVENTVALIDATION": sess.eventvalidation or "",
        "ctl00$CenPH$W1UTEN": username,
        "ctl00$CenPH$W1PSW": password,
        "__isDspF__": "1",
        "__atKMap__": "101001000110000000000000000000",
        "__atCursor__": "7,25",
        "__submitField__": "",
        "__atField__": "W$PSW",
        "__atRecord__": "W$FM01",
        "__focusID__": "ctl00$CenPH$W1IP",
        "__csrLocPos__": "0",
        "__ss__": "",
        "__atSubfile__": "",
        "ctl00$FKeyPH$WEA000VControl": "F6",
        "__atSflRRN__": "-1",
        "__SflLowestRRN__": "",
        "__SessionInfo__": json.dumps({"s": sess.session_path}),
    }
    r = _post(sess, sess.last_url, post_data)

    if "WEA500V" not in r.url:
        print(f"\nLogin fallito (su {r.url[-50:]}).")
        if "SiteDown" in r.url:
            print("Portale in manutenzione.")
        sys.exit(1)

    sess.last_page = "WEA500V"
    sess.menu_page = r.url
    vs = _vs(r.text)
    sess.viewstate = vs["viewstate"]
    sess.viewstategen = vs["viewstategen"]
    sess.eventvalidation = vs["eventvalidation"]
    sess.save()

    m = re.search(r'Ciao,?\s*([^<]+)', r.text)
    print(f"Ciao, {m.group(1).strip() if m else '?'}")

    items = _extract_menu(r.text)
    print(f"\nMenu ({len(items)} voci):")
    for item in items:
        num = item.split("]")[0].strip(" [")
        label = item.split("]")[1].strip()
        print(f"  elca-cli menu {num}   -> {label}")
    print(f"\n  elca-cli consumi")
    print(f"  elca-cli fatture")


def cmd_consumi(args):
    sess = load_session()
    if not sess or not sess.menu_page:
        print("Nessuna sessione valida. Fai 'elca-cli login' prima.")
        sys.exit(1)
    print("Consumi...", end=" ", flush=True)
    r = _nav_to(sess, "9")
    vs = _vs(r.text)
    sess.viewstate = vs["viewstate"]
    sess.viewstategen = vs["viewstategen"]
    sess.eventvalidation = vs["eventvalidation"]
    sess.last_page = "WEB200V"
    sess.save()
    if "WEB200V" in r.url:
        print()
        _print_readings(r.text)
    else:
        print(f" su {r.url[-60:]}")


def cmd_fatture(args):
    sess = load_session()
    if not sess or not sess.menu_page:
        print("Nessuna sessione valida. Fai 'elca-cli login' prima.")
        sys.exit(1)
    print("Fatture...", end=" ", flush=True)
    r = _nav_to(sess, "8")
    vs = _vs(r.text)
    sess.viewstate = vs["viewstate"]
    sess.viewstategen = vs["viewstategen"]
    sess.eventvalidation = vs["eventvalidation"]
    sess.last_url = r.url
    sess.save()

    m = re.search(r'<title>([^<]+)</title>', r.text)
    print(m.group(1).strip() if m else '?')

    pdfs = re.findall(r'href="([^"]*\.pdf[^"]*)"', r.text, re.IGNORECASE)
    if pdfs:
        for p in pdfs:
            print(f"  {p}")
    else:
        stripped = re.sub(r'<script[^>]*>.*?</script>', '', r.text, flags=re.DOTALL)
        stripped = re.sub(r'<style[^>]*>.*?</style>', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'<[^>]+>', '\n', stripped)
        stripped = re.sub(r'\n\s*\n', '\n', stripped).strip()
        for line in stripped.split('\n'):
            line = line.strip()
            if line and len(line) > 5:
                print(f"  {line[:120]}")


def cmd_menu(args):
    sess = load_session()
    if not sess or not sess.menu_page:
        print("Nessuna sessione valida. Fai 'elca-cli login' prima.")
        sys.exit(1)
    if args.item is None:
        r = _get(sess, sess.menu_page)
        vs = _vs(r.text)
        sess.viewstate = vs["viewstate"]
        sess.viewstategen = vs["viewstategen"]
        sess.eventvalidation = vs["eventvalidation"]
        sess.save()
        items = _extract_menu(r.text)
        print(f"Menu ({len(items)} voci):")
        for item in items:
            print(f"  {item}")
        print(f"\nUsa: elca-cli menu <numero>")
        return

    label = MENU.get(args.item, f"voce {args.item}")
    print(f"{label}...", end=" ", flush=True)
    r = _nav_to(sess, args.item)
    vs = _vs(r.text)
    sess.viewstate = vs["viewstate"]
    sess.viewstategen = vs["viewstategen"]
    sess.eventvalidation = vs["eventvalidation"]
    sess.last_url = r.url
    sess.save()

    m = re.search(r'<title>([^<]+)</title>', r.text)
    print(m.group(1).strip() if m else '?')

    stripped = re.sub(r'<script[^>]*>.*?</script>', '', r.text, flags=re.DOTALL)
    stripped = re.sub(r'<style[^>]*>.*?</style>', '', stripped, flags=re.DOTALL)
    stripped = re.sub(r'<[^>]+>', '\n', stripped)
    stripped = re.sub(r'\n\s*\n', '\n', stripped).strip()
    for line in stripped.split('\n'):
        line = line.strip()
        if line and len(line) > 5:
            print(f"  {line[:120]}")


def cmd_invia(args):
    sess = load_session()
    if not sess:
        print("Nessuna sessione salvata. Fai 'elca-cli login' prima.")
        sys.exit(1)
    r = _get(sess, sess.last_url)
    vs = _vs(r.text)
    sess.viewstate = vs["viewstate"]
    sess.viewstategen = vs["viewstategen"]
    sess.eventvalidation = vs["eventvalidation"]
    print(f"Invio autolettura: {args.lettura} (riga {args.riga})...", end=" ", flush=True)
    page = sess.last_page or "WEB200V"
    post_data = {
        "__VIEWSTATE": sess.viewstate or "",
        "__VIEWSTATEGENERATOR": sess.viewstategen or "",
        "__EVENTVALIDATION": sess.eventvalidation or "",
        "__isDspF__": "1",
        "__atKMap__": "101000000000000000000000001100",
        "__atCursor__": "",
        "__submitField__": "ctl00$CenPH$_W_usd_FM01",
        "__atField__": "W$FM01",
        "__atRecord__": "",
        "__focusID__": f"ctl00$CenPH$_W_usd_FM01_{args.riga}",
        "__csrLocPos__": "0",
        "__ss__": "",
        "__atSubfile__": "",
        f"ctl00$FKeyPH${page}Control": "Enter",
        "__atSflRRN__": "",
        "__SflLowestRRN__": "",
        "__SessionInfo__": json.dumps({"s": sess.session_path}),
        f"ctl00$CenPH$_W_usd_FM01_{args.riga}": args.lettura,
    }
    r = _post(sess, sess.last_url, post_data)
    vs2 = _vs(r.text)
    sess.viewstate = vs2["viewstate"]
    sess.viewstategen = vs2["viewstategen"]
    sess.eventvalidation = vs2["eventvalidation"]
    sess.last_url = r.url
    sess.save()
    if "WEB200V" in r.url:
        print()
        _print_readings(r.text)
    else:
        print(f" {r.url[-60:]}")


def cmd_nav(args):
    sess = load_session()
    if not sess:
        print("Nessuna sessione salvata. Fai 'elca-cli login' prima.")
        sys.exit(1)
    r = _get(sess, sess.last_url)
    vs = _vs(r.text)
    sess.viewstate = vs["viewstate"]
    sess.viewstategen = vs["viewstategen"]
    sess.eventvalidation = vs["eventvalidation"]
    print(f"{args.key}...", end=" ", flush=True)
    r = _post(sess, sess.last_url, _fkey_post(sess, args.key))
    vs2 = _vs(r.text)
    sess.viewstate = vs2["viewstate"]
    sess.viewstategen = vs2["viewstategen"]
    sess.eventvalidation = vs2["eventvalidation"]
    for p in ["WEB200V", "WEA500V", "WEA000V", "WEB100V"]:
        if p in r.url:
            sess.last_page = p
            break
    sess.save()
    print(f"{r.url[-60:]}")


def main():
    parser = argparse.ArgumentParser(
        description="CLI per il portale Elca acqua",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Esempi:\n"
            "  elca-cli login -u MATRICOLA -p 'password'\n"
            "  elca-cli consumi\n"
            "  elca-cli fatture\n"
            "  elca-cli menu\n"
            "  elca-cli menu 9\n"
            "  elca-cli invia 1234\n"
            "  elca-cli nav F3\n"
        ),
    )
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("login", help="Login e salva sessione")
    p.add_argument("-u", "--username")
    p.add_argument("-p", "--password")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("consumi", help="Mostra i consumi")
    p.set_defaults(func=cmd_consumi)

    p = sub.add_parser("fatture", help="Mostra le bollette")
    p.set_defaults(func=cmd_fatture)

    p = sub.add_parser("menu", help="Mostra o naviga menu")
    p.add_argument("item", nargs="?", help="Numero voce menu (9=Consumi, 8=Fatture)")
    p.set_defaults(func=cmd_menu)

    p = sub.add_parser("invia", help="Invia autolettura")
    p.add_argument("lettura", help="Valore contatore")
    p.add_argument("--riga", type=int, default=0)
    p.set_defaults(func=cmd_invia)

    p = sub.add_parser("nav", help="Tasto funzione (F1, F3, F6, PgUp, PgDn)")
    p.add_argument("key", help="F1=Help, F3=Logout, F6=Login, PgUp, PgDn")
    p.set_defaults(func=cmd_nav)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
