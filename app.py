from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import os
from pathlib import Path
import re

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for

from utils.data_handler import (
    get_assignment_names,
    get_next_id,
    get_storage_status,
    load_data,
    load_seed_data,
    renumber_observations,
    save_data,
)


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
STYLES_DIR = BASE_DIR / "styles"
LOGO_PATH = ASSETS_DIR / "orascom-logo.png"
DATE_FORMAT = "%Y-%m-%d"
RATINGS = ["High", "Medium", "Low"]


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = getenv_str("FLASK_SECRET_KEY", "orascom-audit-dashboard")

    @app.get("/health")
    def healthcheck() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        return send_from_directory(ASSETS_DIR, filename)

    @app.get("/styles/<path:filename>")
    def styles(filename: str):
        return send_from_directory(STYLES_DIR, filename)

    @app.get("/")
    def dashboard():
        data = load_or_seed_data()
        storage = get_storage_status()
        assignments = get_assignment_names(data)
        selected_assignment = request.args.get("assignment") or (assignments[0] if assignments else None)
        if selected_assignment not in assignments:
            selected_assignment = assignments[0] if assignments else None

        current_observations = data.get(selected_assignment, []) if selected_assignment else []
        owner_options = sorted(
            {
                str(item.get("action_owner", "")).strip()
                for item in current_observations
                if str(item.get("action_owner", "")).strip()
            }
        )

        selected_ratings = request.args.getlist("rating") or RATINGS
        selected_owners = request.args.getlist("owner") or owner_options
        due_start = parse_date(request.args.get("due_start"))
        due_end = parse_date(request.args.get("due_end"))

        filtered_observations = filter_observations(
            observations=current_observations,
            ratings=selected_ratings,
            owners=selected_owners,
            due_start=due_start,
            due_end=due_end,
        )
        edit_observation_id = request.args.get("edit")
        edit_record = None
        if edit_observation_id and selected_assignment:
            edit_record = next(
                (item for item in current_observations if str(item.get("id")) == edit_observation_id),
                None,
            )

        total_observations = sum(len(items) for items in data.values())
        overdue_count = sum(
            1 for item in current_observations if (item_due := parse_date(item.get("due_date"))) and item_due < date.today()
        )
        severity_counts = Counter(item.get("rating", "Unknown") for item in filtered_observations)
        owner_counts = Counter(item.get("action_owner", "Unassigned") for item in filtered_observations)

        return render_template(
            "dashboard.html",
            assignments=assignments,
            current_assignment=selected_assignment,
            current_observations=current_observations,
            filtered_observations=filtered_observations,
            total_observations=total_observations,
            overdue_count=overdue_count,
            high_priority_count=sum(item.get("rating") == "High" for item in current_observations),
            selected_ratings=selected_ratings,
            owner_options=owner_options,
            selected_owners=selected_owners,
            due_start=due_start.isoformat() if due_start else "",
            due_end=due_end.isoformat() if due_end else "",
            metrics={
                "Total Observations": len(filtered_observations),
                "High Severity": severity_counts.get("High", 0),
                "Medium Severity": severity_counts.get("Medium", 0),
                "Low Severity": severity_counts.get("Low", 0),
            },
            severity_chart_data=[
                {"label": rating, "value": severity_counts.get(rating, 0), "color": rating_color(rating)}
                for rating in RATINGS
            ],
            owner_chart_data=[
                {"label": owner, "value": count}
                for owner, count in sorted(owner_counts.items(), key=lambda item: item[1], reverse=True)
            ],
            edit_record=edit_record,
            storage=storage,
            logo_exists=LOGO_PATH.exists(),
            today=date.today().isoformat(),
        )

    @app.post("/assignments")
    def create_assignment():
        data = load_or_seed_data()
        storage = get_storage_status()
        selected_assignment = request.form.get("selected_assignment", "")
        if storage["read_only"]:
            flash("This deployment is running in read-only mode. Configure persistent storage to add assignments.", "error")
            return redirect(url_for("dashboard", assignment=selected_assignment))

        raw_name = request.form.get("new_assignment", "")
        normalized_name = normalize_assignment_name(raw_name)
        if not raw_name.strip():
            flash("Please enter an assignment name.", "error")
        elif not normalized_name:
            flash("The assignment name needs at least one letter or number.", "error")
        elif normalized_name in data:
            flash("That assignment already exists.", "warning")
        else:
            data[normalized_name] = []
            save_data(data)
            flash(f"Assignment '{normalized_name}' created successfully.", "success")
            selected_assignment = normalized_name

        return redirect(url_for("dashboard", assignment=selected_assignment))

    @app.post("/assignments/delete")
    def delete_assignment():
        data = load_or_seed_data()
        storage = get_storage_status()
        selected_assignment = request.form.get("selected_assignment", "")
        if storage["read_only"]:
            flash("This deployment is running in read-only mode. Configure persistent storage to delete assignments.", "error")
            return redirect(url_for("dashboard", assignment=selected_assignment))

        assignment_to_delete = request.form.get("assignment_to_delete", "")
        if assignment_to_delete in data:
            data.pop(assignment_to_delete, None)
            save_data(data)
            flash(f"Assignment '{assignment_to_delete}' deleted successfully.", "success")
            remaining_assignments = get_assignment_names(data)
            selected_assignment = remaining_assignments[0] if remaining_assignments else ""
        else:
            flash("The selected assignment could not be found.", "warning")

        return redirect(url_for("dashboard", assignment=selected_assignment))

    @app.post("/observations")
    def create_observation():
        data = load_or_seed_data()
        storage = get_storage_status()
        current_assignment = request.form.get("assignment", "")
        if storage["read_only"]:
            flash("This deployment is running in read-only mode. Configure persistent storage to add observations.", "error")
            return redirect(url_for("dashboard", assignment=current_assignment))

        if current_assignment not in data:
            flash("Please create an assignment before adding an observation.", "error")
            return redirect(url_for("dashboard"))

        observation = request.form.get("observation", "").strip()
        agreed_action = request.form.get("agreed_action", "").strip()
        action_owner = request.form.get("action_owner", "").strip()
        rating = request.form.get("rating", "Low")
        due_date = request.form.get("due_date", "")

        if not all([observation, agreed_action, action_owner, due_date]):
            flash("Please complete all required fields before submitting.", "error")
            return redirect(url_for("dashboard", assignment=current_assignment))

        current_observations = data[current_assignment]
        current_observations.append(
            {
                "id": get_next_id(current_observations),
                "observation": observation,
                "rating": rating if rating in RATINGS else "Low",
                "agreed_action": agreed_action,
                "action_owner": action_owner,
                "due_date": due_date,
            }
        )
        data[current_assignment] = renumber_observations(current_observations)
        save_data(data)
        flash("Observation added successfully.", "success")
        return redirect(url_for("dashboard", assignment=current_assignment))

    @app.post("/observations/delete")
    def delete_observation():
        data = load_or_seed_data()
        storage = get_storage_status()
        current_assignment = request.form.get("assignment", "")
        if storage["read_only"]:
            flash("This deployment is running in read-only mode. Configure persistent storage to delete observations.", "error")
            return redirect(url_for("dashboard", assignment=current_assignment))

        observation_id = request.form.get("observation_id", "")
        observations = data.get(current_assignment, [])
        updated_observations = [item for item in observations if str(item.get("id")) != observation_id]
        if len(updated_observations) == len(observations):
            flash("The selected observation could not be found.", "warning")
        else:
            data[current_assignment] = renumber_observations(updated_observations)
            save_data(data)
            flash("Observation deleted successfully.", "success")
        return redirect(url_for("dashboard", assignment=current_assignment))

    @app.post("/observations/update")
    def update_observation():
        data = load_or_seed_data()
        storage = get_storage_status()
        current_assignment = request.form.get("assignment", "")
        if storage["read_only"]:
            flash("This deployment is running in read-only mode. Configure persistent storage to update observations.", "error")
            return redirect(url_for("dashboard", assignment=current_assignment))

        observation_id = request.form.get("observation_id", "")
        observations = data.get(current_assignment, [])
        record = next((item for item in observations if str(item.get("id")) == observation_id), None)
        if record is None:
            flash("The selected observation could not be found.", "warning")
            return redirect(url_for("dashboard", assignment=current_assignment))

        observation = request.form.get("observation", "").strip()
        agreed_action = request.form.get("agreed_action", "").strip()
        action_owner = request.form.get("action_owner", "").strip()
        rating = request.form.get("rating", "Low")
        due_date = request.form.get("due_date", "")

        if not all([observation, agreed_action, action_owner, due_date]):
            flash("Please complete all required fields before saving changes.", "error")
            return redirect(url_for("dashboard", assignment=current_assignment, edit=observation_id))

        record.update(
            {
                "observation": observation,
                "rating": rating if rating in RATINGS else "Low",
                "agreed_action": agreed_action,
                "action_owner": action_owner,
                "due_date": due_date,
            }
        )
        data[current_assignment] = renumber_observations(observations)
        save_data(data)
        flash("Observation updated successfully.", "success")
        return redirect(url_for("dashboard", assignment=current_assignment))

    return app


