"""Database module: SQLAlchemy engine and ORM models for the meal plan app."""
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from models import NUTRITION_FIELDS

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "essensplan.db"

DATA_DIR.mkdir(exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class HouseholdORM(Base):
    """The single household row (see storage.HOUSEHOLD_ID) together with its profiles and visitors."""
    __tablename__ = "haushalt"

    id = Column(Integer, primary_key=True)
    location = Column("ort", String, nullable=False, default="Berlin")

    profiles = relationship("ProfileORM", back_populates="household", cascade="all, delete-orphan")
    visitors = relationship("VisitorORM", back_populates="household", cascade="all, delete-orphan")


class ProfileORM(Base):
    """A permanent member of the household: preferences, dislikes, allergies, diet, meal participation."""
    __tablename__ = "profil"

    id = Column(String, primary_key=True)
    household_id = Column("haushalt_id", Integer, ForeignKey("haushalt.id"), nullable=False)
    name = Column(String, nullable=False)
    preferences = Column("praeferenzen", JSON, default=list)
    dislikes = Column("abneigungen", JSON, default=list)
    allergies = Column("allergien", JSON, default=list)
    diet_type = Column("diaetform", String, default="keine")
    meals = Column("mahlzeiten", JSON, default=lambda: ["Frühstück", "Mittag", "Abend"])

    household = relationship("HouseholdORM", back_populates="profiles")


class VisitorORM(Base):
    """A temporary guest of the household, valid only for a limited date range."""
    __tablename__ = "besucher"

    id = Column(String, primary_key=True)
    household_id = Column("haushalt_id", Integer, ForeignKey("haushalt.id"), nullable=False)
    name = Column(String, nullable=False)
    start_date = Column("von", String, nullable=False)
    end_date = Column("bis", String, nullable=False)
    intolerances = Column("unvertraeglichkeiten", JSON, default=list)
    diet_type = Column("diaetform", String, default="keine")
    meals = Column("mahlzeiten", JSON, default=lambda: ["Frühstück", "Mittag", "Abend"])

    household = relationship("HouseholdORM", back_populates="visitors")


class MealPlanORM(Base):
    """An archived meal plan run; every plan creation adds a new row (history)."""
    __tablename__ = "essensplan"

    id = Column(Integer, primary_key=True)
    created_at = Column("erstellt_am", DateTime, default=datetime.utcnow, nullable=False)
    weekly_plan = Column("wochenplan", JSON, default=dict)
    shopping_list = Column("einkaufsliste", JSON, default=list)
    temperatures = Column("temperaturen", JSON, default=dict)

    recipes = relationship("RecipeORM", back_populates="meal_plan", cascade="all, delete-orphan")


class NutritionColumnsMixin:
    """Nutrition value columns (per portion), shared via SQLAlchemy declarative mixin instead of
    being repeated in both RecipeORM and CustomRecipeORM. Column/attribute names must match
    models.NUTRITION_FIELDS."""
    calories = Column("kalorien", Float, default=0)
    protein = Column("eiweiss", Float, default=0)
    fat = Column("fett", Float, default=0)
    saturated_fat = Column("gesaettigte_fettsaeuren", Float, default=0)
    carbs = Column("kohlenhydrate", Float, default=0)
    sugar = Column("zucker", Float, default=0)
    salt = Column("salz", Float, default=0)


class RecipeORM(NutritionColumnsMixin, Base):
    """A recipe as it appeared in one archived weekly plan (MealPlanORM) - a scaled, point-in-time
    copy of the dish it was picked from, so later edits to the dish database don't rewrite history."""
    __tablename__ = "rezept"

    id = Column(Integer, primary_key=True)
    meal_plan_id = Column("essensplan_id", Integer, ForeignKey("essensplan.id"), nullable=False)
    name = Column(String, nullable=False)
    servings = Column("portionen", Integer, default=1)
    time_minutes = Column("zeit_minuten", Integer, default=0)
    ingredients = Column("zutaten", JSON, default=list)
    instructions = Column("zubereitung", JSON, default=list)
    youtube_link = Column("youtube_link", String, default="")

    meal_plan = relationship("MealPlanORM", back_populates="recipes")


class CustomRecipeORM(NutritionColumnsMixin, Base):
    """A pre-made dish in the household's dish database - the basis the AI selects from for the plan."""
    __tablename__ = "eigenes_rezept"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    servings = Column("portionen", Integer, default=1)
    ingredients = Column("zutaten", JSON, default=list)
    instructions = Column("zubereitung", JSON, default=list)
    meal_types = Column("mahlzeiten", JSON, default=list)
    youtube_link = Column("youtube_link", String, default="")
    tags = Column("tags", JSON, default=list)


def _migrate_profile_table() -> None:
    """Migrates the profil table from the old schema (column 'vorlieben') to 'abneigungen' + 'mahlzeiten'.

    create_all() only creates missing tables but doesn't alter existing columns - so this is done
    manually once: back up existing rows (without 'vorlieben', which is deliberately not carried over),
    recreate the table, reinsert the rows with sensible defaults for the new fields.
    """
    with engine.begin() as conn:
        old_rows = conn.execute(
            text("SELECT id, haushalt_id, name, allergien, diaetform FROM profil")
        ).mappings().all()
        conn.execute(text("DROP TABLE profil"))

    Base.metadata.create_all(engine)

    if not old_rows:
        return
    with SessionLocal() as session:
        for row in old_rows:
            session.add(ProfileORM(
                id=row["id"],
                household_id=row["haushalt_id"],
                name=row["name"],
                allergies=json.loads(row["allergien"]) if row["allergien"] else [],
                diet_type=row["diaetform"],
                dislikes=[],
                preferences=[],
                meals=["Frühstück", "Mittag", "Abend"],
            ))
        session.commit()


# Same fields as NutritionColumnsMixin above, in the ALTER-TABLE DDL shape _ensure_columns() needs
# for bringing an existing (pre-nutrition-tracking) database up to date.
NUTRITION_COLUMNS = {json_key: "FLOAT DEFAULT 0" for _, json_key in NUTRITION_FIELDS}


def _ensure_columns(table: str, column_defs: dict) -> None:
    """Adds any columns from column_defs that are missing on `table` via ALTER TABLE, since
    create_all() only creates missing tables but never alters the columns of an existing one."""
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    missing = {name: ddl for name, ddl in column_defs.items() if name not in existing}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    """Creates all tables on first run and brings an existing database up to the current schema.

    Called once at app startup. Must run before any other schema-changing helper here, since it
    performs the one-time 'vorlieben' -> 'abneigungen'/'mahlzeiten' migration before create_all()
    would otherwise leave the old table in place untouched.
    """
    inspector = inspect(engine)
    if "profil" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("profil")}
        if "vorlieben" in columns:
            _migrate_profile_table()
    Base.metadata.create_all(engine)
    _ensure_columns("profil", {"praeferenzen": "JSON DEFAULT '[]'"})
    _ensure_columns("rezept", {**NUTRITION_COLUMNS, "youtube_link": "TEXT DEFAULT ''"})
    _ensure_columns("eigenes_rezept", {
        **NUTRITION_COLUMNS,
        "mahlzeiten": "JSON DEFAULT '[]'",
        "youtube_link": "TEXT DEFAULT ''",
        "tags": "JSON DEFAULT '[]'",
    })
