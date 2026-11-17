"""Conexão com o Postgres e aplicação dos scripts SQL."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()  # lê o .env da pasta do projeto, se existir
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://conc:conc@127.0.0.1:5432/conciliador")
DB_DIR = Path(__file__).resolve().parents[1] / "db"


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def apply_sql(conn: psycopg.Connection, *files: str) -> None:
    """Executa os arquivos de db/ na ordem (schema recria as tabelas do zero)."""
    for f in files:
        conn.execute((DB_DIR / f).read_text(encoding="utf-8"))
    conn.commit()
