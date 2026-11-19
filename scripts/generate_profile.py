"""Genera las tarjetas editoriales del perfil con Python 3.11 y su biblioteca estándar."""

import argparse
import json
import os
import random
import re
import textwrap
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from xml.etree import ElementTree
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
PAPER, INK, BORDER = "#191917", "#F5F2E9", "#44423A"
CARD, MUTED = "#242320", "#BDB9AD"
BLUE, RED, OCHRE = "#94A5FF", "#FF727C", "#F4C467"
MONTHS = "ENE FEB MAR ABR MAY JUN JUL AGO SEP OCT NOV DIC".split()
LEVELS = {
    "NONE": "#32312C",
    "FIRST_QUARTILE": "#303C78",
    "SECOND_QUARTILE": "#4A59AE",
    "THIRD_QUARTILE": "#6376E8",
    "FOURTH_QUARTILE": BLUE,
}
QUERY = """
query ProfileCalendar($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount contributionLevel }
        }
      }
    }
  }
}
"""
STYLE = f"""
    text {{ fill: {INK}; font-family: Georgia, 'Times New Roman', serif; }}
    .mono, .small {{ font-family: 'Courier New', monospace; letter-spacing: 1.3px; }}
    .mono {{ font-size: 12px; font-weight: bold; }}
    .small {{ font-size: 10px; }}
    .muted {{ fill: {MUTED}; }}
    .blue {{ fill: {BLUE}; }}
    .italic {{ font-style: italic; }}
    .rule {{ stroke: {BORDER}; }}
"""


@dataclass(frozen=True)
class Day:
    date: date
    count: int
    level: str


@dataclass(frozen=True)
class Stats:
    days: list[Day]
    total: int
    active: int
    current: int
    longest: int
    monthly: list[tuple[date, int]]


def fetch_calendar(username: str, token: str) -> list[Day]:
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": username}}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Editorial-Profile-Generator",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.load(response)

    if payload.get("errors"):
        issues = ", ".join(str(error.get("type", "ERROR")) for error in payload["errors"])
        raise ValueError(f"GitHub GraphQL devolvió errores ({issues}).")
    user = payload["data"]["user"]
    if user is None:
        raise ValueError(f"GitHub no encontró el usuario @{username}.")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = sorted(
        (
            Day(date.fromisoformat(row["date"]), row["contributionCount"], row["contributionLevel"])
            for week in calendar["weeks"]
            for row in week["contributionDays"]
        ),
        key=lambda day: day.date,
    )
    if not days or any(day.count < 0 or day.level not in LEVELS for day in days):
        raise ValueError("GitHub devolvió un calendario vacío o no válido.")
    if any((second.date - first.date).days != 1 for first, second in zip(days, days[1:])):
        raise ValueError("El calendario de GitHub contiene fechas duplicadas o ausentes.")
    if sum(day.count for day in days) != calendar["totalContributions"]:
        raise ValueError("El total del calendario no coincide con sus datos diarios.")
    return days


def calculate_stats(days: list[Day], today: date) -> Stats:
    monthly = defaultdict(int)
    total = active = run = longest = current = 0
    previous = None
    for day in days:
        total += day.count
        monthly[day.date.replace(day=1)] += day.count
        if previous is not None and day.date - previous != timedelta(days=1):
            run = 0
        run = run + 1 if day.count else 0
        active += bool(day.count)
        longest = max(longest, run)
        previous = day.date

    expected = today
    if not any(day.date == today and day.count for day in days):
        expected -= timedelta(days=1)
    for day in reversed(days):
        if day.date > expected:
            continue
        if day.date != expected or not day.count:
            break
        current += 1
        expected -= timedelta(days=1)

    return Stats(days, total, active, current, longest, sorted(monthly.items()))


