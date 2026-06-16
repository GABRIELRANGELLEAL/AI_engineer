from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import sys
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from logging_config import get_logger, LogContext
from auth import AuthenticationManager
from config import (
    EPROC_BASE_URL,
    EPROC_TIMEOUT_MS,
    EPROC_RETRY_ATTEMPTS,
    HEADLESS_MODE,
    DATABASE_URL,
)

logger = get_logger()

# Import models from Step 1
sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))
from models import Case, Filing, FilingStatusEnum


@dataclass
class RawFiling:
    """Represents a filing extracted from eProc."""

    date: datetime
    content: str
    filing_type: Optional[str] = None


class EprocScraper:
    """Scrapes filings from eProc portal."""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.auth_manager = AuthenticationManager()
        self.db_engine = create_engine(DATABASE_URL)
        self.SessionLocal = sessionmaker(bind=self.db_engine)

    async def start_browser(self) -> None:
        """Initialize Playwright browser."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=HEADLESS_MODE)
        self.context = await self.browser.new_context()
        logger.info("Browser started")

    async def stop_browser(self) -> None:
        """Close Playwright browser."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        logger.info("Browser stopped")

    async def get_new_filings(self, case: Case) -> List[RawFiling]:
        """
        Navigate to case page and extract new filings.
        Compares with last filing in database to avoid duplicates.
        """
        with LogContext(case.case_number) as ctx:
            try:
                page = await self.context.new_page()

                # Navigate to case search
                await page.goto(EPROC_BASE_URL, timeout=EPROC_TIMEOUT_MS)

                # Search for case by case_number
                filings = await self._search_and_extract_filings(
                    page, case.case_number
                )

                # Filter out filings already in database
                new_filings = await self._filter_existing_filings(case.id, filings)

                ctx.info(f"Found {len(new_filings)} new filings", extra={"filing_count": len(new_filings)})

                await page.close()
                return new_filings

            except PlaywrightTimeoutError as e:
                ctx.warning(f"Timeout while scraping: {str(e)}", extra={"retry_attempt": 1})
                return []
            except Exception as e:
                ctx.error(f"Error scraping case: {str(e)}", exc_info=True)
                return []

    async def _search_and_extract_filings(
        self, page: Page, case_number: str
    ) -> List[RawFiling]:
        """Search for case and extract filings from results page."""
        try:
            # Fill search field
            search_selectors = [
                'input[name="numero"]',
                'input[placeholder*="Número"]',
                'input[type="text"][id*="search"]',
            ]

            search_found = False
            for selector in search_selectors:
                try:
                    await page.fill(selector, case_number, timeout=5000)
                    search_found = True
                    break
                except:
                    continue

            if not search_found:
                logger.error(f"Could not find search field with selectors", extra={"selector": str(search_selectors)})
                return []

            # Submit search
            search_button_selectors = [
                'button:has-text("Pesquisar")',
                'button[type="submit"]',
                'button:has-text("Search")',
            ]

            for selector in search_button_selectors:
                try:
                    await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("load", timeout=EPROC_TIMEOUT_MS)
                    break
                except:
                    continue

            # Wait for results
            await page.wait_for_selector(
                '[role="row"], table tbody tr', timeout=EPROC_TIMEOUT_MS
            )

            # Click on case link (first result)
            case_link_selectors = [
                'a[href*="processo"]',
                'a[href*="case"]',
                'table tbody tr:first-child a',
            ]

            for selector in case_link_selectors:
                try:
                    await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("load", timeout=EPROC_TIMEOUT_MS)
                    break
                except:
                    continue

            # Extract filings from docket
            filings = await self._extract_docket_entries(page)
            return filings

        except Exception as e:
            logger.error(f"Error searching and extracting: {str(e)}", exc_info=True)
            return []

    async def _extract_docket_entries(self, page: Page) -> List[RawFiling]:
        """Extract filing entries from case docket page."""
        try:
            filings = []

            # Wait for docket table/entries
            await page.wait_for_selector(
                '[class*="docket"], [class*="processo"], table tbody',
                timeout=EPROC_TIMEOUT_MS,
            )

            # Get all rows (adapt selectors based on actual eProc structure)
            rows = await page.query_selector_all(
                'table tbody tr, [class*="movimento"] div'
            )

            for row in rows[:10]:  # Get last 10 filings
                try:
                    # Extract date
                    date_text = await row.query_selector(
                        '[class*="data"], td:nth-child(1)'
                    )
                    filing_date_str = (
                        await date_text.text_content()
                        if date_text
                        else datetime.now().isoformat()
                    )

                    # Parse date (adapt format if needed)
                    try:
                        filing_date = datetime.strptime(
                            filing_date_str.strip(), "%d/%m/%Y"
                        )
                    except:
                        filing_date = datetime.now()

                    # Extract content/description
                    content_selector = await row.query_selector(
                        '[class*="descricao"], td:nth-child(2), td:nth-child(3)'
                    )
                    content = (
                        await content_selector.text_content()
                        if content_selector
                        else ""
                    )

                    # Extract filing type
                    type_selector = await row.query_selector(
                        '[class*="tipo"], td:nth-child(2)'
                    )
                    filing_type = (
                        await type_selector.text_content() if type_selector else None
                    )

                    if content.strip():
                        filings.append(
                            RawFiling(
                                date=filing_date,
                                content=content.strip(),
                                filing_type=filing_type.strip()
                                if filing_type
                                else None,
                            )
                        )

                except Exception as e:
                    logger.debug(f"Error extracting row: {str(e)}")
                    continue

            return filings

        except Exception as e:
            logger.error(f"Error extracting docket: {str(e)}", exc_info=True)
            return []

    async def _filter_existing_filings(
        self, case_id: int, filings: List[RawFiling]
    ) -> List[RawFiling]:
        """Filter out filings that already exist in database."""
        session = self.SessionLocal()
        try:
            existing_filings = (
                session.query(Filing)
                .filter_by(case_id=case_id)
                .order_by(Filing.filing_date.desc())
                .limit(5)
                .all()
            )

            existing_contents = {f.raw_content for f in existing_filings}
            new_filings = [f for f in filings if f.content not in existing_contents]

            return new_filings

        finally:
            session.close()

    async def save_filings(self, case_id: int, filings: List[RawFiling]) -> int:
        """Save new filings to database."""
        session = self.SessionLocal()
        try:
            count = 0
            for filing in filings:
                try:
                    new_filing = Filing(
                        case_id=case_id,
                        raw_content=filing.content,
                        filing_date=filing.date,
                        status=FilingStatusEnum.NEW,
                    )
                    session.add(new_filing)
                    count += 1
                except Exception as e:
                    logger.error(f"Error saving filing: {str(e)}")

            session.commit()
            logger.info(f"Saved {count} filings to database")
            return count

        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {str(e)}", exc_info=True)
            return 0
        finally:
            session.close()

    async def scrape_case(self, case: Case) -> Tuple[int, int]:
        """
        Full scraping pipeline for one case.
        Returns (new_filings_count, error_count).
        """
        with LogContext(case.case_number):
            for attempt in range(EPROC_RETRY_ATTEMPTS):
                try:
                    filings = await self.get_new_filings(case)
                    if filings:
                        count = await self.save_filings(case.id, filings)
                        return count, 0
                    else:
                        return 0, 0

                except Exception as e:
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {str(e)}",
                        extra={"retry_attempt": attempt + 1},
                    )
                    if attempt == EPROC_RETRY_ATTEMPTS - 1:
                        return 0, 1

            return 0, 1
