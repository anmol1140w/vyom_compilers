"""Real browser smoke test against a running, disposable-data VYOM+ server.

Usage: uv run python tests/browser_smoke.py http://127.0.0.1:8931 /usr/bin/google-chrome
Do NOT target a workspace with valuable data: this script uploads/deletes synthetic records.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8931"
    executable = sys.argv[2] if len(sys.argv) > 2 else None
    errors = []
    artifacts = ROOT / "test-results"
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                errors.append(message.text)
                if message.type == "error" and "favicon" not in message.text
                else None
            ),
        )
        page.goto(base)
        expect(page.locator("#connection-text")).not_to_have_text("Connecting")
        expect(page.locator("#global-error")).to_be_hidden()
        expect(page.locator("#documents-empty")).to_be_visible()
        page.screenshot(
            path=str(artifacts / "desktop-empty.png"), full_page=True, animations="disabled"
        )
        page.locator("#file-input").set_input_files(
            [
                str(ROOT / "samples" / "sample-invoices.xlsx"),
                str(ROOT / "samples" / "sample-mismatch.csv"),
                str(ROOT / "samples" / "sample-invoice.png"),
            ]
        )
        expect(page.locator("#metric-documents")).to_have_text("3", timeout=60000)
        expect(page.locator("#queue-title")).to_contain_text("3 successful", timeout=60000)
        expect(page.locator("#metric-invoices")).to_have_text("4")
        # Select the deliberately inconsistent record, inspect errors and correct it.
        row = page.locator("#document-list tr").filter(has_text="sample-mismatch.csv")
        row.get_by_role("button").last.click()
        expect(page.locator("#review-title")).to_have_text("sample-mismatch.csv")
        page.locator("#tab-issues").click()
        expect(page.locator("#panel-issues")).to_contain_text("12000")
        page.locator("#tab-json").click()
        records = json.loads(page.locator("#json-editor").input_value())
        records[0]["totals"]["grand_total"] = "11800.00"
        page.locator("#json-editor").fill(json.dumps(records, indent=2))
        page.locator("#reviewer-confirmed").check()
        page.locator("#save-document").click()
        expect(page.locator("#review-status")).to_contain_text("Consistency checked", timeout=10000)
        expect(page.locator("#json-error")).to_be_hidden()
        # Downloads go through the real export route.
        with page.expect_download() as download_info:
            page.locator("#download-json").click()
        download = download_info.value
        exported = json.loads(Path(download.path()).read_text())
        assert exported["status"] == "validated"
        assert exported["invoices"][0]["totals"]["grand_total"] == "11800.00"
        with page.expect_download() as download_info:
            page.locator("#download-csv").click()
        assert "invoice_grand_total" in Path(download_info.value.path()).read_text()
        # Inspect real OCR source preview and item rows, then persist human confirmation.
        page.locator("#document-list tr").filter(has_text="sample-invoice.png").get_by_role(
            "button"
        ).last.click()
        expect(page.locator("#review-title")).to_have_text("sample-invoice.png")
        expect(page.locator("#review-status")).to_contain_text("Needs review")
        page.get_by_text("Preview original image", exact=True).click()
        preview = page.locator("#panel-overview img")
        expect(preview).to_be_visible()
        expect(preview).to_have_js_property("complete", True)
        assert preview.evaluate("image => image.naturalWidth") > 0
        page.locator("#tab-items").click()
        expect(page.locator("#panel-items")).to_contain_text("Office chairs")
        page.locator("#tab-raw").click()
        expect(page.locator("#raw-text")).to_contain_text("14160.00")
        page.locator("#reviewer-confirmed").check()
        page.locator("#save-document").click()
        expect(page.locator("#review-status")).to_contain_text("Consistency checked", timeout=10000)
        page.locator("#tab-overview").click()
        page.screenshot(
            path=str(artifacts / "desktop-review.png"), full_page=True, animations="disabled"
        )
        page.reload()
        expect(page.locator("#metric-documents")).to_have_text("3")
        expect(page.locator("#metric-validated")).to_have_text("3")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#menu-button").click()
        page.locator('[data-view="samples"]').click()
        expect(page.locator("#samples-section")).to_be_visible()
        expect(page.locator("#samples-list a").first).to_be_visible()
        page.screenshot(
            path=str(artifacts / "mobile-samples.png"), full_page=True, animations="disabled"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
            "Mobile document overflows horizontally"
        )
        page.locator("#menu-button").click()
        page.locator('[data-view="documents"]').click()
        page.locator("#document-list tr").filter(has_text="sample-mismatch.csv").get_by_role(
            "button"
        ).last.click()
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#delete-document").click()
        expect(page.locator("#metric-documents")).to_have_text("2")
        assert errors == [], f"Browser errors: {errors}"
        browser.close()
    print(
        "Browser smoke passed: multi-upload, real OCR preview, review/correction, persistence, JSON/CSV export, deletion, mobile navigation and no JS/CSP errors."
    )
    print(f"Screenshots: {artifacts}")


if __name__ == "__main__":
    main()
