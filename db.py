"""Database module: SQLAlchemy engine and ORM models for the meal plan app."""
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "essensplan.db"

DATA_DIR.mkdir(exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class HouseholdORM(Base):
    __tablename__ = "haushalt"

    id = Column(Integer, primary_key=True)
    location = Column("ort", String, nullable=False, default="Berlin")

    profiles = relationship("ProfileORM", back_populates="household", cascade="all, delete-orphan")


class ProfileORM(Base):
    __tablename__ = "profil"

    id = Column(String, primary_key=True)
    household_id = Column("haushalt_id", Integer, ForeignKey("haushalt.id"), nullable=False)
    name = Column(String, nullable=False)
    dislikes = Column("abneigungen", JSON, default=list)
    allergies = Column("allergien", JSON, default=list)
    diet_type = Column("diaetform", String, default="keine")
    meals = Column("mahlzeiten", JSON, default=lambda: ["Frühstück", "Mittag", "Abend"])

    household = relationship("HouseholdORM", back_populates="profiles")


class MealPlanORM(Base):
    """An archived meal plan run; every plan creation adds a new row (history)."""
    __tablename__ = "essensplan"

    id = Column(Integer, primary_key=True)
    created_at = Column("erstellt_am", DateTime, default=datetime.utcnow, nullable=False)
    weekly_plan = Column("wochenplan", JSON, default=dict)
    shopping_list = Column("einkaufsliste", JSON, default=list)
    temperatures = Column("temperaturen", JSON, default=dict)

    recipes = relationship("RecipeORM", back_populates="meal_plan", cascade="all, delete-orphan")


class RecipeORM(Base):
    __tablename__ = "rezept"

    id = Column(Integer, primary_key=True)
    meal_plan_id = Column("essensplan_id", Integer, ForeignKey("essensplan.id"), nullable=False)
    name = Column(String, nullable=False)
    servings = Column("portionen", Integer, default=1)
    time_minutes = Column("zeit_minuten", Integer, default=0)
    ingredients = Column("zutaten", JSON, default=list)
    instructions = Column("zubereitung", JSON, default=list)

    meal_plan = relationship("MealPlanORM", back_populates="recipes")


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
                meals=["Frühstück", "Mittag", "Abend"],
            ))
        session.commit()


def init_db() -> None:
    inspector = inspect(engine)
    if "profil" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("profil")}
        if "vorlieben" in columns:
            _migrate_profile_table()
    Base.metadata.create_all(engine)
