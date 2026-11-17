"""Detector determinístico de prompt injection: a segunda barreira, que não depende da IA.

Por que existir além do `contem_instrucoes` que o modelo devolve:
- O modelo pode ser enganado justamente pelo texto que está analisando. Uma regra fixa não.
- O resultado é explicável: diz qual padrão bateu.
- Os dois juntos (OU) são medidos separadamente nas evals: quanto a IA pega sozinha,
  quanto a regra pega sozinha e quanto os dois pegam juntos.

Limite honesto: regex não entende intenção. Ataque bem disfarçado passa por aqui; por isso
a terceira barreira é estrutural (o extrator não grava nada e a conferência no banco rejeita
nota de outro cliente).
"""
from __future__ import annotations

import re
import unicodedata

# caracteres invisíveis usados para quebrar palavras-chave ("ig​nore")
INVISIVEIS = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)

PADROES = {
    "ignorar_regras": r"\b(ignore|ignora|desconsidere|esqueca|esqueça)\b.{0,40}\b(regras?|instruc\w*|orientac\w*|anteriores|previous|instructions|rules)\b",
    "ignore_en": r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|all)\b.{0,20}\b(instructions|rules|prompts?)\b",
    "fala_com_a_ia": r"\b(instruc\w* para (o|a) (sistema|ia|assistente|modelo)|to the (ai|assistant|model|system))\b",
    "mensagem_de_sistema": r"(\[|<|\b)(system|sistema|mensagem do sistema|system prompt|prompt do sistema)(\]|>|:)",
    "troca_de_papel": r"\b(voce agora e|você agora é|a partir de agora voce|you are now|act as|aja como)\b",
    "ordem_de_baixa": r"\b(marque|registre|considere|informe|classifique|aprove)\b.{0,40}\b(como pag\w*|pagas?|pagos?|quitad\w*|comprovante|aprovad\w*)\b.{0,40}\b(todas?|notas? \d+ a \d+|sem conferir|automaticamente)\b",
    "intervalo_de_notas": r"\bnotas?\s+\d{3,7}\s*(a|ate|até|to|-)\s*\d{3,7}\b.{0,40}\b(pag\w*|quitad\w*|paid)\b",
    "json_forjado": r"\{\s*\"(tipo|notas_citadas|valor_pago|contem_instrucoes)\"\s*:",
}
_RE = {k: re.compile(v, re.IGNORECASE | re.DOTALL) for k, v in PADROES.items()}


def normalizar(texto: str) -> str:
    """Tira caracteres invisíveis e acentos e junta espaços, para o disfarce não funcionar."""
    t = (texto or "").translate(INVISIVEIS)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t)


def detectar_instrucoes(texto: str) -> list[str]:
    """Lista dos padrões suspeitos encontrados (vazia = nada suspeito)."""
    t = normalizar(texto)
    return [nome for nome, rx in _RE.items() if rx.search(t)]