def demo_calendar(today: date) -> list[Day]:
    rng = random.Random(721891)
    days = []
    for offset in range(364, -1, -1):
        stamp = today - timedelta(days=offset)
        count = rng.randint(1, 13) if rng.random() < (0.83 if stamp.weekday() < 5 else 0.43) else 0
        if offset < 8:
            count = 0 if offset == 0 else rng.randint(3, 9)
        level = list(LEVELS)[min(4, (count + 3) // 4)]
        days.append(Day(stamp, count, level))
    return days


def number(value: int) -> str:
    return f"{value:,}".replace(",", "\u202f")


def label(x: float, y: float, value: str, css: str = "", **attrs: str | int) -> str:
    properties = " ".join(f'{key.replace("_", "-")}="{val}"' for key, val in attrs.items())
    return f'<text x="{x}" y="{y}" class="{css}" {properties}>{escape(value)}</text>'


def rule(x1: float, y: float, x2: float) -> str:
    return f'<path d="M{x1} {y}H{x2}" class="rule" fill="none"/>'


def svg(height: int, title: str, description: str, body: str, extra_style: str = "") -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="860" height="{height}" viewBox="0 0 860 {height}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(title)}</title>
  <desc id="desc">{escape(description)}</desc>
  <style>{STYLE}{extra_style}</style>
  <rect x="1" y="1" width="858" height="{height - 2}" rx="16" fill="{PAPER}" stroke="{BORDER}" stroke-width="1.5"/>
  {body.strip()}
</svg>
"""


def wrap(value: str, width: int) -> list[str]:
    return textwrap.wrap(" ".join(value.split()), width=width, break_on_hyphens=False)


def fit_font(lines: list[str], size: int, width: int) -> int:
    # Estimación conservadora usando las fuentes de reserva del propio SVG.
    units = max(
        (sum(1.1 if character in "MW@%&" or ord(character) >= 0x2E80
             else 0.86 if character in "mw"
             else 0.76 if character.isupper()
             else 0.38 if character in " ilíj.,'«»"
             else 0.56 for character in line)
         for line in lines),
        default=1,
    )
    return min(size, int(width / units))


def build_header(config: dict, demo: bool) -> str:
    name, bio, username = (config[key] for key in ("name", "bio", "username"))
    # Los nombres cortos conservan la escala de cabecera. Los largos fluyen a nuevas líneas.
    name_lines = wrap(name, 17)
    size = fit_font(name_lines, 86, 526)
    leading = round(size * 0.95)
    bio_lines = wrap(bio, 52)
    bio_size = fit_font(bio_lines, 21, 516)
    name_y = 79 + size * 0.86
    bio_y = round(name_y + (len(name_lines) - 1) * leading + 44)
    height = max(280, bio_y + max(len(bio_lines) - 1, 0) * 26 + 36)

    title = "\n  ".join(
        label(42, round(name_y + i * leading), line, font_size=size, letter_spacing="-2")
        for i, line in enumerate(name_lines)
    )
    subtitle = "\n  ".join(
        label(46, bio_y + i * 26, line, "italic muted", font_size=bio_size)
        for i, line in enumerate(bio_lines)
    )
    motion = """
    @keyframes float {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-4px); }
    }
    .orbit { animation: float 6s ease-in-out infinite; }
    @media (prefers-reduced-motion: reduce) { .orbit { animation: none; } }
