# myMCP — Local MCP Gateway

Passerelle MCP (Model Context Protocol) locale avec outils vision, filesystem, puppeteer et authentification OAuth intégrée.

---

## 📦 Prérequis

- Python 3.10+
- Node.js 18+ (pour `npx`)
- [ngrok](https://ngrok.com/) (pour exposer le service en HTTPS)
- Permission **Screen Recording** (macOS) pour les outils vision/screenshot

---

## 🚀 Installation

### 1. Créer le venv et installer les dépendances

```bash
# Depuis la racine du projet
python3 -m venv .venv
source .venv/bin/activate

# Installer les dépendances
pip install fastmcp python-dotenv fastapi uvicorn pyjwt cryptography python-multipart pyautogui pillow
```

### 2. Configurer les variables d'environnement

Crée un fichier `config/.env` à la racine (ou copie `.env` existant) :

```bash
# Obligatoire
MCP_BASE_URL=https://ton-sous-domaine.ngrok-free.dev

# OAuth (optionnel, valores par défaut)
OAUTH_ISSUER=https://ton-sous-domaine.ngrok-free.dev/oauth
OAUTH_AUDIENCE=https://mcp.local
OAUTH_PORT=8762
OAUTH_TOKEN_TTL_SECONDS=3600

# Mode OAuth on/off
ENABLE_OAUTH=true

# Clé OAuth (générée automatiquement si absente)
OAUTH_KEY_ID=local-dev-key
```

> ⚠️ `MCP_BASE_URL` et `OAUTH_ISSUER` doivent pointer vers ton URL ngrok.

---

## 🏁 Démarrage

### Option A — `run.sh` tout-en-un (recommandé)

```bash
# Mode interactif — Ctrl+C arrête le gateway + ngrok
./run.sh

# Mode daemon (arrière-plan)
./run.sh start

# Arrêter le daemon
./run.sh stop

# Voir l'état du daemon
./run.sh status
```

Le script s'occupe de tout : activation du venv, lancement du gateway, tunnel ngrok.

### Option B — Lancement automatique simple

```bash
python3 start_services.py
```

Lance le service unique **Gateway** (MCP + OAuth intégré) sur le port `8761`.

Les logs sont écrits dans `logs/services/gateway.log`.

### Option C — Lancement manuel

```bash
source .venv/bin/activate
python3 src/mcp_gateway.py
# → http://localhost:8761/mcp
# → http://localhost:8761/oauth/...
```

---

## 🌐 Exposition via ngrok

```bash
# Un seul tunnel suffit — le gateway sert MCP + OAuth sur le même port
ngrok http 8761
# → https://xxxx-xxxx-xxxx.ngrok-free.dev
```

L'URL générée devient ton `MCP_BASE_URL` dans `config/.env`.

---

## 🛠️ Tools MCP disponibles

### 🔐 Authentification
| Tool | Description |
|---|---|
| `auth_status` | État OAuth : issuer, audience, base_url |

### 📁 File Sharing
| Tool | Description |
|---|---|
| `public_file_share` | Partager un fichier via URL publique |
| `public_file_list` | Lister les partages actifs |
| `public_file_revoke` | Révoquer un partage |

### 🖥️ Filesystem & Puppeteer (via npx)
| Tool | Description |
|---|---|
| `list_filesystem_available_tools` | Lister les outils du serveur filesystem |
| `list_puppeteer_available_tools` | Lister les outils du serveur puppeteer |
| `filesystem_execute_tool` | Exécuter un outil filesystem |
| `puppeteer_execute_tool` | Exécuter un outil puppeteer |

### 👁️ Vision & Automation
| Tool | Description |
|---|---|
| `vision_screen_size` | Taille de l'écran |
| `vision_screenshot` | Capture d'écran (fichier) |
| `vision_screenshot_as_base64` | Capture d'écran (base64) |
| `mouse_position` | Position actuelle de la souris |
| `mouse_move` | Déplacer la souris |
| `mouse_click_at` | Clic à une position spécifique |
| `mouse_click_current` | Clic à la position actuelle |
| `mouse_drag` | Glisser de la souris |
| `mouse_scroll` | Scroll |
| `keyboard_type` | Taper du texte |
| `keyboard_press` | Presser une touche |
| `keyboard_hotkey` | Combinaison de touches |

### 💻 Commandes
| Tool | Description |
|---|---|
| `run_command` | Exécuter une commande shell avec streaming |

---

## 🧪 Tests

### Tests unitaires OAuth (29 tests — sans dépendance externe)

```bash
pytest tests/test_oauth.py -v
```

Couvre : metadata, enregistrement client, authorization, token exchange, PKCE (S256), JWKS, validation JWT, codes expirés, réutilisation de code, edge cases.

### Tests d'intégration MCP (7 tests — nécessite le gateway en marche)

```bash
# Gateway doit tourner (./run.sh start), puis :
pytest tests/test_mcp_endpoint.py -v
```

Couvre : reachabilité, santé OAuth, discovery, JWKS live, flow OAuth complet (register → authorize → token), appel JSON-RPC (`initialize` + `tools/list`).

### Toute la suite

```bash
pytest tests/ -v
```

> Les tests d'intégration MCP sont automatiquement **skippés** si le gateway n'est pas joignable (localhost:8761). Aucun faux échec en CI ou hors-ligne.

---

## 📂 Structure du projet

```
myMCP/
├── config/
│   └── .env                 # Variables d'environnement
├── data/
│   ├── oauth_clients.json
│   ├── oauth_codes.json
│   ├── oauth_private_key.pem
│   └── public_file_shares.json
├── logs/
│   ├── commands/            # Logs des commandes exécutées
│   ├── services/            # Logs du gateway
│   └── vision/              # Captures d'écran
├── src/
│   ├── mcp_gateway.py       # Serveur MCP + OAuth unifié (port 8761)
│   └── lightweight_oauth.py # Module OAuth (importé par le gateway)
├── tests/
│   ├── conftest.py          # Fixtures partagées
│   ├── test_oauth.py        # 29 tests unitaires OAuth
│   └── test_mcp_endpoint.py # 7 tests d'intégration MCP
├── docs/
│   └── plans-dev/           # Plans de développement
├── run.sh                   # Gestionnaire tout-en-un (interactif + daemon)
├── start_services.py        # Lanceur du service unique
├── pytest.ini               # Configuration pytest
├── .env                     # Variables d'environnement (fallback)
└── README.md
```

---

## 🔗 Connexion depuis un client MCP

### Exemple avec ChatGPT (connector OAuth)

1. Lancer ngrok sur le port **8761**
2. Configurer `MCP_BASE_URL` avec l'URL ngrok
3. Dans ChatGPT, utiliser l'URL :
   ```
   https://ton-url.ngrok-free.dev/mcp
   ```
4. L'OAuth se fait automatiquement via le endpoint monté sur `/oauth`

### Exemple avec `fastmcp` CLI

```bash
fastmcp dev src/mcp_gateway.py
```

Ou en HTTP direct :

```bash
curl -X POST https://ton-url.ngrok-free.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
  }'
```

---

## 🧪 Vérifier que tout tourne

```bash
# Santé du service OAuth
curl http://localhost:8762/oauth/health

# Métadonnées OAuth
curl http://localhost:8762/oauth/.well-known/oauth-authorization-server

# JWKS
curl http://localhost:8762/oauth/jwks.json
```

---

## ⚠️ Sécurité

- `run_command` exécute des commandes shell **sans restriction** — utiliser avec précaution
- Les tokens OAuth sont signés avec une clé RSA locale (générée dans `data/oauth_private_key.pem`)
- Les fichiers partagés via `public_file_share` sont accessibles sans authentification
- Les logs de commandes contiennent toutes les entrées/sorties — ne pas exposer les logs
