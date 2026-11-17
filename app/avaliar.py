"""Compara as divergências encontradas com o gabarito: precisão e recall por tipo.

precisão = das divergências que o sistema apontou, quantas eram reais
recall   = das divergências reais, quantas o sistema encontrou
"""
import json
from pathlib import Path

GABARITO = Path(__file__).resolve().parents[1] / "data" / "gabarito.json"


def avaliar(encontradas: list[dict], gabarito: list[dict]) -> dict:
    achou = {(d["tipo"], d["ref"]) for d in encontradas}
    real = {(d["tipo"], d["ref"]) for d in gabarito}
    tipos = sorted({t for t, _ in achou | real})
    linhas = []
    for t in tipos:
        a = {x for x in achou if x[0] == t}
        r = {x for x in real if x[0] == t}
        tp = len(a & r)
        linhas.append({"tipo": t, "reais": len(r), "apontadas": len(a), "acertos": tp,
                       "precisao": tp / len(a) if a else 1.0, "recall": tp / len(r) if r else 1.0,
                       "falsos_positivos": sorted(x[1] for x in a - r),
                       "nao_encontradas": sorted(x[1] for x in r - a)})
    tp = len(achou & real)
    return {"por_tipo": linhas,
            "geral": {"precisao": tp / len(achou) if achou else 1.0, "recall": tp / len(real) if real else 1.0,
                      "acertos": tp, "apontadas": len(achou), "reais": len(real)}}


def carregar_gabarito() -> list[dict] | None:
    if not GABARITO.exists():
        return None
    return json.loads(GABARITO.read_text(encoding="utf-8"))["divergencias"]


def imprimir(r: dict) -> None:
    print(f"\n{'tipo':28} {'reais':>5} {'apont.':>6} {'acertos':>7} {'precisão':>9} {'recall':>7}")
    for l in r["por_tipo"]:
        print(f"{l['tipo']:28} {l['reais']:>5} {l['apontadas']:>6} {l['acertos']:>7} "
              f"{l['precisao']:>9.0%} {l['recall']:>7.0%}")
    g = r["geral"]
    print(f"{'GERAL':28} {g['reais']:>5} {g['apontadas']:>6} {g['acertos']:>7} {g['precisao']:>9.0%} {g['recall']:>7.0%}")
    for l in r["por_tipo"]:
        if l["falsos_positivos"] or l["nao_encontradas"]:
            print(f"  {l['tipo']}: falsos positivos {l['falsos_positivos']}, não encontradas {l['nao_encontradas']}")
