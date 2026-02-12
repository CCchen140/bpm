import json
import os
import re
import difflib
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class BirdTaxonomy:
    species_cn: str = ""
    species_la: str = ""
    order_cn: str = ""
    family_cn: str = ""
    genus_cn: str = ""
    order_la: str = ""
    family_la: str = ""
    genus_la: str = ""


class BirdBiologicalClassifier:
    _cache_loaded = False
    _taxonomy_by_name: dict[str, BirdTaxonomy] = {}
    _normalized_to_name: dict[str, str] = {}
    _latin_norm_to_name: dict[str, str] = {}
    _latin_bucket: dict[str, list[str]] = {}

    def classify(self, bird_name: str) -> Optional[BirdTaxonomy]:
        self._ensure_loaded()
        species = self._extract_species_name(bird_name)
        if not species:
            return None

        direct = self._taxonomy_by_name.get(species)
        if direct is not None:
            return direct

        norm = self._normalize_name(species)
        canonical = self._normalized_to_name.get(norm)
        if canonical:
            return self._taxonomy_by_name.get(canonical)
        return None

    def classify_by_latin_name(self, latin_name: str, min_ratio: float = 0.78) -> Optional[BirdTaxonomy]:
        self._ensure_loaded()
        q = self._normalize_latin_name(latin_name)
        if not q or len(q) < 3:
            return None
        try:
            if len([x for x in q.split(" ") if x]) < 2:
                return None
        except Exception:
            return None
        cn = self._latin_norm_to_name.get(q)
        if cn:
            return self._taxonomy_by_name.get(cn)

        candidates = None
        bucket_key = q[:2] if len(q) >= 2 else q[:1]
        if bucket_key:
            candidates = self._latin_bucket.get(bucket_key)
        if not candidates:
            candidates = list(self._latin_norm_to_name.keys())

        best_key = ""
        best_ratio = 0.0
        for k in candidates:
            if not k:
                continue
            if q in k or k in q:
                cn = self._latin_norm_to_name.get(k)
                return self._taxonomy_by_name.get(cn) if cn else None
            r = difflib.SequenceMatcher(a=q, b=k).ratio()
            if r > best_ratio:
                best_ratio = r
                best_key = k

        if best_key and best_ratio >= float(min_ratio):
            cn = self._latin_norm_to_name.get(best_key)
            if cn:
                return self._taxonomy_by_name.get(cn)
        return None

    def get_rank_names(self, bird_name: str) -> tuple[str, str, str]:
        t = self.classify(bird_name)
        if t is None:
            return "", "", ""
        return t.order_cn, t.family_cn, t.genus_cn

    @classmethod
    def _default_data_path(cls) -> str:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(project_root, "data", "bird_classification.json")

    @classmethod
    def _ensure_loaded(cls):
        if cls._cache_loaded:
            return
        cls._cache_loaded = True
        cls._taxonomy_by_name = {}
        cls._normalized_to_name = {}
        cls._latin_norm_to_name = {}
        cls._latin_bucket = {}

        data_path = cls._default_data_path()
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        if not isinstance(data, dict):
            return

        for name, v in data.items():
            if not isinstance(name, str) or not isinstance(v, dict):
                continue
            t = BirdTaxonomy(
                species_cn=str(name or ""),
                species_la=str(v.get("name_la") or ""),
                order_cn=str(v.get("order_cn") or ""),
                family_cn=str(v.get("family_cn") or ""),
                genus_cn=str(v.get("genus_cn") or ""),
                order_la=str(v.get("order_la") or ""),
                family_la=str(v.get("family_la") or ""),
                genus_la=str(v.get("genus_la") or ""),
            )
            cls._taxonomy_by_name[name] = t
            norm = cls._normalize_name(name)
            if norm:
                cls._normalized_to_name.setdefault(norm, name)
            latin_norm = cls._normalize_latin_name(v.get("name_la") or "")
            if latin_norm:
                cls._latin_norm_to_name.setdefault(latin_norm, name)
                key = latin_norm[:2] if len(latin_norm) >= 2 else latin_norm[:1]
                if key:
                    cls._latin_bucket.setdefault(key, []).append(latin_norm)

    @staticmethod
    def _extract_species_name(text: str) -> str:
        if text is None:
            return ""
        s = str(text).strip()
        if not s:
            return ""

        for sep in ("，", ",", "|", "｜", "；", ";"):
            if sep in s:
                parts = [p.strip() for p in s.split(sep) if p.strip()]
                if len(parts) >= 1:
                    return parts[-1]

        s = re.sub(r"^无法识别$", "", s).strip()
        return s

    @staticmethod
    def _normalize_name(name: str) -> str:
        if name is None:
            return ""
        s = str(name).strip().lower()
        if not s:
            return ""
        s = s.replace("（", "(").replace("）", ")")
        s = re.sub(r"\(.*?\)", "", s)
        s = re.sub(r"[\s·•\u3000\t\r\n]+", "", s)
        s = re.sub(r"[\"'“”‘’`]", "", s)
        return s

    @staticmethod
    def _normalize_latin_name(name: str) -> str:
        if name is None:
            return ""
        s = str(name).strip().lower()
        if not s:
            return ""
        s = re.sub(r"[\(\)\[\]\{\}]", " ", s)
        s = re.sub(r"[^a-z\s\.\-]+", " ", s)
        s = re.sub(r"[\s\.\-]+", " ", s).strip()
        return s


def classify_bird_taxonomy(bird_name: str) -> Optional[BirdTaxonomy]:
    return BirdBiologicalClassifier().classify(bird_name)
