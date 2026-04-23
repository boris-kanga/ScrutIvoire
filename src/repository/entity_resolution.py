import re
from dataclasses import dataclass, asdict
from typing import Optional

from thefuzz import process

from kb_tools.tools import remove_accent_from_text


@dataclass
class BestEntity:
    id: int
    canonic_name: str
    score: int

    def to_dict(self):
        return asdict(self)


@dataclass
class EntityResolver:
    origin: str
    category: str
    found: bool
    ambiguous: bool = False
    suggestions: tuple[BestEntity, ...] = ()
    best: Optional[BestEntity] = None

    def __bool__(self):
        return self.found

    def __post_init__(self):
        if self.found and not isinstance(self.best, BestEntity):
            raise RuntimeError("Need best")
        if self.ambiguous and not self.suggestions:
            raise RuntimeError("Need suggestions")

    def __repr__(self):
        if not self.found:
            return "Not Found"
        if self.ambiguous:
            return "Match trouves: " + str(self.suggestions)
        return "Entité: " + str(self.best)

    def __str__(self):
        return self.__repr__()



MIN_SCORE = 60  # en dessous → not found
MAX_CANDIDATES = 10  # top N matches à analyser
MAX_SUGGESTIONS = 10  # max suggestions à montrer à l'utilisateur


