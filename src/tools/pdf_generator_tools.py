from weasyprint import HTML


class PDFGeneratorTool:
    def to_pdf(self, html_content: str) -> bytes:
        """Génère un PDF à partir de contenu HTML."""
        pdf = HTML(string=html_content).write_pdf()
        return pdf
