"""Frozen broad technical taxonomy for provisional zero-shot browsing topics.

Version 1 is defined independently of predicted assignments. Changing descriptions or edges
requires a new version so comparisons remain interpretable.
"""

from dataclasses import dataclass

TAXONOMY_VERSION = "apogee-technical-v1"


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    description: str
    prerequisites: tuple[str, ...] = ()


TOPICS = (
    Topic("programming", "Programming", "Programming languages, software design, code, debugging, and development tools."),
    Topic("algorithms", "Algorithms", "Data structures, graph traversal, computational algorithms, and complexity analysis.", ("programming",)),
    Topic("databases", "Databases", "Relational databases, SQL, data storage, transactions, indexing, and query processing."),
    Topic("machine-learning", "Machine learning", "Statistical learning, model training, neural networks, features, and evaluation."),
    Topic("information-retrieval", "Information retrieval", "Search systems, text indexing, relevance ranking, semantic embeddings, and vector retrieval.", ("databases",)),
    Topic("cloud-systems", "Cloud systems", "Cloud platforms, distributed infrastructure, deployment, and managed computing services."),
    Topic("web-development", "Web development", "Web applications, browsers, HTTP APIs, frontend interfaces, and backend services.", ("programming",)),
    Topic("security-privacy", "Security and privacy", "Authentication, authorization, data protection, privacy controls, and secure software."),
)
