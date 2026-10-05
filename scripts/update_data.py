#!/usr/bin/env python3
"""Atualiza docs/data.json para o Radar de Milhas.

Milhas: API pessoal do Seats.aero Pro (variável de ambiente SEATS_AERO_KEY).
Ida e volta em dinheiro: Google Flights pelo plano grátis do SerpApi (variável SERPAPI_KEY).

Sem a chave de um serviço, a parte dele mantém os dados da última execução.
Com --parte milhas, só atualiza as milhas (não gasta buscas do SerpApi).
Com --sample, gera dados de exemplo para testar a página sem chave nenhuma.
Só usa a biblioteca padrão do Python; não há nada para instalar.
"""
import argparse
import datetime as dt
import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "docs" / "data.json"
SEATS_URL = "https://seats.aero/partnerapi/search"
SERPAPI_URL = "https://serpapi.com/search"
SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"


def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def dates_between(start, end):
    d, last, out = dt.date.fromisoformat(start), dt.date.fromisoformat(end), []
    while d <= last:
        out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "radar-de-milhas/1.0",
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from None


def warn(msg):
    # Formato que o GitHub Actions mostra como aviso no resumo da execução
    print(f"::warning::{msg}")


# ---------------------------------------------------------------- Milhas

def seats_search(key, origins, destinations, start, end):
    rows, cursor = [], None
    for _ in range(20):
        params = {
            "origin_airport": origins,
            "destination_airport": destinations,
            "start_date": start,
            "end_date": end,
            "take": 1000,
            "include_trips": "true",
        }
        if cursor is not None:
            params["cursor"] = cursor
            params["skip"] = len(rows)
        page = get_json(f"{SEATS_URL}?{urllib.parse.urlencode(params)}", {"Partner-Authorization": key})
        rows.extend(page.get("data") or [])
        if not page.get("hasMore"):
            break
        cursor = page.get("cursor")
    return rows


def fare_from(row, prefix, cabin):
    """Resume uma cabine (Y = econômica, J = executiva) de um resultado do Seats.aero."""
    if not row.get(f"{prefix}Available"):
        return None
    try:
        pts = int(float(row.get(f"{prefix}MileageCost") or 0))
    except ValueError:
        return None
    if pts <= 0:
        return None
    trips = [t for t in row.get("AvailabilityTrips") or [] if (t.get("Cabin") or "").lower() == cabin]
    trip = min(trips, key=lambda t: t.get("MileageCost") or 10**9) if trips else None
    # TotalTaxes vem em centavos; alguns programas não informam taxas
    tax = round(trip["TotalTaxes"] / 100, 2) if trip and trip.get("TotalTaxes") is not None else None
    if trip and trip.get("Stops") is not None:
        stops = trip["Stops"]
    else:
        stops = 0 if row.get(f"{prefix}Direct") else None
    return {
        "pts": pts,
        "tax": tax,
        "seats": row.get(f"{prefix}RemainingSeats") or None,
        "airlines": row.get(f"{prefix}Airlines") or "",
        "stops": stops,
        "flights": trip.get("FlightNumbers") if trip else None,
    }


def fetch_miles(cfg, key):
    origin = cfg["origin"]
    codes = [r["code"] for r in cfg["routes"]]
    windows = cfg["miles"]["windows"]
    out = {"ida": {c: [] for c in codes}, "volta": {c: [] for c in codes}}
    for direction, orig, dest in (("ida", origin, ",".join(codes)), ("volta", ",".join(codes), origin)):
        rows = seats_search(key, orig, dest, windows[direction]["start"], windows[direction]["end"])
        print(f"Seats.aero {direction}: {len(rows)} resultados")
        for row in rows:
            route = row.get("Route") or {}
            code = route.get("DestinationAirport") if direction == "ida" else route.get("OriginAirport")
            if code not in out[direction]:
                continue
            econ = fare_from(row, "Y", "economy")
            biz = fare_from(row, "J", "business")
            if not econ and not biz:
                continue
            out[direction][code].append({
                "date": row.get("Date"),
                "program": row.get("Source") or route.get("Source"),
                "econ": econ,
                "biz": biz,
                "seenAt": row.get("UpdatedAt"),
            })
    return {"updatedAt": iso(now()), "sample": False, **out}


