# Rapport de Conception Technique : ScrutIvoire
**Projet :** Plateforme de Monitoring Électoral Indépendante  
**Auteur :** Boris, Ingénieur Statisticien & Développeur Python  
**Date :** Avril 2026  

---

## 1. Vision et Objectifs
**ScrutIvoire** est une solution technologique conçue pour garantir la transparence électorale en Côte d'Ivoire. Elle centralise et vérifie les procès-verbaux (PV) via deux flux : les archives officielles (PDF) et les remontées de terrain (Scans mobiles).

---

## 2. Architecture Logicielle & Stack
L'application repose sur une architecture découplée pour assurer la sécurité et la performance.

* **Backend :** Python (FastAPI/Flask).
* **Frontend :** Vanilla HTML/CSS/JS (Approche légère et mobile-first).
* **Base de Données :** PostgreSQL avec extension UUID.
* **Stockage :** MinIO (Compatible S3) pour les fichiers sources.

---

## 3. Choix de Conception Critiques

### 3.1. Gestion de l'Unicité Électorale (Non-chevauchement)
Un choix architectural majeur a été fait : **une seule élection peut être active à un instant T.**

**Justifications techniques et métier :**
* **Intégrité des données :** Élimine le risque qu'un Agent de Terrain envoie par erreur un PV des "Législatives" dans le flux de la "Présidentielle".
* **Simplification du Contexte :** Réduit la charge cognitive des agents et des validateurs qui se concentrent sur un seul scrutin national à la fois.
* **Verrouillage SQL :** Implémenté via un index partiel unique :
    ```sql
    CREATE UNIQUE INDEX IF NOT EXISTS only_one_active_election 
    ON elections (status) WHERE status = 'OPEN';
    ```

### 3.2. Identifiants UUID
Utilisation systématique des **UUID v4** au lieu des entiers auto-incrémentés pour :
* Empêcher l'énumération des ressources par des tiers (Sécurité).
* Faciliter la synchronisation des données provenant de sources distribuées (Agents terrain).

---

## 4. Modélisation de la Base de Données
Le schéma garantit une traçabilité totale (Audit Trail).

### Tables Clés
* **users :** Gestion RBAC (ADMIN, FIELD_AGENT, VALIDATOR).
* **source_documents :** Stockage des chemins S3 et des empreintes numériques (SHA-256).
* **staging_results :** Zone tampon pour les résultats extraits. Le champ `validated_by` est `NULL` par défaut, marquant l'attente de certification.
* **consolidated_results :** La "source de vérité" après validation humaine.

---

## 5. Workflow de Validation
Le système sépare strictement la saisie de la certification :
1.  **Ingestion :** Stockage du fichier et calcul du hash.
2.  **Extraction :** Insertion en mode `PENDING` dans la table de staging.
3.  **Certification :** Un validateur confirme la donnée, ce qui déclenche une transaction SQL vers la table consolidée et horodate l'action (`validated_at`).

---

## 6. Interface Utilisateur (UX/UI)
* **Identité :** Palette Orange (#FF8200) et Vert (#009B77).
* **Accès :** Page de connexion unique avec routage automatique basé sur le rôle détecté en base de données (suppression de la sélection manuelle du rôle pour une meilleure sécurité).
* **Admin Dashboard :** Vue "Cockpit" affichant l'élection active, la gestion des utilisateurs et le module d'importation d'archives.

---

## 7. Perspectives et Roadmap
* Intégration du moteur d'OCR pour l'automatisation de la lecture des PV.
* Développement de l'interface de capture mobile pour les agents.
* Mise en place du chat IA pour l'interrogation des résultats consolidés.