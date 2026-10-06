"""Appel à Claude (SDK officiel `anthropic`) pour la rédaction personnalisée."""

from __future__ import annotations

# Modèles pour lesquels le paramètre serveur `fallbacks` est disponible.
MODELES_AVEC_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class Redacteur:
    def __init__(self, modele: str = "claude-opus-5-5", client=None):
        self.modele = modele or "claude-opus-5-5"
        self.client = client

    def rediger(self, consignes: str, demande: str) -> str:
        """Retourne le texte produit ; lève RuntimeError en cas de refus ou de réponse vide."""
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        options = {}
        if self.modele in MODELES_AVEC_FALLBACK:
            options = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        reponse = self.client.beta.messages.create(
            model=self.modele,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=consignes,
            messages=[{"role": "user", "content": demande}],
            **options,
        )
        if reponse.stop_reason == "refusal":
            raise RuntimeError("le modèle a refusé la demande")
        texte = "".join(b.text for b in reponse.content if b.type == "text").strip()
        if not texte:
            raise RuntimeError(f"réponse vide (stop_reason={reponse.stop_reason})")
        return texte
