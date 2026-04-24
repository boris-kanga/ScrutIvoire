# ScrutIvoire

**Plateforme d'archivage et d'analyse électorale — Côte d'Ivoire**

ScrutIvoire permet de charger des rapports électoraux PDF officiels, d'en extraire automatiquement les données tabulaires, et d'interroger ces données en langage naturel via un agent SQL.

---

## Aperçu

```
┌─────────────────────────────────────────────────────────┐
│                        ScrutIvoire                      │
│                                                         │
│   Vue Admin          Vue Utilisateur     Monitoring     │
│   ─────────          ─────────────────  ──────────      │
│   • Charger PDF      • Liste élections  • Traces LLM    │
│   • Voir extraction  • Chat avec data   • SQL généré    │
│   • Gérer users      • Graphiques       • Tokens/latence│
└─────────────────────────────────────────────────────────┘
         │                    │
    ┌────▼─────┐         ┌────▼─────┐
    │  Worker  │         │   API    │
    │ (extract)│         │ (Flask)  │
    └────┬─────┘         └────┬─────┘
         │                    │
    ┌────▼────────────────────▼─────┐
    │  PostgreSQL  │  Redis  │ MinIO │
    └───────────────────────────────┘
```

---

## Stack

| Composant | Technologie                            |
|---|----------------------------------------|
| Backend | Python 3.11+, Flask, SocketIO          |
| Worker | Python asyncio                         |
| Base de données | PostgreSQL 16                          |
| Cache / PubSub | Redis 7                                |
| Stockage fichiers | MinIO (compatible S3)                  |
| LLM | OpenAI, Groq, Cerebras, Gemini, Ollama |
| Frontend | HTML/CSS/JS, Tailwind CSS, D3.js       |

---

## Prérequis

- Docker & Docker Compose
- Au moins une clé API LLM (OpenAI recommandé)
- 4 Go RAM minimum

---

## Installation

### 1. Cloner le repo

```bash
git clone https://github.com/ton-user/scrutivoire.git
cd scrutivoire
```

### 2. Configurer l'environnement

```bash
cp config/.env.example config/.env
```

