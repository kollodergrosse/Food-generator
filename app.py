"""Flask web interface for the meal plan app."""
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from ai_client import AIClient
from db import init_db
from models import CustomRecipe, Household
from storage import (
    add_shopping_list_item,
    delete_custom_recipe,
    delete_shopping_list_item,
    get_custom_recipe,
    load_custom_recipes,
    load_household,
    load_plan,
    save_custom_recipe,
    save_household,
    save_plan,
    set_shopping_list_checked,
    update_shopping_list_item,
)
from weather import detect_location, get_daily_temperatures, reverse_geocode

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__)
init_db()


@app.route("/")
def index():
    """Renders the single-page app shell, pre-filled with the current household, the latest meal
    plan (if any) and the custom-recipe database, so the frontend has its initial state without an
    extra round-trip through the JSON API."""
    household = load_household()
    plan = load_plan()
    eigene_rezepte = load_custom_recipes()
    return render_template(
        "index.html",
        haushalt=household.to_dict(),
        plan=plan.to_dict() if plan else None,
        eigene_rezepte=[r.to_dict() for r in eigene_rezepte],
    )


@app.route("/api/haushalt", methods=["GET"])
def api_get_household():
    """Returns the current household (profiles and visitors) as JSON."""
    return jsonify(load_household().to_dict())


@app.route("/api/haushalt", methods=["POST"])
def api_save_household():
    """Validates and persists the household submitted from the profile form.

    Requires at least one profile, and for every visitor a non-empty name plus a valid,
    non-inverted date range - all checked here (not just client-side) since the meal-plan
    creation later relies on this data being well-formed.
    """
    data = request.get_json(force=True)
    household = Household.from_dict(data)
    if not household.profiles:
        return jsonify({"status": "fehler", "meldung": "Ein Haushalt braucht mindestens ein Profil."}), 400
    for visitor in household.visitors:
        if not visitor.name.strip():
            return jsonify({"status": "fehler", "meldung": "Ein Besucher braucht einen Namen."}), 400
        try:
            start = date.fromisoformat(visitor.start_date)
            end = date.fromisoformat(visitor.end_date)
        except ValueError:
            return jsonify({
                "status": "fehler",
                "meldung": f"Besucher '{visitor.name}': Bitte Von- und Bis-Datum angeben.",
            }), 400
        if end < start:
            return jsonify({
                "status": "fehler",
                "meldung": f"Besucher '{visitor.name}': Das Bis-Datum darf nicht vor dem Von-Datum liegen.",
            }), 400
    save_household(household)
    return jsonify({"status": "ok", "haushalt": household.to_dict()})


@app.route("/api/standort-erkennen", methods=["GET"])
def api_detect_location():
    """Determines a location name for the "Standort erkennen" button in the household form.

    Prefers the device GPS coordinates passed as `lat`/`lon` query params (from the browser's
    Geolocation API) via reverse geocoding, since that reflects the actual device rather than the
    server; falls back to IP-based geolocation of the server itself when no coordinates were
    supplied or the browser lookup failed.
    """
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    location = reverse_geocode(lat, lon) if lat is not None and lon is not None else None
    if location is None:
        location = detect_location()
    if location is None:
        return jsonify({"status": "fehler", "meldung": "Standort konnte nicht automatisch ermittelt werden."}), 502
    return jsonify({"status": "ok", "ort": location})


@app.route("/api/eigene-rezepte", methods=["GET"])
def api_get_custom_recipes():
    """Returns every dish in the household's dish database as JSON."""
    return jsonify([r.to_dict() for r in load_custom_recipes()])


@app.route("/api/eigene-rezepte", methods=["POST"])
def api_save_custom_recipe():
    """Creates or (if `id` is set) overwrites a dish in the dish database.

    Nutrition values are never taken from the client - they're re-estimated by the AI from the
    submitted ingredients on every save. If that estimate fails (e.g. AI unreachable), saving must
    not fail because of it: an edit falls back to the dish's previously stored nutrition, while a
    brand new dish is saved with all-zero values.
    """
    data = request.get_json(force=True)
    recipe = CustomRecipe.from_dict(data)
    if not recipe.name.strip():
        return jsonify({"status": "fehler", "meldung": "Ein Rezept braucht einen Namen."}), 400
    try:
        recipe.nutrition = AIClient().estimate_nutrition(recipe.ingredients, recipe.servings)
    except Exception:
        # Schätzung fehlgeschlagen (z.B. KI nicht erreichbar) - Speichern soll daran nicht scheitern;
        # bei einer Bearbeitung bleibt dafür die zuvor geschätzte Nährwertangabe erhalten.
        existing = get_custom_recipe(recipe.id) if recipe.id else None
        if existing:
            recipe.nutrition = existing.nutrition
    recipe = save_custom_recipe(recipe)
    return jsonify({"status": "ok", "rezept": recipe.to_dict()})


