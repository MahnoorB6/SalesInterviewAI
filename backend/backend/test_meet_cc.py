import asyncio
from playwright.async_api import async_playwright


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False
        )

        page = await browser.new_page()

        print("Open your Google Meet manually.")
        print("Then enable Captions.")
        print("This browser will inspect visible text.")

        await page.goto(
            "https://meet.google.com/",
            wait_until="domcontentloaded"
        )

        input(
            "\nWhen Meet is open and captions are visible, "
            "press ENTER here..."
        )

        print("\n" + "=" * 70)
        print("VISIBLE TEXT")
        print("=" * 70)

        text = await page.locator("body").inner_text()

        print(text)

        print("=" * 70)

        await browser.close()


asyncio.run(main())