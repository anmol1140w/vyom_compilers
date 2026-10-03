"""Generate synthetic, non-private evaluation fixtures. Run from project root."""

import csv
import io
from pathlib import Path

from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont

from app.validation import gst_check_digit

DEST = Path(__file__).resolve().parent
PREFIX = "27AAPFU0939F1Z"
GSTIN = PREFIX + gst_check_digit(PREFIX)
COLUMNS = [
    "Invoice No",
    "Invoice Date",
    "Supplier Name",
    "Supplier GSTIN",
    "Buyer Name",
    "Place of Supply",
    "Description",
    "HSN",
    "Qty",
    "Unit Price",
    "Taxable Value",
    "GST Rate",
    "CGST Rate",
    "SGST Rate",
    "CGST",
    "SGST",
    "IGST",
    "Line Total",
    "Grand Total",
]
ROWS = [
    [
        "VYM-2026-001",
        "2026-01-15",
        "Sahyadri Office Supplies",
        GSTIN,
        "Demo Retail Private Ltd",
        "27-Maharashtra",
        "Office chairs",
        "9403",
        "2",
        "5000.00",
        "10000.00",
        "18",
        "9",
        "9",
        "900.00",
        "900.00",
        "0.00",
        "11800.00",
        "14160.00",
    ],
    [
        "VYM-2026-001",
        "2026-01-15",
        "Sahyadri Office Supplies",
        GSTIN,
        "Demo Retail Private Ltd",
        "27-Maharashtra",
        "Desk lamps",
        "9405",
        "4",
        "500.00",
        "2000.00",
        "18",
        "9",
        "9",
        "180.00",
        "180.00",
        "0.00",
        "2360.00",
        "14160.00",
    ],
    [
        "VYM-2026-002",
        "2026-01-16",
        "Sahyadri Office Supplies",
        GSTIN,
        "Example Studio",
        "27-Maharashtra",
        "Storage cabinet",
        "9403",
        "1",
        "8000.00",
        "8000.00",
        "18",
        "9",
        "9",
        "720.00",
        "720.00",
        "0.00",
        "9440.00",
        "9440.00",
    ],
]
LINES = [
    "TAX INVOICE - SYNTHETIC EVALUATION SAMPLE",
    "",
    "Supplier: Sahyadri Office Supplies",
    f"Supplier GSTIN: {GSTIN}",
    "Buyer: Demo Retail Private Ltd",
    "Invoice No: VYM-2026-001",
    "Invoice Date: 15/01/2026",
    "Place of Supply: 27-Maharashtra",
    "",
    "Description       HSN   Qty   Unit Price   Taxable Value   CGST     SGST     Total",
    "Office chairs     9403  2     5000.00      10000.00        900.00   900.00   11800.00",
    "Desk lamps        9405  4     500.00       2000.00         180.00   180.00   2360.00",
    "",
    "Taxable Value: 12000.00",
    "CGST: 1080.00",
    "SGST: 1080.00",
    "IGST: 0.00",
    "Grand Total: 14160.00",
    "",
    "This is a synthetic sample, not a real tax invoice.",
]


def make_pdf(lines=LINES):
    def escape(value):
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = (
        "BT /F1 11 Tf 35 655 Td 24 TL\n"
        + "\n".join(f"({escape(line)}) Tj T*" for line in lines)
        + "\nET"
    )
    content = content.encode("latin1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 850 700] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return output.getvalue()


def generate():
    for filename, rows in (
        ("sample-invoices.csv", ROWS),
        ("sample-mismatch.csv", [ROWS[0][:-1] + ["12000.00"]]),
    ):
        with (DEST / filename).open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(COLUMNS)
            writer.writerows(rows)
    book = Workbook()
    sheet = book.active
    sheet.title = "Invoices"
    sheet.append(COLUMNS)
    for row in ROWS:
        sheet.append(row)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    book.save(DEST / "sample-invoices.xlsx")
    (DEST / "sample-invoice.pdf").write_bytes(make_pdf())
    image = Image.new("RGB", (2200, 1350), "white")
    draw = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    font = (
        ImageFont.truetype(font_path, 30)
        if Path(font_path).is_file()
        else ImageFont.load_default(size=30)
    )
    for n, line in enumerate(LINES):
        draw.text((65, 60 + n * 60), line, fill="#17212b", font=font)
    image.save(DEST / "sample-invoice.png")


if __name__ == "__main__":
    generate()
    print(f"Generated synthetic samples in {DEST}")