# ------------------------------------------------- Ida e volta em dinheiro

def cheapest_by_via(result, vias):
    """Menor preço de ida e volta para cada conexão (pela escala da ida)."""
    best = {v: None for v in vias}
    for it in (result.get("best_flights") or []) + (result.get("other_flights") or []):
        price = it.get("price")
        if not isinstance(price, (int, float)):
            continue
        layovers = [l.get("id") for l in it.get("layovers") or []]
        airlines = sorted({f.get("airline") for f in it.get("flights") or [] if f.get("airline")})
        for v in vias:
            if v in layovers and (best[v] is None or price < best[v]["price"]):
                best[v] = {
                    "price": price,
                    "airlines": ", ".join(airlines),
                    "hoursOut": round((it.get("total_duration") or 0) / 60, 1),
                    "stops": len(layovers),
                }
    return best


def min_price(combo):
    prices = [v["price"] for v in combo["via"].values() if v]
    return min(prices) if prices else None


def mark_favorites(combos, n):
    ranked = sorted((c for c in combos if min_price(c) is not None), key=min_price)
    favs = {(c["out"], c["back"]) for c in ranked[:n]}
    for c in combos:
        c["fav"] = (c["out"], c["back"]) in favs


def build_combos(cfg, previous):
    rt = cfg["roundtrip"]
    vias = [v["code"] for v in rt["via"]]
    prev = {(c["out"], c["back"]): c for c in (previous or {}).get("combos", [])}
    combos = []
    for out_date in dates_between(rt["windows"]["ida"]["start"], rt["windows"]["ida"]["end"]):
        for back_date in dates_between(rt["windows"]["volta"]["start"], rt["windows"]["volta"]["end"]):
            c = prev.get((out_date, back_date)) or {"out": out_date, "back": back_date, "checkedAt": None, "via": {}}
            c["via"] = {v: c.get("via", {}).get(v) for v in vias}
            combos.append(c)
    return combos


def fetch_roundtrip(cfg, key, previous):
    rt = cfg["roundtrip"]
    vias = [v["code"] for v in rt["via"]]
    combos = build_combos(cfg, previous)
    budget = rt["dailyFavorites"] + rt["dailyRotation"]

    # Favoritas (mais baratas até agora) todo dia; o resto em rodízio, as nunca verificadas primeiro
    favorites = sorted((c for c in combos if min_price(c) is not None), key=min_price)[: rt["dailyFavorites"]]
    rest = sorted((c for c in combos if c not in favorites), key=lambda c: c["checkedAt"] or "")
    picks = favorites + rest[: budget - len(favorites)]

    done = 0
    for c in picks:
        try:
            result = get_json(f"{SERPAPI_URL}?" + urllib.parse.urlencode({
                "engine": "google_flights",
                "departure_id": cfg["origin"],
                "arrival_id": rt["destination"],
                "outbound_date": c["out"],
                "return_date": c["back"],
                "type": 1,
                "currency": "BRL",
                "hl": "pt",
                "gl": "br",
                "api_key": key,
            }))
        except Exception as e:
            warn(f"SerpApi {c['out']} → {c['back']}: {e}")
            continue
        c["via"] = cheapest_by_via(result, vias)
        c["checkedAt"] = iso(now())
        done += 1
    print(f"SerpApi: {done} de {len(picks)} buscas concluídas")
    mark_favorites(combos, rt["dailyFavorites"])
    return {"updatedAt": iso(now()), "sample": False, "searches": done, "combos": combos}


def fetch_serpapi_account(key):
    """Saldo de buscas do mês. Esta consulta não gasta buscas."""
    acc = get_json(f"{SERPAPI_ACCOUNT_URL}?" + urllib.parse.urlencode({"api_key": key}))
    return {
        "searchesLeft": acc.get("total_searches_left"),
        "searchesPerMonth": acc.get("searches_per_month"),
        "checkedAt": iso(now()),
    }


# ---------------------------------------------------- Dados de exemplo

