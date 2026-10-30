"""Общие типы данных прототипа «Второе мнение». Контракт для всех модулей."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

@dataclass
class Sanction:
    article: str
    part: str
    label: str
    category: str
    negligent: bool = False
    punishment_types: list[str] = field(default_factory=list)
    imprisonment_min_years: Optional[float] = None
    imprisonment_max_years: Optional[float] = None
    fine_min_rub: Optional[float] = None
    fine_max_rub: Optional[float] = None
    life_or_death: bool = False
    notes: list[str] = field(default_factory=list)

@dataclass
class PersonInfo:
    gender: Optional[str] = None
    # True = утвердительно найдено; False = явно опровергнуто; None = не установлено.
    is_minor: Optional[bool] = None
    first_offense: Optional[bool] = None
    recidivism: Optional[str] = None      # нет|простой|опасный|особо опасный
    employment: Optional[str] = None
    health: Optional[str] = None

@dataclass
class CaseParameters:
    case_id: str
    article: Optional[str] = None
    part: Optional[str] = None
    crime_date: Optional[str] = None
    person: PersonInfo = field(default_factory=PersonInfo)
    mitigating: list[str] = field(default_factory=list)
    aggravating: list[str] = field(default_factory=list)
    punishment_type: Optional[str] = None
    punishment_years: Optional[float] = None
    punishment_months: Optional[float] = None
    fine_rub: Optional[float] = None
    probation: bool = False
    probation_years: Optional[float] = None     # испытательный срок (ч. 3 ст. 73 УК РФ)
    probation_months: Optional[float] = None
    stage: Optional[str] = None          # оконченное|приготовление|покушение
    release_grounds: list[str] = field(default_factory=list)
    masked_text: str = ""
    notes: list[str] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    rule_context: dict[str, Optional[bool]] = field(default_factory=dict)
    mentioned_articles: list[str] = field(default_factory=list)  # "статья~часть" всех упомянутых статей

@dataclass
class Violation:
    code: str
    level: str        # ошибка|предупреждение|информация
    message: str

@dataclass
class CheckResult:
    ok: Optional[bool] = True
    status: str = "partial"
    scope: str = "Демонстрационные правила; применимая редакция закона не проверена"
    trace: list[dict] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    limits: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

@dataclass
class SimilarCase:
    id: str
    article: str
    part: str
    punishment_type: str
    years: Optional[float] = None
    months: Optional[float] = None
    fine_rub: Optional[float] = None
    score: float = 0.0
    summary: str = ""
    source_kind: str = "synthetic"

@dataclass
class Conclusion:
    case_id: str
    annotation: str
    check: CheckResult = field(default_factory=CheckResult)
    similar: list[SimilarCase] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    deeper_analysis: list[str] = field(default_factory=list)
    generated_at: str = ""

def to_dict(obj: Any) -> dict:
    return asdict(obj)
