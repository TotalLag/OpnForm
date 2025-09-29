from playwright.sync_api import sync_playwright, expect, Page

def run_verification(page: Page):
    """
    Navigates to the form page and takes a screenshot to verify it loads.
    """
    url = "https://ef566178.opnform.pages.dev/forms/501138a2-376b-4156-8b1f-782af22a9092"

    # 1. Navigate to the page.
    # Increase timeout because the first load on a new deployment can be slow.
    page.goto(url, wait_until='domcontentloaded', timeout=90000)

    # 2. Wait for a reliable element to be visible.
    # The main form container is a good indicator that the page has loaded successfully.
    form_container = page.locator("#public-form")
    expect(form_container).to_be_visible(timeout=60000)

    # 3. Take a screenshot for visual confirmation.
    page.screenshot(path="jules-scratch/verification/verification.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            run_verification(page)
            print("Verification script completed successfully.")
        except Exception as e:
            print(f"An error occurred during verification: {e}")
        finally:
            browser.close()