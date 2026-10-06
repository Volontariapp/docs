#!/usr/bin/env python3
"""Script d'exportation du backlog Notion vers CSV et JSON pour le rapport de coaching et le Gantt.

Interroge directement l'API Notion avec le NOTION_TOKEN de docs/.env.
Génère le CSV au format exact attendu par https://gant-notion.vercel.app/
avec résolution complète des dépendances (Bloqué par, Bloque) et des dates.
Extrait également le bilan du sprint N-1 pour les synthèses.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

NOTION_DB_ID = "2fd37561-a847-80a1-8c79-cebcaa8100b7"
NOTION_API_VERSION = "2022-06-28"


def get_notion_token() -> str:
    """Récupère le token Notion depuis l'environnement ou docs/.env."""
    token = os.environ.get("NOTION_TOKEN")
    if token:
        return token.strip()
    
    env_paths = [
        Path("docs/.env"),
        Path(__file__).resolve().parent.parent / ".env",
        Path(".env")
    ]
    for p in env_paths:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("NOTION_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
                    
    raise ValueError("NOTION_TOKEN introuvable dans l'environnement ou docs/.env")


def query_notion_db(token: str, db_id: str, filter_payload: dict = None) -> list[dict]:
    """Interroge la base de données Notion avec pagination complète."""
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    results = []
    has_more = True
    cursor = None

    while has_more:
        payload = {}
        if filter_payload:
            payload.update(filter_payload)
        if cursor:
            payload["start_cursor"] = cursor

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json"
            },
            data=data_bytes
        )

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results.extend(data.get("results", []))
                has_more = data.get("has_more", False)
                cursor = data.get("next_cursor")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Erreur API Notion ({e.code}) : {error_body}")

    return results


def build_title_map(pages: list[dict]) -> dict[str, str]:
    """Construit une table de correspondance id_page -> Titre de la tâche."""
    title_map = {}
    for p in pages:
        p_id = p.get("id")
        title_nodes = p.get("properties", {}).get("Nom", {}).get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_nodes).strip()
        if p_id:
            title_map[p_id] = title
    return title_map


def parse_task_properties(page: dict, title_map: dict[str, str] = None) -> dict:
    """Extrait et normalise les propriétés d'une tâche Notion en résolvant les dépendances."""
    props = page.get("properties", {})
    title_map = title_map or {}

    # Nom (titre)
    name_parts = [t.get("plain_text", "") for t in props.get("Nom", {}).get("title", [])]
    name = "".join(name_parts).strip()

    # Sprint
    sprint_prop = props.get("Sprint", {}).get("select")
    sprint = sprint_prop.get("name", "").strip() if sprint_prop else ""

    # Personnes
    persons = [p.get("name", "").strip() for p in props.get("Personne", {}).get("multi_select", [])]
    person_str = ", ".join(persons)

    # Date (start -> end ou start)
    date_prop = props.get("Date", {}).get("date")
    date_str = ""
    start_date = ""
    end_date = ""
    if date_prop:
        start_date = date_prop.get("start", "") or ""
        end_date = date_prop.get("end", "") or ""
        date_str = f"{start_date} -> {end_date}" if end_date else start_date

    # Charge
    charge_parts = [t.get("plain_text", "") for t in props.get("Charge", {}).get("rich_text", [])]
    charge = "".join(charge_parts).strip() or "1h"

    # Délais
    delais_parts = [t.get("plain_text", "") for t in props.get("Delais", {}).get("rich_text", [])]
    delais = "".join(delais_parts).strip() or charge

    # État / Status
    etat_obj = props.get("État", {}).get("status") or props.get("Status", {}).get("status")
    etat = etat_obj.get("name", "Todo").strip() if etat_obj else "Todo"

    # Description
    desc_parts = [t.get("plain_text", "") for t in props.get("Description", {}).get("rich_text", [])]
    description = "".join(desc_parts).strip()

    # Ressources
    ressources = [r.get("name", "").strip() for r in props.get("Ressources", {}).get("multi_select", [])]
    ressources_str = ", ".join(ressources)

    # EPIC
    epic_prop = props.get("EPIC", {}).get("select")
    epic = epic_prop.get("name", "").strip() if epic_prop else ""

    # Dépendances : Bloque & Bloqué par (résolution des IDs vers les noms)
    bloque_ids = [r.get("id") for r in props.get("Bloque", {}).get("relation", [])]
    bloque_par_ids = [r.get("id") for r in props.get("Bloqué par", {}).get("relation", [])]

    bloque_names = [title_map.get(rid, "") for rid in bloque_ids if rid in title_map and title_map.get(rid)]
    bloque_par_names = [title_map.get(rid, "") for rid in bloque_par_ids if rid in title_map and title_map.get(rid)]

    bloque_str = "; ".join(bloque_names)
    bloque_par_str = "; ".join(bloque_par_names)

    return {
        "id": page.get("id"),
        "name": name,
        "sprint": sprint,
        "person": person_str,
        "persons_list": persons,
        "date_str": date_str,
        "start_date": start_date,
        "end_date": end_date,
        "charge": charge,
        "delais": delais,
        "etat": etat,
        "description": description,
        "ressources": ressources_str,
        "epic": epic,
        "bloque": bloque_str,
        "bloque_par": bloque_par_str,
        "bloque_list": bloque_names,
        "bloque_par_list": bloque_par_names
    }


