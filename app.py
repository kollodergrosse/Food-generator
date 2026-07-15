"""Flask web interface for the meal plan app."""
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from ai_client import AIClient
from db import init_db
from models import Household
from storage import load_household, load_plan, save_household, save_plan, set_shopping_list_checked
from weather import detect_location, get_daily_temperatures, reverse_geocode

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__)
init_db()


@app.route("/")
def index():
    household = load_household()
    plan = load_plan()
    return render_template("index.html", haushalt=household.to_dict(), plan=plan.to_dict() if plan else None)


@app.route("/api/haushalt", methods=["GET"])
def api_get_household():
    return jsonify(load_household().to_dict())


@app.route("/api/haushalt", methods=["POST"])
def api_save_household():
    data = request.get_json(force=True)
    household = Household.from_dict(data)
    if not household.profiles:
        return jsonify({"status": "fehler", "meldung": "Ein Haushalt braucht mindestens ein Profil."}), 400
    save_household(household)
    return jsonify({"status": "ok", "haushalt": household.to_dict()})


@app.route("/api/standort-erkennen", methods=["GET"])
def api_detect_location():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    location = reverse_geocode(lat, lon) if lat is not None and lon is not None else None
    if location is None:
        location = detect_location()
    if location is None:
        return jsonify({"status": "fehler", "meldung": "Standort konnte nicht automatisch ermittelt werden."}), 502
    return jsonify({"status": "ok", "ort": location})


@app.route("/api/plan", methods=["GET"])
def api_get_plan():
    plan = load_plan()
    return jsonify(plan.to_dict() if plan else None)


@app.route("/api/plan/einkaufsliste/<int:index>", methods=["POST"])
def api_check_shopping_list_item(index):
    data = request.get_json(force=True)
    checked = bool(data.get("abgehakt", False))
    plan = set_shopping_list_checked(index, checked)
    if plan is None:
        return jsonify({"status": "fehler", "meldung": "Kein Plan oder ungültige Position."}), 404
    return jsonify({"status": "ok", "einkaufsliste": [i.to_dict() for i in plan.shopping_list]})


@app.route("/api/plan/erstellen", methods=["POST"])
def api_create_plan():
    try:
        household = load_household()
        temperatures = get_daily_temperatures(household.location)
        ai = AIClient()
        plan = ai.create_meal_plan(household, temperatures)
        save_plan(plan)
        return jsonify({"status": "ok", "plan": plan.to_dict(), "temperaturen": temperatures})
    except Exception as exc:
        return jsonify({"status": "fehler", "meldung": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
