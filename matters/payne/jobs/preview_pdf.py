import os, pypdfium2 as pdfium

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pdf_path = os.path.join(workdir, "report_focus_2026-06-24_not-found-and-quotes.pdf")
pdf = pdfium.PdfDocument(pdf_path)
print("pages:", len(pdf))
for i in range(len(pdf)):
    bmp = pdf[i].render(scale=1.6)
    out = os.path.join(workdir, "jobs", "preview_p%d.png" % (i+1))
    bmp.to_pil().save(out)
    print("wrote", out)
