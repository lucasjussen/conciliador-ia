"""Langfuse opcional: se as chaves estiverem no .env, cada caso vira um trace.

Sem chaves, o agente roda normalmente, só sem rastreamento. Cada investigação é uma
sessão (session_id = thread_id), então a investigação e a aprovação humana, mesmo
feitas em horários diferentes, aparecem juntas no Langfuse.
"""
import os
from contextlib import contextmanager


def ativo() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


@contextmanager
def rastrear(thread_id: str, nome: str, tags: list[str]):
    """Uso: with rastrear(...) as callbacks: graph.invoke(..., config={"callbacks": callbacks})"""
    if not ativo():
        yield []
        return
    from langfuse import get_client, propagate_attributes
    from langfuse.langchain import CallbackHandler

    lf = get_client()
    with lf.start_as_current_observation(as_type="span", name=nome):
        with propagate_attributes(session_id=thread_id, tags=tags):
            yield [CallbackHandler()]
    lf.flush()


def fechar() -> None:
    if ativo():
        from langfuse import get_client
        get_client().flush()