"""
    lines = "".join(
        f'<path d="M0 {n} H228" stroke="{BLUE}" stroke-width="1"/>'
        for n in range(-55, 190, 6)
    )
    return svg(height, name, f"{bio} GitHub: @{username}.", f"""
  {label(46, 40, "GITHUB / PERFIL", "mono")}
  {label(814, 40, ("MUESTRA / " if demo else "") + f"@{username.upper()}", "mono blue", text_anchor="end")}
  {rule(46, 56, 814)}
  {title}
  {subtitle}
  <g transform="translate(599 {max(91, (height - 120) // 2 + 19)})" aria-hidden="true">
    <defs><clipPath id="engraving"><circle cx="119" cy="69" r="65"/></clipPath></defs>
    <circle cx="119" cy="69" r="80" fill="none" stroke="{BORDER}" stroke-dasharray="2 4"/>
    <circle cx="119" cy="69" r="65" fill="#252A42"/>
    <g clip-path="url(#engraving)"><g transform="rotate(-25 119 69)">{lines}</g></g>
    <ellipse cx="119" cy="69" rx="101" ry="31" transform="rotate(-27 119 69)" fill="none" stroke="{INK}" stroke-width="1.2"/>
    <path d="M119 -19v9m0 158v9M31 69h9m158 0h9" stroke="{INK}"/>
    <g class="orbit"><circle cx="188" cy="26" r="9" fill="{RED}" stroke="{PAPER}" stroke-width="2"/></g>
    <circle cx="53" cy="109" r="5" fill="{OCHRE}" stroke="{PAPER}" stroke-width="1.5"/>
  </g>""", motion)


def date_label(value: date) -> str:
    return f"{value.day:02} {MONTHS[value.month - 1]} {value.year}"


def build_heatmap(stats: Stats, demo: bool) -> str:
    start, end = stats.days[0].date, stats.days[-1].date
    first_monday = start - timedelta(days=start.weekday())
    columns = (end - first_monday).days // 7 + 1
    step = min(14, 728 / columns)
    cell = round(step - 3, 2)
    labels, cells = [], []
    last_column = -2

    for day in stats.days:
        column, row = divmod((day.date - first_monday).days, 7)
        x = round(86 + column * step, 2)
        y = 113 + row * 15
        if (day.date == start or day.date.day == 1) and column - last_column >= 2 and x <= 790:
            labels.append(label(x, 104, MONTHS[day.date.month - 1], "small muted"))
            last_column = column
        cells.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="12" rx="2" fill="{LEVELS[day.level]}">'
            f'<title>{day.date}: {day.count} contribuciones</title></rect>'
        )

    weekdays = [label(46, 122 + row * 15, text, "small muted") for row, text in ((0, "LUN"), (2, "MIÉ"), (4, "VIE"), (6, "DOM"))]
    swatches = [
        f'<rect x="{694 + i * 16}" y="240" width="12" height="12" rx="2" fill="{color}"/>'
        for i, color in enumerate(LEVELS.values())
    ]
    period = f"{date_label(start)} – {date_label(end)}"
    return svg(274, "Mapa de actividad", f"{period}. {stats.active} días activos.{' Datos de muestra.' if demo else ''}", f"""
  <text x="45" y="59" font-size="40">Mapa de <tspan class="blue italic">actividad</tspan></text>
  {label(814, 53, "DATOS DE MUESTRA" if demo else "CALENDARIO DE GITHUB", "mono muted", text_anchor="end")}
  {rule(46, 79, 814)}
  {" ".join(labels)}
  {" ".join(weekdays)}
  {" ".join(cells)}
  {rule(46, 227, 814)}
  {label(46, 250, period, "small muted")}
  {label(685, 250, "MENOS", "small muted", text_anchor="end")}
  {" ".join(swatches)}
  {label(814, 250, "MÁS", "small muted", text_anchor="end")}
""")


def build_stats(stats: Stats, demo: bool) -> str:
    maximum = max(val for _, val in stats.monthly)
    step = min(64, 454 / len(stats.monthly))
    baseline = 260
    bars = []
    for index, (month, value) in enumerate(stats.monthly):
        x = round(89 + index * step, 2)
        height = round(99 * value / maximum, 2) if maximum else 0
        if height:
            color = BLUE if value == maximum else INK
            bars.append(
                f'<rect x="{x}" y="{baseline - height:.2f}" width="{step - 9:.2f}" height="{height}" rx="2" fill="{color}">'
                f'<title>{date_label(month)[3:]}: {value} contribuciones</title></rect>'
            )
        bars.append(label(round(x + (step - 9) / 2, 2), 280, MONTHS[month.month - 1], "small muted", text_anchor="middle"))

    metrics = (
        ("DÍAS ACTIVOS", f"{stats.active} / {len(stats.days)}"),
        ("RACHA ACTUAL", f"{stats.current} {'día' if stats.current == 1 else 'días'}"),
        ("MEJOR RACHA", f"{stats.longest} {'día' if stats.longest == 1 else 'días'}"),
    )
    sidebar = []
    for index, (caption, value) in enumerate(metrics):
        y = 55 + index * 90
        sidebar.extend((
            label(614, y, caption, "mono muted"),
            label(613, y + 39, value, "blue" if index == 0 else "", font_size=33),
        ))
        if index < 2:
            sidebar.append(rule(614, y + 59, 814))
    return svg(331, "Contribuciones en cifras",
               f"{stats.total} contribuciones, {stats.active} días activos, "
               f"racha actual de {stats.current} días y mejor racha de {stats.longest} días."
               f"{' Datos de muestra.' if demo else ''}", f"""
  {label(46, 41, "CONTRIBUCIONES / MUESTRA" if demo else "CONTRIBUCIONES / ÚLTIMO AÑO", "mono blue")}
  {label(42, 106, number(stats.total), font_size=64, letter_spacing="-2")}
  {label(46, 134, "Contribuciones por mes", "italic muted", font_size=19)}
  <path d="M86 161H548 M86 {baseline}H548 M583 31V302" class="rule" fill="none"/>
  {label(77, 164, number(maximum), "small muted", text_anchor="end")}
  {label(77, baseline + 3, "0", "small muted", text_anchor="end") if maximum else ""}
  {" ".join(bars)}
  {" ".join(sidebar)}
  {label(46, 309, "EL PRIMER Y EL ÚLTIMO MES PUEDEN SER PARCIALES", "small muted")}
