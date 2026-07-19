"""
Модели базы данных.

Справочники (Job, House, RelationshipStage, RelationshipAction) — это таблицы
с "константными" данными, которые мы сами заполняем один раз (сколько стоит
дом, какая зарплата у работы и т.д.). Их удобно менять без правки кода —
просто обновил строку в БД, и баланс игры поменялся.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Справочники
# ---------------------------------------------------------------------------


class Job(Base):
    """Справочник доступных работ."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    salary: Mapped[int] = mapped_column(Integer)
    cooldown_seconds: Mapped[int] = mapped_column(Integer)


class House(Base):
    """Справочник домов, доступных для покупки."""

    __tablename__ = "houses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[int] = mapped_column(Integer)
    max_children: Mapped[int] = mapped_column(Integer)
    # порядок для сортировки "от дешёвого к дорогому" в магазине
    order: Mapped[int] = mapped_column(Integer, unique=True)


class Car(Base):
    """Справочник машин, доступных для покупки."""

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[int] = mapped_column(Integer)
    order: Mapped[int] = mapped_column(Integer, unique=True)


class RelationshipStage(Base):
    """
    Справочник стадий отношений: Симпатия -> Отношения -> ... -> Брак.

    min_affection_points — сколько очков близости нужно накопить паре,
    чтобы попасть на эту стадию.
    """

    __tablename__ = "relationship_stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    order: Mapped[int] = mapped_column(Integer, unique=True)
    min_affection_points: Mapped[int] = mapped_column(Integer)
    # является ли эта стадия браком (нужно для проверок "доступен ли /have_child")
    is_marriage: Mapped[bool] = mapped_column(Boolean, default=False)


class RelationshipAction(Base):
    """
    Справочник действий, доступных парам (комплимент, погулять, поцелуй...).
    """

    __tablename__ = "relationship_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    # эмодзи действия отдельно от названия — используется в логе выполненного действия
    emoji: Mapped[str] = mapped_column(String(10))
    # глагольная фраза в прошедшем времени для лога, например "подарил(а) цветы"
    log_verb: Mapped[str] = mapped_column(String(150))
    # начиная с какой стадии (order из RelationshipStage) действие доступно
    min_stage_order: Mapped[int] = mapped_column(Integer)
    cooldown_seconds: Mapped[int] = mapped_column(Integer)
    affection_reward: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Основные сущности
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100))
    # чат, откуда пользователь последний раз писал боту — нужен для личных
    # уведомлений (например, напоминание про кредит)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    balance: Mapped[int] = mapped_column(Integer, default=0)
    loan_amount: Mapped[int] = mapped_column(Integer, default=0)  # текущий долг (уже с переплатой)
    loan_last_charge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    job_last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    casino_last_bet_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job | None"] = relationship(lazy="joined")


class RelationshipStatus(str, enum.Enum):
    PENDING = "pending"  # предложение отправлено, ждём подтверждения
    ACTIVE = "active"  # пара встречается
    MARRIED = "married"  # в браке
    DIVORCED = "divorced"  # расстались/развелись
    REJECTED = "rejected"  # предложение отклонили


