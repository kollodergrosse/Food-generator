"""Füllt die Gerichte-Datenbank mit einigen Testgerichten (verschiedene Mahlzeiten, Temperaturen,
Diätformen und Allergene), damit sich der KI-Essensplan direkt ausprobieren lässt. Die Nährwerte
werden dabei - wie auch beim normalen Anlegen über die Oberfläche - automatisch von der KI aus den
Zutaten geschätzt, nicht hier hart hinterlegt."""
from pathlib import Path

from dotenv import load_dotenv

from ai_client import AIClient
from db import init_db
from models import CustomRecipe, Ingredient
from storage import save_custom_recipe

load_dotenv(Path(__file__).parent / ".env")

GERICHTE = [
    CustomRecipe(
        id="", name="Overnight Oats mit Beeren", servings=1,
        meal_types=["Frühstück"],
        ingredients=[
            Ingredient(name="Haferflocken", amount="50", unit="g"),
            Ingredient(name="Milch", amount="150", unit="ml"),
            Ingredient(name="Joghurt", amount="50", unit="g"),
            Ingredient(name="Beeren", amount="80", unit="g"),
            Ingredient(name="Honig", amount="1", unit="TL"),
        ],
        instructions=[
            "Haferflocken, Milch und Joghurt verrühren.",
            "Über Nacht abgedeckt im Kühlschrank ziehen lassen.",
            "Am Morgen mit Beeren und Honig servieren.",
        ],
    ),
    CustomRecipe(
        id="", name="Rührei mit Vollkornbrot", servings=1,
        meal_types=["Frühstück"],
        ingredients=[
            Ingredient(name="Eier", amount="2", unit="Stück"),
            Ingredient(name="Vollkornbrot", amount="2", unit="Scheiben"),
            Ingredient(name="Butter", amount="10", unit="g"),
            Ingredient(name="Schnittlauch", amount="1", unit="Prise"),
        ],
        instructions=[
            "Eier verquirlen und salzen.",
            "In Butter bei mittlerer Hitze zu Rührei stocken lassen.",
            "Mit Vollkornbrot und Schnittlauch servieren.",
        ],
    ),
    CustomRecipe(
        id="", name="Bircher Müsli mit Apfel", servings=1,
        meal_types=["Frühstück"],
        ingredients=[
            Ingredient(name="Haferflocken", amount="60", unit="g"),
            Ingredient(name="Apfel", amount="1", unit="Stück"),
            Ingredient(name="Joghurt", amount="100", unit="g"),
            Ingredient(name="Milch", amount="80", unit="ml"),
            Ingredient(name="Walnüsse", amount="15", unit="g"),
        ],
        instructions=[
            "Apfel raspeln, Walnüsse grob hacken.",
            "Alle Zutaten miteinander vermengen.",
            "Über Nacht im Kühlschrank ziehen lassen.",
        ],
    ),
    CustomRecipe(
        id="", name="Pfannkuchen mit Ahornsirup", servings=2,
        meal_types=["Frühstück"],
        ingredients=[
            Ingredient(name="Mehl", amount="200", unit="g"),
            Ingredient(name="Milch", amount="300", unit="ml"),
            Ingredient(name="Eier", amount="2", unit="Stück"),
            Ingredient(name="Butter", amount="20", unit="g"),
            Ingredient(name="Ahornsirup", amount="3", unit="EL"),
        ],
        instructions=[
            "Mehl, Milch und Eier zu einem glatten Teig verrühren.",
            "Portionsweise in Butter goldbraun ausbacken.",
            "Mit Ahornsirup servieren.",
        ],
    ),
    CustomRecipe(
        id="", name="Avocado-Toast mit Ei", servings=1,
        meal_types=["Frühstück"],
        ingredients=[
            Ingredient(name="Vollkornbrot", amount="2", unit="Scheiben"),
            Ingredient(name="Avocado", amount="1", unit="Stück"),
            Ingredient(name="Eier", amount="1", unit="Stück"),
            Ingredient(name="Zitrone", amount="0.5", unit="Stück"),
            Ingredient(name="Chiliflocken", amount="1", unit="Prise"),
        ],
        instructions=[
            "Brot toasten, Avocado zerdrücken und mit Zitrone abschmecken.",
            "Ei pochieren oder als Spiegelei braten.",
            "Brot mit Avocadocreme bestreichen und mit dem Ei belegen.",
        ],
    ),
    CustomRecipe(
        id="", name="Gazpacho", servings=2,
        meal_types=["Mittag", "Abend"],
        ingredients=[
            Ingredient(name="Tomaten", amount="500", unit="g"),
            Ingredient(name="Gurke", amount="1", unit="Stück"),
            Ingredient(name="Paprika", amount="1", unit="Stück"),
            Ingredient(name="Knoblauch", amount="1", unit="Zehe"),
            Ingredient(name="Olivenöl", amount="2", unit="EL"),
        ],
        instructions=[
            "Alle Zutaten grob würfeln.",
            "Im Mixer fein pürieren.",
            "Mindestens 1 Stunde kalt stellen und gekühlt servieren.",
        ],
    ),
    CustomRecipe(
        id="", name="Sommersalat mit Feta", servings=2,
        meal_types=["Mittag", "Abend"],
        ingredients=[
            Ingredient(name="Feta", amount="150", unit="g"),
            Ingredient(name="Gurke", amount="1", unit="Stück"),
            Ingredient(name="Tomaten", amount="200", unit="g"),
            Ingredient(name="Oliven", amount="50", unit="g"),
            Ingredient(name="Olivenöl", amount="2", unit="EL"),
        ],
        instructions=[
            "Gemüse würfeln, Feta zerbröckeln.",
            "Alles zusammen mit den Oliven vermengen.",
            "Mit Olivenöl beträufeln und servieren.",
        ],
    ),
    CustomRecipe(
        id="", name="Linsensuppe", servings=4,
        meal_types=["Mittag", "Abend"],
        ingredients=[
            Ingredient(name="Rote Linsen", amount="300", unit="g"),
            Ingredient(name="Karotten", amount="200", unit="g"),
            Ingredient(name="Zwiebel", amount="1", unit="Stück"),
            Ingredient(name="Gemüsebrühe", amount="1", unit="l"),
            Ingredient(name="Kreuzkümmel", amount="1", unit="TL"),
        ],
        instructions=[
            "Zwiebel und Karotten klein schneiden und anschwitzen.",
            "Linsen und Gemüsebrühe zugeben, aufkochen.",
            "Ca. 25 Minuten köcheln, bis die Linsen weich sind.",
            "Mit Kreuzkümmel abschmecken.",
        ],
    ),
    CustomRecipe(
        id="", name="Chili con Carne", servings=4,
        meal_types=["Mittag", "Abend"],
        ingredients=[
            Ingredient(name="Hackfleisch", amount="500", unit="g"),
            Ingredient(name="Kidneybohnen", amount="400", unit="g"),
            Ingredient(name="Mais", amount="200", unit="g"),
            Ingredient(name="Tomaten", amount="400", unit="g"),
            Ingredient(name="Chili", amount="1", unit="TL"),
            Ingredient(name="Zwiebel", amount="1", unit="Stück"),
        ],
        instructions=[
            "Zwiebel anbraten, Hackfleisch scharf anbraten.",
            "Tomaten, Bohnen und Mais zugeben.",
            "Mit Chili würzen und 20 Minuten köcheln lassen.",
        ],
    ),
    CustomRecipe(
        id="", name="Thai-Erdnuss-Curry", servings=2,
        meal_types=["Mittag", "Abend"],
        ingredients=[
            Ingredient(name="Kokosmilch", amount="400", unit="ml"),
            Ingredient(name="Erdnussbutter", amount="2", unit="EL"),
            Ingredient(name="Brokkoli", amount="200", unit="g"),
            Ingredient(name="Paprika", amount="1", unit="Stück"),
            Ingredient(name="Reis", amount="150", unit="g"),
            Ingredient(name="Currypaste", amount="1", unit="EL"),
        ],
        instructions=[
            "Gemüse in Streifen schneiden.",
            "Kokosmilch, Erdnussbutter und Currypaste verrühren und erhitzen.",
            "Gemüse zugeben und 10 Minuten köcheln.",
            "Mit gekochtem Reis servieren.",
        ],
    ),
    CustomRecipe(
        id="", name="Kürbissuppe", servings=4,
        meal_types=["Mittag", "Abend"],
        ingredients=[
            Ingredient(name="Kürbis", amount="800", unit="g"),
            Ingredient(name="Kartoffeln", amount="200", unit="g"),
            Ingredient(name="Zwiebel", amount="1", unit="Stück"),
            Ingredient(name="Gemüsebrühe", amount="800", unit="ml"),
            Ingredient(name="Sahne", amount="100", unit="ml"),
        ],
        instructions=[
            "Kürbis, Kartoffeln und Zwiebel würfeln.",
            "Mit Gemüsebrühe aufkochen und ca. 20 Minuten weich köcheln.",
            "Pürieren und mit Sahne verfeinern.",
        ],
    ),
    CustomRecipe(
        id="", name="Gegrillter Lachs mit Ofengemüse", servings=2,
        meal_types=["Abend"],
        ingredients=[
            Ingredient(name="Lachsfilet", amount="300", unit="g"),
            Ingredient(name="Zucchini", amount="1", unit="Stück"),
            Ingredient(name="Paprika", amount="1", unit="Stück"),
            Ingredient(name="Olivenöl", amount="2", unit="EL"),
            Ingredient(name="Zitrone", amount="1", unit="Stück"),
        ],
        instructions=[
            "Gemüse in Streifen schneiden, mit Olivenöl vermengen.",
            "Im Ofen bei 200 °C ca. 20 Minuten rösten.",
            "Lachs braten und mit Zitrone und dem Ofengemüse servieren.",
        ],
    ),
    CustomRecipe(
        id="", name="Caprese-Sandwich", servings=1,
        meal_types=["Mittag"],
        ingredients=[
            Ingredient(name="Ciabatta", amount="1", unit="Stück"),
            Ingredient(name="Mozzarella", amount="100", unit="g"),
            Ingredient(name="Tomaten", amount="1", unit="Stück"),
            Ingredient(name="Basilikum", amount="1", unit="Bund"),
            Ingredient(name="Olivenöl", amount="1", unit="EL"),
        ],
        instructions=[
            "Ciabatta aufschneiden.",
            "Mit Mozzarella, Tomatenscheiben und Basilikum belegen.",
            "Mit Olivenöl beträufeln.",
        ],
    ),
]