def sample_miles(cfg):
    rnd = random.Random(20261210)
    progs = list(cfg["programs"])
    t = now()
    out = {"ida": {}, "volta": {}}
    for direction in ("ida", "volta"):
        w = cfg["miles"]["windows"][direction]
        for r in cfg["routes"]:
            chosen = rnd.sample(progs, 3)
            opts = []
            for date in dates_between(w["start"], w["end"]):
                for p in chosen:
                    has_e, has_b = rnd.random() < 0.22, rnd.random() < 0.12
                    if not has_e and not has_b:
                        continue
                    mult = 3.2 if p in ("smiles", "azul") else 1
                    pts = round(r["cash"] * 9 * (0.8 + rnd.random() * 0.4) * mult / 500) * 500
                    airline = rnd.choice(["QR", "EK", "TK", "LH", "BA", "AF", "TP", "ET"])

                    def fare(points, factor):
                        return {"pts": points, "tax": round(rnd.uniform(30, 200) * factor), "seats": rnd.randint(1, 9),
                                "airlines": airline, "stops": rnd.choice([0, 0, 1]), "flights": None}

                    opts.append({
                        "date": date, "program": p,
                        "econ": fare(pts, 1) if has_e else None,
                        "biz": fare(round(pts * 2.2 / 500) * 500, 1.5) if has_b else None,
                        "seenAt": iso(t - dt.timedelta(hours=rnd.randint(1, 30))),
                    })
            out[direction][r["code"]] = opts
    return {"updatedAt": iso(t), "sample": True, **out}


def sample_roundtrip(cfg):
    rnd = random.Random(4242)
    rt = cfg["roundtrip"]
    combos = build_combos(cfg, None)
    t = now()
    names = {"DOH": "Qatar Airways", "FRA": "Lufthansa"}
    for c in combos:
        c["via"] = {
            v: {"price": round(rt["reference"] * rnd.uniform(0.78, 1.28) / 10) * 10,
                "airlines": names.get(v, "Várias"), "hoursOut": round(rnd.uniform(20, 25), 1), "stops": 1}
            for v in c["via"]
        }
        c["checkedAt"] = iso(t - dt.timedelta(days=rnd.randint(0, 10)))
    mark_favorites(combos, rt["dailyFavorites"])
    for c in combos:
        if c["fav"]:
            c["checkedAt"] = iso(t)
    return {"updatedAt": iso(t), "sample": True, "searches": 0, "combos": combos}


# ------------------------------------------------------------------ Main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="gera dados de exemplo, sem consultar as APIs")
    ap.add_argument("--parte", choices=["tudo", "milhas"], default=os.environ.get("PARTE") or "tudo",
                    help="o que atualizar (padrão: tudo)")
    args = ap.parse_args()

    cfg = json.loads(CONFIG_PATH.read_text("utf-8"))
    previous = json.loads(DATA_PATH.read_text("utf-8")) if DATA_PATH.exists() else {}
    seats_key = os.environ.get("SEATS_AERO_KEY", "").strip()
    serp_key = os.environ.get("SERPAPI_KEY", "").strip()
    data = {"generatedAt": iso(now()), "config": cfg, "serpapi": previous.get("serpapi")}

    if args.sample:
        data["miles"] = sample_miles(cfg)
        data["roundtrip"] = sample_roundtrip(cfg)
    else:
        if seats_key:
            try:
                data["miles"] = fetch_miles(cfg, seats_key)
            except Exception as e:
                warn(f"Seats.aero: {e}. Mantendo os dados anteriores.")
                data["miles"] = previous.get("miles")
        else:
            warn("SEATS_AERO_KEY não definida. Milhas mantêm os dados anteriores.")
            data["miles"] = previous.get("miles")

        prev_rt = previous.get("roundtrip")
        if args.parte == "milhas":
            print("Parte: só milhas. Ida e volta mantém os dados anteriores.")
            data["roundtrip"] = prev_rt
        elif serp_key:
            # Dados de exemplo não entram no rodízio real
            base = prev_rt if prev_rt and not prev_rt.get("sample") else None
            data["roundtrip"] = fetch_roundtrip(cfg, serp_key, base)
        else:
            warn("SERPAPI_KEY não definida. Ida e volta mantém os dados anteriores.")
            data["roundtrip"] = prev_rt

        if serp_key:
            try:
                data["serpapi"] = fetch_serpapi_account(serp_key)
            except Exception as e:
                warn(f"SerpApi (saldo): {e}")

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    print(f"Dados salvos em {DATA_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
