"""Playwright-Login-Flow fuer DFBnet Spielplus.

Ablauf (verifiziert per sichtbarem Testlauf):
1. www.dfbnet.org/spielplus/login.do laden, Cookie-Banner ablehnen.
2. "Anmelden"-Link klicken -> Redirect zu Keycloak (auth.dfbnet.org).
3. Benutzerkennung/Passwort im Keycloak-Formular ausfuellen, absenden.
4. Redirect zurueck zu www.dfbnet.org bestaetigt erfolgreichen Login.
"""

from playwright.sync_api import Page, sync_playwright

from config import LOGIN_URL, PASSWORD, USERNAME

COOKIE_DECLINE_TEXT = "Alle Ablehnen"
ANMELDEN_LINK_XPATH = (
    "xpath=//span[contains(text(),'Anmelden')]/ancestor::*[self::button or self::a][1]"
)


def login(page: Page) -> None:
    page.goto(LOGIN_URL)
    page.wait_for_load_state("networkidle")

    decline = page.get_by_text(COOKIE_DECLINE_TEXT, exact=True)
    if decline.count() > 0:
        decline.click()
        page.wait_for_timeout(300)

    page.locator(ANMELDEN_LINK_XPATH).first.click(force=True)
    page.wait_for_load_state("networkidle")

    page.locator("#username").fill(USERNAME)
    page.locator("#password").fill(PASSWORD)
    page.locator("#password").press("Enter")

    # Die Portalseite laedt fortlaufend Werbebanner nach, daher wird hier nicht auf
    # "networkidle" gewartet (das koennte nie eintreten), sondern nur auf die Rueckkehr
    # zu www.dfbnet.org sowie den anschliessenden DOM-Ladezustand.
    page.wait_for_url("**://www.dfbnet.org/**", timeout=15000)
    page.wait_for_load_state("domcontentloaded")


if __name__ == "__main__":
    # Manueller, sichtbarer Testlauf: python src/login.py
    from config import ROOT_DIR

    screenshot_path = ROOT_DIR / "logs" / "login_test.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        login(page)
        print("Login erfolgreich. Aktuelle URL:", page.url)
        page.screenshot(path=str(screenshot_path), full_page=True)
        print("Screenshot gespeichert:", screenshot_path)
        browser.close()
