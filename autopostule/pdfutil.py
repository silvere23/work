"""Outils communs pour produire des PDF (lettres, CV) avec fpdf2."""

from __future__ import annotations

from pathlib import Path

POLICES_UNICODE = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
)
REMPLACEMENTS_LATIN1 = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "œ": "oe",
                        "Œ": "OE", "€": "EUR", "\u00a0": " ", "\u202f": " ", "•": "-", "·": "-"}


class Document:
    """FPDF préconfiguré : police Unicode si disponible, sinon Helvetica avec translittération Latin-1."""

    def __init__(self, marges: tuple[float, float, float] = (22, 20, 22)):
        from fpdf import FPDF

        self.pdf = FPDF(format="A4")
        self.pdf.set_margins(*marges)
        self.pdf.set_auto_page_break(True, margin=18)
        self.pdf.add_page()
        self.unicode = False
        for normale, grasse in POLICES_UNICODE:
            if Path(normale).exists():
                self.pdf.add_font("Texte", "", normale)
                self.pdf.add_font("Texte", "B", grasse if Path(grasse).exists() else normale)
                self.police = "Texte"
                self.unicode = True
                break
        else:
            self.police = "Helvetica"

    @property
    def largeur(self) -> float:
        return self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def texte(self, valeur: str) -> str:
        if self.unicode:
            return valeur
        for avant, apres in REMPLACEMENTS_LATIN1.items():
            valeur = valeur.replace(avant, apres)
        return valeur.encode("latin-1", errors="replace").decode("latin-1")

    def police_(self, taille: float, gras: bool = False) -> None:
        self.pdf.set_font(self.police, "B" if gras else "", taille)

    def paragraphe(self, valeur: str, hauteur: float = 5.2, markdown: bool = False) -> None:
        self.pdf.multi_cell(self.largeur, hauteur, self.texte(valeur), new_x="LMARGIN", new_y="NEXT",
                            markdown=markdown)

    def enregistrer(self, chemin: Path) -> Path:
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.pdf.output(str(chemin))
        return chemin