@app.route("/api/eigene-rezepte/<recipe_id>", methods=["DELETE"])
def api_delete_custom_recipe(recipe_id):
    """Deletes a dish from the dish database by id."""
    if not delete_custom_recipe(recipe_id):
        return jsonify({"status": "fehler", "meldung": "Rezept nicht gefunden."}), 404
    return jsonify({"status": "ok"})


@app.route("/api/plan", methods=["GET"])
def api_get_plan():
    """Returns the most recently created meal plan, or `null` if none exists yet."""
    plan = load_plan()
    return jsonify(plan.to_dict() if plan else None)


@app.route("/api/plan/einkaufsliste/<int:index>", methods=["POST"])
def api_check_shopping_list_item(index):
    """Checks or unchecks a single shopping-list item, identified by its position in the list."""
    data = request.get_json(force=True)
    checked = bool(data.get("abgehakt", False))
    einkaufsliste = set_shopping_list_checked(index, checked)
    if einkaufsliste is None:
        return jsonify({"status": "fehler", "meldung": "Kein Plan oder ungültige Position."}), 404
    return jsonify({"status": "ok", "einkaufsliste": [i.to_dict() for i in einkaufsliste]})


@app.route("/api/plan/einkaufsliste", methods=["POST"])
def api_add_shopping_list_item():
    """Adds a manually entered shopping-list item that isn't tied to any recipe (e.g. household
    supplies). Creates an empty plan first if none exists yet, so the shopping list is usable even
    before the first AI-generated weekly plan."""
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "fehler", "meldung": "Ein Artikel braucht einen Namen."}), 400
    einkaufsliste = add_shopping_list_item(name, data.get("menge", ""), data.get("einheit", ""))
    return jsonify({"status": "ok", "einkaufsliste": [i.to_dict() for i in einkaufsliste]})


@app.route("/api/plan/einkaufsliste/<int:index>", methods=["PUT"])
def api_update_shopping_list_item(index):
    """Overwrites name/amount/unit of an existing shopping-list item, keeping its checked state."""
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "fehler", "meldung": "Ein Artikel braucht einen Namen."}), 400
    einkaufsliste = update_shopping_list_item(index, name, data.get("menge", ""), data.get("einheit", ""))
    if einkaufsliste is None:
        return jsonify({"status": "fehler", "meldung": "Kein Plan oder ungültige Position."}), 404
    return jsonify({"status": "ok", "einkaufsliste": [i.to_dict() for i in einkaufsliste]})


@app.route("/api/plan/einkaufsliste/<int:index>", methods=["DELETE"])
def api_delete_shopping_list_item(index):
    """Removes a single item from the shopping list, identified by its position in the list."""
    einkaufsliste = delete_shopping_list_item(index)
    if einkaufsliste is None:
        return jsonify({"status": "fehler", "meldung": "Kein Plan oder ungültige Position."}), 404
    return jsonify({"status": "ok", "einkaufsliste": [i.to_dict() for i in einkaufsliste]})


@app.route("/api/plan/erstellen", methods=["POST"])
def api_create_plan():
    """Creates a new weekly meal plan: fetches the weather forecast for the household's location,
    asks the AI to pick a dish per day/meal from the dish database based on that forecast, then
    persists and returns the resulting plan. Any failure along the way (e.g. no dishes in the
    database, unreachable weather/AI service) is reported as a JSON error instead of a stack trace,
    since this is a single user-triggered action rather than a chain of independently retryable
    steps."""
    try:
        household = load_household()
        temperatures = get_daily_temperatures(household.location)
        custom_recipes = load_custom_recipes()
        ai = AIClient()
        plan = ai.create_meal_plan(household, temperatures, custom_recipes)
        save_plan(plan)
        return jsonify({"status": "ok", "plan": plan.to_dict(), "temperaturen": temperatures})
    except Exception as exc:
        return jsonify({"status": "fehler", "meldung": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