class Relationship(Base):
    """
    Связь между двумя пользователями. Дом и дети привязаны сюда,
    а не к отдельному User, потому что это общее имущество пары.
    """

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(primary_key=True)

    user1_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user2_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    status: Mapped[RelationshipStatus] = mapped_column(
        Enum(RelationshipStatus, name="relationship_status"),
        default=RelationshipStatus.PENDING,
    )

    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey("relationship_stages.id"), nullable=True
    )
    affection_points: Mapped[int] = mapped_column(Integer, default=0)

    house_id: Mapped[int | None] = mapped_column(
        ForeignKey("houses.id"), nullable=True
    )
    car_id: Mapped[int | None] = mapped_column(
        ForeignKey("cars.id"), nullable=True
    )
    # Семейный бюджет — общий кошелёк пары, доступен только в браке.
    # Пополняется/тратится отдельно от личных балансов user1/user2.
    family_budget: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # когда пара стала official (ACTIVE) — пригодится для статистики "сколько дней вместе"
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # когда пара поженилась — для статистики "сколько дней в браке"
    married_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ID чата, где пара играет — нужен, чтобы бот мог САМ написать в чат
    # (например, объявить о рождении ребёнка), не дожидаясь чьей-то команды.
    # Записывается в момент принятия предложения отношений.
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_conception_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # была ли последняя попытка зачатия успешной — от этого зависит длительность
    # кулдауна до следующей попытки (см. children_service.py)
    last_conception_was_success: Mapped[bool] = mapped_column(Boolean, default=False)

    user1: Mapped["User"] = relationship(foreign_keys=[user1_id], lazy="joined")
    user2: Mapped["User"] = relationship(foreign_keys=[user2_id], lazy="joined")
    stage: Mapped["RelationshipStage | None"] = relationship(lazy="joined")
    house: Mapped["House | None"] = relationship(lazy="joined")
    car: Mapped["Car | None"] = relationship(lazy="joined")


class ActionLog(Base):
    """
    Лог выполненных действий пары. Используется для проверки кулдауна:
    берём последнюю запись по (relationship_id, action_code) и сравниваем
    время с cooldown_seconds из RelationshipAction.
    """

    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[int] = mapped_column(ForeignKey("relationships.id"))
    action_code: Mapped[str] = mapped_column(String(50))
    performed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


class ChildStatus(str, enum.Enum):
    PREGNANT = "pregnant"  # ещё не родился, идёт ожидание (3 дня)
    ALIVE = "alive"  # родился и живёт с родителями


class AgeStage(str, enum.Enum):
    BABY = "baby"  # 👶 Младенец
    TODDLER = "toddler"  # 🚼 Малыш
    CHILD = "child"  # 🧒 Ребёнок
    TEEN = "teen"  # 🧑 Подросток


class Toy(Base):
    """Справочник игрушек для детей — снижают скорость угасания настроения."""

    __tablename__ = "toys"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[int] = mapped_column(Integer)
    mood_decay_reduction: Mapped[float] = mapped_column()  # 0.10 = -10% к угасанию
    order: Mapped[int] = mapped_column(Integer, unique=True)


class ChildAction(Base):
    """
    Справочник действий с ребёнком. У каждой возрастной стадии (stage) свой набор.
    """

    __tablename__ = "child_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    stage: Mapped["AgeStage"] = mapped_column(Enum(AgeStage, name="child_action_stage"))
    affection_reward: Mapped[int] = mapped_column(Integer)
    mood_reward: Mapped[int] = mapped_column(Integer)
    # код черты характера, которая даёт бонус к этому действию (см. children_service.py); может быть пустым
    bonus_trait: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[int] = mapped_column(ForeignKey("relationships.id"))

    status: Mapped[ChildStatus] = mapped_column(
        Enum(ChildStatus, name="child_status"), default=ChildStatus.PREGNANT
    )

    # имя задаётся отдельно командой /name_child уже ПОСЛЕ рождения
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # пол и черты характера присваиваются случайно в момент родов, не зачатия
    gender: Mapped[Gender | None] = mapped_column(Enum(Gender, name="gender"), nullable=True)
    # черты характера — коды через запятую, например "cheerful,creative,curious"
    traits: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # купленные игрушки — коды через запятую, аналогично traits
    owned_toys: Mapped[str | None] = mapped_column(String(200), nullable=True)

    mood: Mapped[int] = mapped_column(Integer, default=100)
    age_stage: Mapped[AgeStage] = mapped_column(
        Enum(AgeStage, name="age_stage"), default=AgeStage.BABY
    )
    # когда последний раз с ребёнком выполняли действие — общий кулдаун
    # (любое действие блокирует любое следующее на 6 часов)
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # от какой точки отсчитывается угасание настроения (сбрасывается при любом действии)
    last_mood_decay_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conceived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    born_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    relationship_: Mapped["Relationship"] = relationship(lazy="joined")