def main() -> None:
    """Seeds the dish database with the test dishes defined in GERICHTE, estimating nutrition for
    each via the AI (best-effort - a dish is still saved, with unestimated nutrition, if that call
    fails). Intended to be run once against a fresh/empty database, e.g. for local development."""
    init_db()
    ai = AIClient()
    fehlgeschlagene_schaetzungen = []
    for gericht in GERICHTE:
        try:
            gericht.nutrition = ai.estimate_nutrition(gericht.ingredients, gericht.servings)
        except Exception as exc:
            fehlgeschlagene_schaetzungen.append(gericht.name)
            print(f"  Nährwerte für '{gericht.name}' konnten nicht geschätzt werden: {exc}")
        save_custom_recipe(gericht)
        print(f"  gespeichert: {gericht.name}")

    print(f"{len(GERICHTE)} Testgerichte gespeichert.")
    if fehlgeschlagene_schaetzungen:
        # Die Gerichte sind trotzdem gespeichert (mit Nährwert 0) - das hier macht nur sichtbar,
        # dass die KI-Schätzung nicht für alle geklappt hat, statt das stillschweigend zu verschlucken.
        print(
            f"ACHTUNG: Für {len(fehlgeschlagene_schaetzungen)} von {len(GERICHTE)} Gerichten konnten "
            f"keine Nährwerte geschätzt werden (z.B. wegen fehlendem/ungültigem OPENAI_API_KEY): "
            f"{', '.join(fehlgeschlagene_schaetzungen)}"
        )


if __name__ == "__main__":
    main()
