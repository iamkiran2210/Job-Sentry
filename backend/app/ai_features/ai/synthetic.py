"""Deterministic SYNTHETIC resumes with gold labels. For plumbing, smoke tests and CI only.
Metrics on synthetic data say nothing about real-world quality: label real (consented, anonymised) resumes
and pass them with --examples before trusting a model or an optimized prompt."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

FIRST = [
    "Aarav",
    "Maria",
    "Chen",
    "Fatima",
    "Lucas",
    "Priya",
    "Omar",
    "Sofia",
    "Kenji",
    "Elena",
    "Noah",
    "Amara",
]
LAST = [
    "Rao",
    "Garcia",
    "Wei",
    "Khan",
    "Silva",
    "Nair",
    "Haddad",
    "Rossi",
    "Tanaka",
    "Petrov",
    "Smith",
    "Okafor",
]
SKILLS = [
    "Python",
    "FastAPI",
    "PostgreSQL",
    "Docker",
    "Kubernetes",
    "Rust",
    "TypeScript",
    "Svelte",
    "Redis",
    "Celery",
    "Terraform",
    "SQL",
    "Go",
    "Linux",
    "Git",
]
COMPANIES = [
    "Acme Robotics",
    "Northwind Labs",
    "Globex Systems",
    "Initech Software",
    "Umbrella Analytics",
    "Hooli Cloud",
    "Stark Data",
    "Wayne Logistics",
]
TITLES = [
    "Backend Engineer",
    "Data Engineer",
    "Platform Engineer",
    "Software Developer",
    "ML Engineer",
    "DevOps Engineer",
]
UNIS = [
    "Example University",
    "Riverside College",
    "Northern Institute of Technology",
    "Lakeview University",
]
DEGREES = [
    ("BSc", "Computer Science"),
    ("MSc", "Data Science"),
    ("BTech", "Information Technology"),
]
CERTS = [
    "AWS Certified Developer",
    "Certified Kubernetes Administrator",
    "Google Professional Data Engineer",
    "HashiCorp Terraform Associate",
]
PROJECTS = [
    "Inventory Tracker",
    "Log Insight",
    "Route Planner",
    "Chat Relay",
    "Resume Parser",
]
CITIES = ["Springfield", "Rivertown", "Lakeside", "Hillcrest"]


@dataclass
class Sample:
    text: str
    gold: dict


def _gen(rng: random.Random, i: int) -> Sample:
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    email = f"{name.lower().replace(' ', '.')}{i}@example.com"
    phone = f"+1 415 555 {rng.randint(1000, 9999)}"
    skills = rng.sample(SKILLS, rng.randint(3, 7))
    jobs = []
    for _ in range(rng.randint(1, 3)):
        y = rng.randint(2012, 2022)
        jobs.append(
            (
                rng.choice(TITLES),
                rng.choice(COMPANIES),
                y,
                rng.choice([None, y + rng.randint(1, 3)]),
            )
        )
    deg, field = rng.choice(DEGREES)
    uni, grad = rng.choice(UNIS), rng.randint(2008, 2020)
    certs = rng.sample(CERTS, rng.randint(0, 2))
    projs = rng.sample(PROJECTS, rng.randint(1, 2))
    years = rng.randint(2, 9)
    alt = rng.random() < 0.4  # second layout so the heuristic isn't trivially perfect
    lines = [
        name,
        f"{email} | {phone} | {rng.choice(CITIES)}",
        "SUMMARY",
        f"Engineer with {years}+ years of {skills[0]} experience.",
        "SKILLS",
        ", ".join(skills),
        "EXPERIENCE",
    ]
    for t, c, y, e in jobs:
        end = str(e) if e else "Present"
        lines.append(
            f"{t} at {c} ({y} - {end})"
            if alt
            else f"{t}, {c}, {y}-03 to {end if e is None else str(e) + '-06'}"
        )
        lines.append("Delivered production services and mentored teammates.")
    lines += ["EDUCATION", f"{deg} {field}, {uni}, {grad}"]
    if certs:
        lines += ["CERTIFICATIONS", *certs]
    lines += [
        "PROJECTS",
        *[f"{p} - {rng.choice(skills)} service for internal use" for p in projs],
    ]
    gold = {
        "full_name": name,
        "email": email,
        "phone": phone,
        "skills": skills,
        "employment": [{"company": c, "title": t} for t, c, _, _ in jobs],
        "education": [uni],
        "certifications": certs,
        "projects": projs,
    }
    return Sample("\n".join(lines), gold)


def generate(n: int, seed: int = 7) -> list[Sample]:
    rng = random.Random(seed)
    return [_gen(rng, i) for i in range(n)]


def load_jsonl(path: str | Path) -> list[Sample]:
    """Each line: {"text": "...", "gold": {full_name, email, phone, skills[], employment[{company,title}], education[], certifications[], projects[]}}"""
    return [Sample(**json.loads(ln)) for ln in Path(path).read_text().splitlines() if ln.strip()]


def dump_jsonl(samples: list[Sample], path: str | Path) -> None:
    Path(path).write_text(
        "\n".join(json.dumps({"text": s.text, "gold": s.gold}) for s in samples) + "\n"
    )