def load_or_seed_data() -> dict[str, list[dict[str, str | int]]]:
    data = load_data()
    storage = get_storage_status()
    if data:
        return data
    if storage["read_only"]:
        seed_data = load_seed_data()
        return seed_data or build_default_data()

    seed_data = load_seed_data()
    initial_data = seed_data or build_default_data()
    save_data(initial_data)
    return initial_data


def build_default_data() -> dict[str, list[dict[str, str | int]]]:
    return {
        "assignment_1": [
            {
                "id": 1,
                "observation": "Safety helmet not worn",
                "rating": "High",
                "agreed_action": "Provide training",
                "action_owner": "Safety Officer",
                "due_date": "2026-04-10",
            }
        ],
        "assignment_2": [
            {
                "id": 1,
                "observation": "Scaffold not secured",
                "rating": "Medium",
                "agreed_action": "Reinforce scaffold",
                "action_owner": "Site Engineer",
                "due_date": "2026-04-15",
            }
        ],
    }


def normalize_assignment_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        return None


def filter_observations(
    observations: list[dict[str, str | int]],
    ratings: list[str],
    owners: list[str],
    due_start: date | None,
    due_end: date | None,
) -> list[dict[str, str | int]]:
    filtered_items: list[dict[str, str | int]] = []
    for item in observations:
        item_rating = str(item.get("rating", ""))
        item_owner = str(item.get("action_owner", ""))
        item_due_date = parse_date(str(item.get("due_date", "")))
        if ratings and item_rating not in ratings:
            continue
        if owners and item_owner not in owners:
            continue
        if due_start and (item_due_date is None or item_due_date < due_start):
            continue
        if due_end and (item_due_date is None or item_due_date > due_end):
            continue
        filtered_items.append(item)
    return filtered_items


def rating_color(value: str) -> str:
    colors = {
        "High": "#DC3545",
        "Medium": "#FFC107",
        "Low": "#17A2B8",
    }
    return colors.get(value, "#6C757D")


def getenv_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