""")


def build_highlights(cards: list[dict], demo: bool) -> str:
    blocks = []
    top = 91
    if not cards:
        return svg(151, "Destacados", "Sección editable.",
                   label(45, 59, "Destacados", font_size=40) +
                   rule(46, 78, 814) + label(46, 117, "Sin destacados", "italic muted", font_size=21))

    for start in range(0, len(cards), 3):
        row = cards[start:start + 3]
        gap = 14
        width = (768 - gap * (len(row) - 1)) / len(row)
        prepared = [
            (card, wrap(card["tag"].upper(), int((width - 40) / 9)),
             wrap(card["title"], int((width - 40) / 12)),
             wrap(card["description"], int((width - 40) / 7.5)))
            for card in row
        ]
        height = max(149, max(61 + len(tags) * 16 + len(titles) * 35 + len(desc) * 21
                              for _, tags, titles, desc in prepared))
        for index, (card, tags, titles, desc) in enumerate(prepared):
            x = round(46 + index * (width + gap), 2)
            color = card["color"]
            blocks.extend((
                f'<rect x="{x}" y="{top}" width="{width:.2f}" height="{height}" rx="11" fill="{CARD}" stroke="{BORDER}"/>',
                f'<rect x="{x+20}" y="{top+21}" width="19" height="4" rx="2" fill="{color}"/>',
            ))
            y = top + 45
            for line in tags:
                blocks.append(label(x + 20, y, line, "mono muted"))
                y += 16
            y += 19
            title_size = fit_font(titles, 29, int(width - 40))
            for line in titles:
                blocks.append(label(x + 19, y, line, font_size=title_size))
                y += 35
            y -= 8
            desc_size = fit_font(desc, 15, int(width - 40))
            for line in desc:
                blocks.append(label(x + 20, y, line, "muted", font_size=desc_size))
                y += 21
        top += height + gap

    return svg(top + 14, "Destacados", ". ".join(card["title"] for card in cards), f"""
  {label(45, 59, "Destacados", font_size=40)}
  {label(814, 53, "MUESTRA" if demo else "SELECCIÓN PERSONAL", "mono muted", text_anchor="end")}
  {rule(46, 78, 814)}
  {" ".join(blocks)}
""")


def read_config() -> dict:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    for key in ("username", "name", "bio"):
        value = config[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Completa el campo {key} en config.json.")
        config[key] = " ".join(value.split())
    for card in config["cards"]:
        for key in ("tag", "title", "description"):
            if not isinstance(card[key], str) or not card[key].strip():
                raise ValueError(f"Cada destacado requiere el campo {key}.")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", card["color"]):
            raise ValueError("Usa un color hexadecimal de seis dígitos en cada destacado.")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Genera una vista previa con datos de muestra.")
    demo = parser.parse_args().demo

    try:
        config = read_config()
        if demo:
            today = date(2026, 11, 18)
            days = demo_calendar(today)
        else:
            username = config["username"]
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}", username):
                raise ValueError("Configura un usuario de GitHub válido en config.json.")
            token = os.environ.get("GITHUB_TOKEN", "").strip()
            if not token:
                raise ValueError("Define GITHUB_TOKEN para consultar GitHub.")
            today = datetime.now(timezone.utc).date()
            days = fetch_calendar(username, token)

        stats = calculate_stats(days, today)
        images = {
            "header.svg": build_header(config, demo),
            "heatmap.svg": build_heatmap(stats, demo),
            "stats.svg": build_stats(stats, demo),
            "highlights.svg": build_highlights(config["cards"], demo),
        }
        for image in images.values():
            ElementTree.fromstring(image)

        assets = ROOT / "assets"
        assets.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=assets) as directory:
            for name, image in images.items():
                (Path(directory) / name).write_text(image, encoding="utf-8")
            for name in images:
                (Path(directory) / name).replace(assets / name)
        print(f"SVG actualizados en {assets}.")
    except (OSError, URLError, ValueError, TypeError, KeyError, ElementTree.ParseError) as error:
        parser.exit(1, f"Error al generar el perfil: {error}\n")


if __name__ == "__main__":
    main()