Édite `config/.env` et renseigne les variables — voir la section [Configuration](#configuration) ci-dessous.

### 3. Lancer les services

```bash
docker-compose --env-file config/.env up -d
```

Les services démarrent dans cet ordre automatiquement :
`db` → `redis` → `minio` → `app-worker` → `app-api`

### 4. Accéder à l'application

| Service | URL |
|---|---|
| Application | `http://localhost:5005` |
| Console MinIO | `http://localhost:9001` |

---

## Configuration

Copie `config/.env.example` vers `config/.env` et renseigne les variables :

```env
# ── Base de données principale (admin) ────────────────────────────────
DB_USER=scrutivoire
DB_PWD=ton_mot_de_passe_fort
DB_NAME=scrutivoire_db
DB_HOST=db          # nom du service Docker — ne pas changer
DB_PORT=5432

# ── Utilisateur restreint pour l'agent LLM (SELECT uniquement) ────────
LLM_USER=llm_user
LLM_PWD=ton_mot_de_passe_llm

# ── Redis ──────────────────────────────────────────────────────────────
REDIS_HOST=redis    # nom du service Docker — ne pas changer
REDIS_PORT=6379

# ── Application ────────────────────────────────────────────────────────
SECRET_KEY=genere_une_cle_aleatoire_ici  

# ── MinIO / S3 ─────────────────────────────────────────────────────────
S3_ENDPOINT=http://minio:9000             # endpoint interne Docker
S3_ACCESS_KEY=ton_access_key
S3_SECRET_KEY=ton_secret_key
S3_PUBLIC_URL=http://TON_IP_PUBLIQUE:9000
# Sur AWS S3 : laisser S3_ENDPOINT vide et renseigner la région dans le code

# ── Providers LLM (au moins un requis) ────────────────────────────────
GROQ_KEY=gsk_...          # https://console.groq.com — gratuit
OPENAI_KEY=sk-...         # optionnel
CEREBRAS_KEY=...          # optionnel
OLLAMA_URL=http://host.docker.internal:11434  # si Ollama tourne sur l'hôte

# ── Variables calculées automatiquement — NE PAS MODIFIER ─────────────
DB_URI=postgresql://${DB_USER}:${DB_PWD}@${DB_HOST}:${DB_PORT}/${DB_NAME}
LLM_DB_URI=postgresql://${LLM_USER}:${LLM_PWD}@${DB_HOST}:${DB_PORT}/${DB_NAME}
REDIS_DB_URI=redis://${REDIS_HOST}:${REDIS_PORT}
```

### Priorité des providers LLM

L'agent utilise les providers dans cet ordre de priorité (configurable si cle API disponible) :

| Priorité | Provider | Modèle | Usage |
|----------|---|---|---|
| 1        | OpenAI | gpt-4o-mini | Fallback |
| 2        | Groq | llama-4-scout-17b | Requêtes principales |
| 3        | Cerebras | llama3.1-8b | Tâches rapides |
| 4        | Gemini | gemini-2.0-flash | Fallback longs textes |
| 5        | Ollama | qwen3:14b | Fallback local sans quota |

Si un provider échoue (quota, timeout, erreur), le suivant est tenté automatiquement.

---

## Déploiement en production (VPS)

### Prérequis VPS

- Ubuntu 22.04+ avec Docker installé
- Ports ouverts : `5005` (app), `9000` (MinIO API), `9001` (MinIO console)
- Optionnel : Nginx en reverse proxy pour HTTPS

### Déploiement

```bash
# Sur le VPS
git clone https://github.com/ton-user/scrutivoire.git
cd scrutivoire
cp config/.env.example config/.env
nano config/.env   # renseigner les variables

docker-compose --env-file config/.env up -d --build --remove-orphans

# Vérifier que tout tourne
docker-compose ps
docker-compose logs -f app-api
```

### Mettre à jour

```bash
git pull
docker rm -f $(docker ps -aq)
docker compose build
docker-compose --env-file config/.env up -d --build --remove-orphans
```

---

## Utilisation

### 1. Charger un rapport électoral

1. Connecte-toi en tant qu'**Admin**
2. Menu **Archives** → **Importer un document**
3. Sélectionne le PDF (ex: [EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf](./data/doc_example/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf))
4. Suis la progression en temps réel : identification → détection tableau → candidats → localités → base de données

### 2. Interroger les données

1. Depuis la vue **Utilisateur**, clique sur l'élection chargée
2. Pose des questions en français :

```
"Combien de sièges a remporté le RHDP ?"
"Top 10 des candidats par score dans la région AGNEBI Tiasa."   # (note l'erreur)
"Taux de participation par région — affiche un graphique en barres."
"Qui a gagné à Cocody ?"
```

### 3. Questions supportées

| Type | Exemples                                             |
|---|------------------------------------------------------|
| Agrégation | "Combien de sièges par parti ?"                      |
| Classement | "Top 10 candidats RHDP"                              |
| Graphique | "Histogramme des gagnants par parti"                 |
| Participation | "Taux de participation par région"                   |
| Entité floue | "Kouadio a gagné Dans quelle localité"               |

---

## Architecture détaillée

### Services Docker

| Service | Rôle                                                                                                       |
|---|------------------------------------------------------------------------------------------------------------|
| `app-api` | Serveur web Flask + SocketIO. Gère les requêtes HTTP, les WebSockets.                                      |
| `app-worker` | Worker asyncio. Traite l'extraction PDF en arrière-plan, publie la progression via Redis pub/sub. Gere le chat |
| `db` | PostgreSQL. Stocke les données électorales, les sessions de chat, les traces.                              |
| `redis` | Broker de messages entre l'API et le worker. Cache des sessions.                                           |
| `minio` | Stockage objet. Conserve les PDFs sources et les images de crops (preuves visuelles).                      |

### Flux d'ingestion

```
PDF uploadé
    │ - 1. Hash SHA-256 → source_documents
    ▼
Worker reçoit la tâche (Redis)
    │
    ├─ 2. Upload S3 (MinIO)
    ├─ 3. pdfplumber → extraction tabulaire
    ├─ 4. LLM colum_detector → mapping colonnes
    ├─ 5. Extraction et cropage des preuves
    └─ 6. INSERT batch PostgreSQL (50k lignes/batch)
    
API reçoit la progression (SocketIO → frontend)
```

### Flux de chat

```
Question utilisateur
    │
    ▼
LLM Router (OpenAI/Groq/Cerebras/Gemini/Ollama)
    │
    ├─ fuzzy_wuzzy → résolution entité → ID
    │       └─ si ambigu → CLARIFICATION → utilisateur
    │
    ├─ [injection schéma SQL]
    │
    ├─ execute_sql_query → PostgreSQL
    │       └─ validation SELECT, injection LIMIT
    │
    └─ Réponse JSON {intent, display, text, data, source}
            │
            ▼
        Frontend : TEXT / BAR / PIE / TABLE / OPTIONS + badges source
```

---

## Sécurité

- **SELECT uniquement** : toute requête SQL non-SELECT est bloquée côté Python avant exécution.
- **Utilisateur restreint** : l'agent LLM utilise `llm_user` avec droits SELECT uniquement sur le schéma public.
- **LIMIT automatique** : injection de `LIMIT 100` sur toutes les requêtes retournant plusieurs lignes (sauf agrégations pures).
- **Intégrité SHA-256** : chaque fichier source est hashé à l'import. Chaque heure le fichier est analysé. Toute modification ultérieure est détectable.
- **UUID v4** : aucune ressource n'est énumérable par un tiers.

---

## Commandes utiles

```bash
# Voir les logs en temps réel
docker compose logs -f app-api
docker compose logs -f app-worker

# Redémarrer un service
docker compose restart app-api

# Accéder à PostgreSQL
docker compose exec db psql -U ${DB_USER} -d ${DB_NAME}

# Vider et recréer la base (ATTENTION : supprime toutes les données)
docker compose down -v
docker compose up -d

# Rebuild après modification du code
docker compose build app-api app-worker
docker compose up -d app-api app-worker
```

---

## Limitations connues

- Le parser PDF est optimisé pour le format EDAN (CEI Côte d'Ivoire). Un PDF de structure très différente nécessite une adaptation.
- Le flux terrain (agents de terrain + validation humaine) est conçu mais pas encore implémenté.

---

## Licence

Projet développé dans le cadre d'un challenge technique. Usage éducatif et de démonstration.