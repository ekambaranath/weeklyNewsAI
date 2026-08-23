"""Deterministic topic discovery and cross-run continuity.

Throughline asks its strong model to read ~60 raw headlines, cluster them, and
remember what previous weeks covered. Clustering and near-duplicate detection
are not judgement problems — they are similarity problems, and a model is the
wrong tool. Doing them in code here means:

  * the editor is briefed with ~8 labelled clusters instead of 60 raw items,
  * source-level dedup (which Throughline's roadmap still lists as unfinished)
    falls out for free,
  * continuity is measured against stored centroids rather than recalled from a
    prose ledger.

Pure stdlib — no numpy, no sklearn, no model download.

**The rule this module obeys: similarity LABELS, it never DROPS.** A cluster
scoring above ``repeat_threshold`` is handed to the editor tagged REPEAT with
its prior-topic name attached; the editor still makes the call. Automatic
dropping is how you silently lose the week a long-running storyline finally
breaks.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from newsroom.config import CLUSTER, MEMORY_DIR
from newsroom.schemas import Cluster, Item

CENTROID_PATH: Path = MEMORY_DIR / "centroids.json"

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\+\.]{1,}")
_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "for", "to", "with",
    "is", "are", "was", "were", "be", "been", "as", "at", "by", "from", "that",
    "this", "it", "its", "has", "have", "had", "will", "can", "new", "says",
    "said", "about", "how", "why", "what", "you", "your", "we", "our", "more",
    "than", "into", "after", "over", "not", "no", "up", "out", "s", "t",
}

Vector = dict[str, float]


# Light suffix stripping. Not a real stemmer — just enough that "enforcement",
# "enforceable" and "enforcing" collapse to one term, which is the difference
# between clustering two reports of the same story and splitting them.
_SUFFIXES = ("ements", "ement", "ations", "ation", "ingly", "iness", "ables",
             "able", "ible", "ing", "ers", "er", "ies", "ied", "ies", "es",
             "ed", "ly", "s")


def stem(token: str) -> str:
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _TOKEN.findall(text.lower()):
        token = raw.strip(".-+")
        if len(token) <= 2 or token in _STOP:
            continue
        stemmed = stem(token)
        if stemmed not in _STOP and len(stemmed) > 2:
            tokens.append(stemmed)
    return tokens


def _tf_idf(docs: list[list[str]]) -> list[Vector]:
    n = len(docs) or 1
    df = Counter()
    for doc in docs:
        df.update(set(doc))
    vectors: list[Vector] = []
    for doc in docs:
        tf = Counter(doc)
        vec: Vector = {}
        for term, count in tf.items():
            idf = math.log((n + 1) / (df[term] + 1)) + 1.0
            vec[term] = (count / max(len(doc), 1)) * idf
        vectors.append(_normalise(vec))
    return vectors


def _normalise(vec: Vector) -> Vector:
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def cosine(a: Vector, b: Vector) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(term, 0.0) for term, w in a.items())


def centroid(vectors: list[Vector]) -> Vector:
    total: Vector = {}
    for vec in vectors:
        for term, weight in vec.items():
            total[term] = total.get(term, 0.0) + weight
    # Keep only the strongest terms: a centroid is a label, not an archive.
    trimmed = dict(sorted(total.items(), key=lambda kv: -kv[1])[:40])
    return _normalise(trimmed)


def _label(items: list[Item]) -> str:
    """A human-readable cluster name from the most shared salient terms."""
    counts = Counter()
    for item in items:
        counts.update(set(tokenize(item.title)))
    top = [term for term, _ in counts.most_common(4)]
    return " / ".join(top) if top else "untitled"


def build_clusters(items: list[Item]) -> list[Cluster]:
    """Single-link greedy agglomeration over title+snippet similarity."""
    if not items:
        return []

    docs = [tokenize(f"{i.title} {i.snippet}") for i in items]
    vectors = _tf_idf(docs)
    threshold = float(CLUSTER["similarity_threshold"])

    assigned: list[int] = [-1] * len(items)
    groups: list[list[int]] = []

    for idx in range(len(items)):
        if assigned[idx] != -1:
            continue
        group = [idx]
        assigned[idx] = len(groups)
        for other in range(idx + 1, len(items)):
            if assigned[other] != -1:
                continue
            if any(cosine(vectors[member], vectors[other]) >= threshold for member in group):
                assigned[other] = len(groups)
                group.append(other)
        groups.append(group)

    min_size = int(CLUSTER["min_cluster_size"])
    clusters: list[Cluster] = []
    singletons: list[int] = []

    for gi, group in enumerate(groups):
        members = [items[i] for i in group]
        # A lone item from a reputable source is still worth a look; a lone item
        # from an unverified one usually is not.
        if len(group) < min_size and not any(m.quality == "reputable" for m in members):
            singletons.extend(group)
            continue
        clusters.append(
            Cluster(
                cluster_id=f"c{gi:02d}",
                label=_label(members),
                items=members,
            )
        )

    # Rank by corroboration then source quality: a story three reputable outlets
    # covered independently outranks one nobody else picked up.
    clusters.sort(
        key=lambda c: (
            -sum(1 for i in c.items if i.quality == "reputable"),
            -len(c.items),
        )
    )
    return clusters


# ------------------------------------------------------------ cross-run memory


def load_centroids() -> list[dict]:
    if not CENTROID_PATH.is_file():
        return []
    try:
        return json.loads(CENTROID_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_centroids(records: list[dict], keep_runs: int = 8) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = records[-keep_runs * 8 :]
    CENTROID_PATH.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")


def cluster_vector(cluster: Cluster) -> Vector:
    docs = [tokenize(f"{i.title} {i.snippet}") for i in cluster.items]
    return centroid(_tf_idf(docs)) if docs else {}


def label_continuity(clusters: list[Cluster]) -> list[Cluster]:
    """Tag each cluster NEW / DEVELOPING / REPEAT against prior runs.

    Suggestion only. The editor confirms or overrides in the next tier.
    """
    prior = load_centroids()
    repeat_at = float(CLUSTER["repeat_threshold"])
    developing_at = float(CLUSTER["developing_threshold"])

    for cluster in clusters:
        vec = cluster_vector(cluster)
        best_score, best_topic = 0.0, ""
        for record in prior:
            score = cosine(vec, record.get("vector", {}))
            if score > best_score:
                best_score, best_topic = score, record.get("topic", "")
        cluster.prior_similarity = round(best_score, 3)
        cluster.prior_topic = best_topic
        if best_score >= repeat_at:
            cluster.suggested_status = "REPEAT"
        elif best_score >= developing_at:
            cluster.suggested_status = "DEVELOPING"
        else:
            cluster.suggested_status = "NEW"
    return clusters


def record_run(clusters: list[Cluster], topics: dict[str, str], run_date: str) -> None:
    """Append this run's centroids so the next run has something to compare to."""
    records = load_centroids()
    for cluster in clusters:
        records.append(
            {
                "run": run_date,
                "topic": topics.get(cluster.cluster_id, cluster.label),
                "vector": cluster_vector(cluster),
            }
        )
    save_centroids(records)