def export_sprint_backlog(sprint_num: int, output_csv: Path, token: str, all_pages: list[dict], title_map: dict[str, str]) -> list[dict]:
    """Exporte les tâches du sprint demandé au format CSV pour le Gantt avec toutes les dépendances."""
    print(f"Extraction Notion pour le Sprint {sprint_num}...")
    sprint_prefix = f"Sprint {sprint_num}"
    sprint_tasks = []

    for page in all_pages:
        task = parse_task_properties(page, title_map)
        if task["sprint"].startswith(sprint_prefix):
            sprint_tasks.append(task)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Colonnes conformes à https://gant-notion.vercel.app/
        writer.writerow([
            "Nom",
            "Date",
            "Charge = Delais",
            "Personne",
            "État",
            "Sprint",
            "Bloqué par",
            "Bloque",
            "Description",
            "Ressources"
        ])
        for t in sprint_tasks:
            writer.writerow([
                t["name"],
                t["date_str"],
                t["charge"],
                t["person"],
                t["etat"],
                t["sprint"],
                t["bloque_par"],
                t["bloque"],
                t["description"],
                t["ressources"]
            ])

    deps_count = sum(1 for t in sprint_tasks if t["bloque"] or t["bloque_par"])
    print(f"-> {len(sprint_tasks)} tâches exportées dans {output_csv} (dont {deps_count} avec dépendances actives)")
    return sprint_tasks


def export_completed_tasks_summary(prev_sprint_num: int, output_json: Path, token: str, all_pages: list[dict], title_map: dict[str, str]) -> dict:
    """Exporte le récapitulatif des tâches du sprint précédent pour les synthèses."""
    print(f"Extraction du bilan pour le Sprint précédent ({prev_sprint_num})...")
    sprint_prefix = f"Sprint {prev_sprint_num}"
    completed_tasks = []

    done_aliases = {"done", "terminé", "termine", "fait", "clos"}

    for page in all_pages:
        task = parse_task_properties(page, title_map)
        if task["sprint"].startswith(sprint_prefix):
            is_done = task["etat"].lower() in done_aliases
            task["is_done"] = is_done
            completed_tasks.append(task)

    # Grouper par personne
    by_person = {}
    for t in completed_tasks:
        persons = t["persons_list"] or ["Non assigné"]
        for p in persons:
            by_person.setdefault(p, []).append(t)

    summary = {
        "sprint": prev_sprint_num,
        "total_tasks": len(completed_tasks),
        "by_person": {}
    }

    for p, tasks in by_person.items():
        done_count = sum(1 for t in tasks if t["is_done"])
        summary["by_person"][p] = {
            "total": len(tasks),
            "done": done_count,
            "tasks": [
                {
                    "name": t["name"],
                    "date": t["date_str"],
                    "charge": t["charge"],
                    "description": t["description"],
                    "ressources": t["ressources"],
                    "epic": t["epic"],
                    "etat": t["etat"],
                    "is_done": t["is_done"],
                    "bloque_par": t["bloque_par"],
                    "bloque": t["bloque"]
                }
                for t in tasks
            ]
        }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"-> Bilan du Sprint {prev_sprint_num} exporté dans {output_json}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Export Notion Backlogs vers CSV Gantt et synthèse JSON.")
    parser.add_argument("--sprint", type=int, required=True, help="Numéro du sprint à exporter (ex: 8)")
    parser.add_argument("--out-csv", type=str, help="Chemin du fichier CSV de sortie")
    parser.add_argument("--prev-sprint", type=int, help="Numéro du sprint précédent à synthétiser (ex: 7)")
    parser.add_argument("--out-json", type=str, help="Chemin du fichier JSON de synthèse précédent")

    args = parser.parse_args()
    token = get_notion_token()

    print("Chargement complet de la base de données Notion...")
    all_pages = query_notion_db(token, NOTION_DB_ID)
    title_map = build_title_map(all_pages)
    print(f"-> {len(all_pages)} entrées Notion indexées pour les résolutions de dépendances.")

    csv_path = Path(args.out_csv) if args.out_csv else Path(f"docs/coaching/sprint_{args.sprint}_backlog.csv")
    export_sprint_backlog(args.sprint, csv_path, token, all_pages, title_map)

    prev_num = args.prev_sprint if args.prev_sprint is not None else (args.sprint - 1)
    if prev_num >= 0:
        json_path = Path(args.out_json) if args.out_json else Path(f"docs/coaching/sprint_{prev_num}_completed.json")
        export_completed_tasks_summary(prev_num, json_path, token, all_pages, title_map)


if __name__ == "__main__":
    main()
