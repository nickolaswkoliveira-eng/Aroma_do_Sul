"""Carrega, valida, resume ou remove a base de demonstração no banco configurado (DATABASE_URL).

Uso:
  py -3 scripts/demo_banco.py carregar --confirmar
  py -3 scripts/demo_banco.py validar
  py -3 scripts/demo_banco.py resumo
  py -3 scripts/demo_banco.py limpar --confirmar

Somente registros marcados como demonstração (tabela registros_demo) são criados ou removidos.
Nenhuma credencial é exibida.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from config import DATABASE_URL
from database.connection import SessionLocal, init_database
from services.demo_operacoes import (
    carregar_dados_demo, contar_registros_demo, limpar_dados_demo,
    registros_reais_por_tabela, validar_dados_demo,
)


def _print_table(counts: dict[str, int]) -> None:
    width = max((len(name) for name in counts), default=10)
    for name, count in counts.items():
        print(f"  {name.ljust(width)}  {count:>7}")
    print(f"  {'TOTAL'.ljust(width)}  {sum(counts.values()):>7}")


def _print_checks(checks: list[dict]) -> bool:
    for check in checks:
        print(f"  [{'OK' if check['ok'] else 'FALHOU'}] {check['verificacao']}: {check['detalhe']}")
    return all(check["ok"] for check in checks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("acao", choices=("carregar", "validar", "resumo", "limpar"))
    parser.add_argument("--confirmar", action="store_true", help="Obrigatório para carregar ou limpar.")
    arguments = parser.parse_args()

    url = make_url(DATABASE_URL)
    print(f"Banco: {url.drivername} em {url.host or url.database}")
    if arguments.acao in ("carregar", "limpar") and not arguments.confirmar:
        print("ERRO: informe --confirmar para executar esta ação.", file=sys.stderr)
        return 2
    started = time.perf_counter()
    try:
        init_database(demo=False)
        with SessionLocal() as session:
            if arguments.acao == "carregar":
                result = carregar_dados_demo(session)
                print("Dados gerados:", result["gerado"])
                print("Registros por tabela:")
                _print_table(result["por_tabela"])
                print("Validação de integridade:")
                ok = _print_checks(result["validacao"])
            elif arguments.acao == "validar":
                print("Validação de integridade:")
                ok = _print_checks(validar_dados_demo(session))
            elif arguments.acao == "resumo":
                print("Registros de demonstração por tabela:")
                _print_table(contar_registros_demo(session))
                print("Registros reais nas tabelas de negócio:", registros_reais_por_tabela(session) or "nenhum")
                ok = True
            else:
                result = limpar_dados_demo(session)
                print(f"Removidos {result['removidos']} registros de demonstração:")
                _print_table(result["por_tabela"])
                print("Registros de demonstração restantes:", sum(contar_registros_demo(session).values()))
                ok = True
    except (ValueError, SQLAlchemyError) as error:
        print(f"ERRO: {type(error).__name__}: {str(error)[:400]}", file=sys.stderr)
        return 1
    print(f"Concluído em {time.perf_counter() - started:.0f}s.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