class EntityResolution:
    def __init__(self, db):
        self.db = db
        self._cache: dict[str, list] = {}

        self._commune_reg = re.compile(r"\bc\s*o\s*m\s*m\s*u\s*n\s*e\s*s?\b",
                                       flags=re.I)
        self._sp_reg = re.compile(
            r"\b(s\s*|s\s*o\s*u\s*s\s*)[\\/\.\-\s]*(p|p\s*r\s*[eèéė]\s*f\s*(?:\.|e\s*c\s*t\s*u\s*r\s*e\s*s?)?)\b",
            flags=re.I)


    def extraction_ref_entities(self, value, type_="locality"):
        refs = []
        canonic_name = remove_accent_from_text(
            (" ".join(value.split())).upper())
        if type_ == "locality":
            canonic_name = re.sub(r"\d\(\)\.", "", canonic_name)
            parts = re.split(r"(?:,|\be\s*t\b)", canonic_name, flags=re.I)

            current = []
            got_commune = False
            got_sp = False
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                _com = self._commune_reg.search(part)
                _sp = self._sp_reg.search(part)

                if got_commune:
                    if not _sp:
                        current = []
                    got_commune = False

                if got_sp:
                    if not _com:
                        current = []
                    got_sp = False

                if _com:
                    s, e = _com.span()
                    before = part[:s].strip()
                    end = part[e:].strip()
                    if end.startswith("."):
                        end = end[1:]
                    if before:
                        current.append(before)
                    refs.extend([
                        {
                            "type": "COMMUNE",
                            "raw_name": x,
                            "canonic_name": x
                        }
                        for x in current
                    ])
                    if end:
                        current.append(end)
                        current = []
                    else:
                        if i == len(parts) - 1:
                            current = []
                        got_commune = True
                    continue

                if _sp:
                    s, e = _sp.span()
                    before = part[:s].strip()
                    end = part[e:].strip()
                    if end.startswith("."):
                        end = end[1:]
                    if before:
                        current.append(before)
                    refs.extend([
                        {
                            "type": "SOUS_PREFECTURE",
                            "raw_name": x,
                            "canonic_name": x
                        }
                        for x in current
                    ])
                    if end:
                        current.append(end)
                        current = []
                    else:
                        if i == len(parts) - 1:
                            current = []
                        got_sp = True

                    continue

                current.append(part)
            if current and not got_commune and not got_sp:
                refs.extend([
                    {
                        "type": "ZONE",
                        "raw_name": x,
                        "canonic_name": x
                    }
                    for x in current
                ])
        else:
            refs.extend([
                {
                    "type": type_.upper(),
                    "raw_name": value,
                    "canonic_name": canonic_name
                }
            ])

        return refs

    async def _fetch_candidates(self, category, election_id):
        category = category.upper()
        if category == "ZONE":
            category = ['COMMUNE', 'SOUS_PREFECTURE', 'ZONE', "REGION"]

        if not isinstance(category, list):
            category = [category]
        category = list(set(category))
        result = []

        for c in category:
            cache_key = f"{category}:{election_id}"
            if cache_key in self._cache:
                result.extend(self._cache[cache_key])
                continue

            res = await self.db.run_query(
                f"""
                SELECT * FROM ref_entities
                WHERE type=$1 AND election_id=$2
                """, params=(c, election_id)
            )
            tmp = []
            for r in res:
                if r["type"] in ("COMMUNE", "SOUS_PREFECTURE", "ZONE"):
                    tmp.append({
                        "name": r["canonic_name"],
                        "id": r["circonscription_id"],
                        "type": r["type"]
                    })
                elif r["type"] == "REGION":
                    tmp.append({
                        "name": r["canonic_name"],
                        "id": r["region_id"],
                        "type": r["type"]
                    })
                elif r["type"] == "CANDIDATE":
                    tmp.append({
                        "name": r["canonic_name"],
                        "id": r["candidate_id"],
                        "type": r["type"]

                    })
                elif r["type"] == "PARTY":
                    tmp.append({
                        "name": r["canonic_name"],
                        "id": r["party_id"],
                        "type": r["type"]
                    })
            self._cache[cache_key] = tmp
            result.extend(tmp)
        return result

    @staticmethod
    def _detect_cluster(entity: str, scored_matches: list) -> list:
        if len(scored_matches) <= 1:
            return scored_matches

        entity_len = len(entity)
        best_score = scored_matches[0][1]
        cluster = [scored_matches[0]]

        for i in range(1, len(scored_matches)):
            prev = scored_matches[i - 1][1]
            curr = scored_matches[i][1]

            if entity_len <= 5:
                gap_abs_threshold = 5
            elif entity_len <= 15:
                gap_abs_threshold = 8
            else:
                gap_abs_threshold = 12

            gap_abs = prev - curr
            gap_rel = gap_abs / prev
            drop_from_best = best_score - curr

            if gap_abs > gap_abs_threshold or gap_rel > 0.08 or drop_from_best > 15:
                break

            cluster.append(scored_matches[i])

        return cluster

    async def resolve(
            self,
            entity: str,
            category: str,
            election_id: str,
    ) -> EntityResolver:
        category = category.upper()
        candidates = await self._fetch_candidates(category, election_id)

        if not candidates:
            return EntityResolver(origin=entity, found=False, category=category)

        # Mapping name → id pour thefuzz
        if entity == "ZONE":
            choices = {
                c["name"] + " "+ c["type"]: c
                for c in candidates
            }
        else:
            choices = {c["name"]: c for c in candidates}

        # Top N matches via thefuzz
        raw_matches = process.extractBests(
            entity,
            choices.keys(),
            limit=MAX_CANDIDATES,
            score_cutoff=MIN_SCORE,
        )
        # raw_matches : [(name, score), ...]

        if not raw_matches:
            print("\tNot found")
            return EntityResolver(origin=entity, found=False, category=category)

        # Enrichir avec les IDs
        scored = [(name, score, choices[name]) for name, score in raw_matches]

        print("\tle match a donne:", scored)
        # scored : [(name, score, entity), ...] déjà trié par score DESC

        # Détecter le cluster
        cluster = self._detect_cluster(entity, scored)

        if len(cluster) == 0:
            return EntityResolver(origin=entity, found=False, category=category)

        if len(cluster) == 1:
            # Confiant
            name, score, entity = cluster[0]
            return EntityResolver(
                origin=entity,
                category=category,
                found=True,
                best=BestEntity(
                    id=entity["id"],
                    canonic_name=name + ("" if category != "ZONE" else " "+ entity["type"]),
                    score=score
                )
            )

        if len(cluster) > MAX_SUGGESTIONS:
            # Trop vague → not found
            return EntityResolver(origin=entity, found=False, category=category)

        # Ambigu — proposer le cluster
        suggestions = tuple(
            BestEntity(
                id=entity["id"],
                score=score,
                canonic_name=name + ("" if category != "ZONE" else " "+ entity["type"])
            )
            for name, score, entity in cluster
        )
        best = BestEntity(
            id=scored[0][2]["id"],
            score=scored[0][1],
            canonic_name=scored[0][2]["name"]
        )

        return EntityResolver(
                origin=entity,
                category=category,
                found=True,
                best=best,
                ambiguous=True,
                suggestions=suggestions
            )

