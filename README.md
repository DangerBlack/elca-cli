# elca-cli

CLI per il portale Elca acqua (areaclienti.elcasas.it). Parla HTTP diretto con l'emulatore ASNA Monarch (AS400 → Web), niente browser, niente BeautifulSoup.

## Installazione

```bash
pip install -r requirements.txt
python3 elca-cli.py --help
```

Dipende solo da `requests`.

## Setup

Crea un file `.env` nella stessa cartella dello script:

```
USERNAME=MATRICOLA
PASSWORD=la_tua_password
```

Oppure passa username/password come argomento.

## Comandi

| Comando | Cosa fa |
|---------|---------|
| `login` | Login e salva la sessione |
| `consumi` | Mostra storico letture |
| `fatture` | Mostra bolletta corrente |
| `menu [n]` | Mostra/naviga menu |
| `invia <valore>` | Invia autolettura |
| `nav <tasto>` | Tasto funzione (F3, PgUp, PgDn...) |

### Esempi

```bash
# Login (username da .env o -u)
python3 elca-cli.py login
python3 elca-cli.py login -u MATRICOLA

# Consumi e fatture
python3 elca-cli.py consumi
python3 elca-cli.py fatture

# Esplora menu
python3 elca-cli.py menu
python3 elca-cli.py menu 14   # Autoletture

# Tasti funzione
python3 elca-cli.py nav F3    # Torna al menu
python3 elca-cli.py nav PgDn  # Pagina successiva

# Autolettura
python3 elca-cli.py invia 1234
```

## Come funziona

Il portale usa ASP.NET WebForms con emulatore ASNA Monarch. Ogni azione è una POST con VIEWSTATE e tasti funzione (F3, F6, Enter). La CLI mantiene la sessione in `~/.elca-cli/session.json` e ricostruisce le richieste parlando direttamente le operazioni macchina dell'AS400.

Reverse engineering completo in [.code/elca-portal-analysis.md](.code/elca-portal-analysis.md).
