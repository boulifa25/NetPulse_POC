-- Le cahier de NetPulse : les sites, leurs bornes, et chaque mesure prise par le gardien.
-- Exécuté par le gardien à chaque démarrage ("IF NOT EXISTS" : sans effet si tout existe déjà).

CREATE TABLE IF NOT EXISTS sites (
    id    SERIAL PRIMARY KEY,
    nom   TEXT NOT NULL UNIQUE,
    type  TEXT NOT NULL CHECK (type IN ('hotel', 'residence', 'magasin'))
);

CREATE TABLE IF NOT EXISTS bornes (
    id           SERIAL PRIMARY KEY,
    nom          TEXT NOT NULL UNIQUE,
    site_id      INTEGER NOT NULL REFERENCES sites (id),
    port         INTEGER NOT NULL,
    emplacement  TEXT            -- tel que la borne l'annonce en SNMP (sysLocation)
);

-- Une ligne par borne et par tour du gardien, qu'elle ait répondu ou non.
CREATE TABLE IF NOT EXISTS mesures (
    id                BIGSERIAL PRIMARY KEY,
    borne_id          INTEGER NOT NULL REFERENCES bornes (id),
    horodatage        TIMESTAMPTZ NOT NULL DEFAULT now(),
    en_ligne          BOOLEAN NOT NULL,
    clients           INTEGER,   -- NULL si la borne n'a pas répondu
    allumee_depuis_s  BIGINT,    -- sysUpTime converti en secondes ; NULL si pas de réponse
    erreur            TEXT       -- raison de l'échec ; NULL si la borne a répondu
);

-- Pour retrouver vite l'historique d'une borne, du plus récent au plus ancien.
CREATE INDEX IF NOT EXISTS mesures_par_borne ON mesures (borne_id, horodatage DESC);

-- Étape 5 : les alertes créées par les règles du gardien (voir collector/regles.py).
-- Une alerte est "en cours" tant que sa colonne fin est vide.
-- Une alerte concerne soit UNE borne (borne_id), soit un site ENTIER (site_id, étape 7).
CREATE TABLE IF NOT EXISTS alertes (
    id        BIGSERIAL PRIMARY KEY,
    borne_id  INTEGER REFERENCES bornes (id),
    site_id   INTEGER REFERENCES sites (id),
    type      TEXT NOT NULL,             -- panne, surcharge, anomalie, site_hors_service (contrainte plus bas)
    gravite   TEXT NOT NULL CHECK (gravite IN ('critique', 'avertissement')),
    message   TEXT NOT NULL,
    debut     TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin       TIMESTAMPTZ,               -- NULL tant que le problème dure
    regroupee_dans BIGINT REFERENCES alertes (id)  -- étape 7 : alerte de site qui l'a remplacée
);

-- Au plus UNE alerte en cours par borne et par type : pas de doublon, même si le gardien redémarre.
CREATE UNIQUE INDEX IF NOT EXISTS une_alerte_en_cours ON alertes (borne_id, type) WHERE fin IS NULL;

-- Mise à niveau des bases créées avant l'étape 7 (sans effet sur une base neuve).
ALTER TABLE alertes ALTER COLUMN borne_id DROP NOT NULL;
ALTER TABLE alertes ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites (id);
ALTER TABLE alertes ADD COLUMN IF NOT EXISTS regroupee_dans BIGINT REFERENCES alertes (id);

-- Étape 7 : au plus UNE alerte en cours par site et par type.
CREATE UNIQUE INDEX IF NOT EXISTS une_alerte_site_en_cours ON alertes (site_id, type)
    WHERE fin IS NULL AND site_id IS NOT NULL;

-- Contraintes supprimées puis recréées à chaque démarrage, pour que les bases créées lors des
-- étapes précédentes acceptent aussi les nouveaux types d'alerte.
ALTER TABLE alertes DROP CONSTRAINT IF EXISTS alertes_type_check;
ALTER TABLE alertes ADD CONSTRAINT alertes_type_check
    CHECK (type IN ('panne', 'surcharge', 'anomalie', 'site_hors_service'));
-- Une alerte vise une borne OU un site, jamais les deux, jamais aucun.
ALTER TABLE alertes DROP CONSTRAINT IF EXISTS alertes_cible_check;
ALTER TABLE alertes ADD CONSTRAINT alertes_cible_check
    CHECK ((borne_id IS NULL) <> (site_id IS NULL));

-- Étape 6 : les mesures inventées par generer_historique.py sont marquées, pour ne jamais
-- les confondre avec les vraies (elles servent seulement à l'apprentissage).
ALTER TABLE mesures ADD COLUMN IF NOT EXISTS simulee BOOLEAN NOT NULL DEFAULT false;

-- Étape 6 : ce que le gardien malin a appris (voir collector/normes.py).
-- Pour chaque borne et chaque heure de la journée : le nombre de clients habituel.
CREATE TABLE IF NOT EXISTS normes (
    borne_id   INTEGER NOT NULL REFERENCES bornes (id),
    heure      SMALLINT NOT NULL CHECK (heure BETWEEN 0 AND 23),   -- heure locale
    mediane    REAL NOT NULL,     -- nombre de clients "typique" à cette heure
    ecart      REAL NOT NULL,     -- variation habituelle autour de la médiane
    nb         INTEGER NOT NULL,  -- nombre de mesures ayant servi à l'apprendre
    appris_le  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (borne_id, heure)
);
