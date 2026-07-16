"""
Script de premier démarrage : télécharge les modèles de traduction Argos
pour les paires de langues demandées.

Usage :
    python scripts/install_models.py              # fr↔en (défaut)
    python scripts/install_models.py fr en de     # fr + en + de
"""
import sys

import argostranslate.package
import argostranslate.translate


def install_pair(from_code: str, to_code: str) -> None:
    print(f"  {from_code} -> {to_code}... ", end="", flush=True)
    installed = {
        (p.from_code, p.to_code)
        for p in argostranslate.package.get_installed_packages()
    }
    if (from_code, to_code) in installed:
        print("déjà installé.")
        return

    pkgs = argostranslate.package.get_available_packages()
    pkg = next((p for p in pkgs if p.from_code == from_code and p.to_code == to_code), None)
    if pkg is None:
        print(f"ERREUR — paire introuvable dans le registre Argos.")
        return

    path = pkg.download()
    argostranslate.package.install_from_path(path)
    print("OK")


def main() -> None:
    langs = sys.argv[1:] if len(sys.argv) > 1 else ["fr", "en"]

    print("Mise à jour de l'index des packages Argos…")
    argostranslate.package.update_package_index()

    print(f"Installation des paires pour : {langs}")
    for i, src in enumerate(langs):
        for tgt in langs[i + 1:]:
            install_pair(src, tgt)
            install_pair(tgt, src)

    print("\nTerminé. Tu peux lancer l'application.")


if __name__ == "__main__":
    main()
