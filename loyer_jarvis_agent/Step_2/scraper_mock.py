"""
Mock Scraper for testing without real eProc credentials.
Simulates eProc responses with realistic test data.

Usage:
    python scraper_mock.py              # Scrape all active cases
    python scraper_mock.py --case-id 1  # Scrape specific case
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scraper import EprocScraper, RawFiling
from logging_config import setup_logging, get_logger
from config import DATABASE_URL

# Import models from Step 1
sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))
from models import Case, Filing, FilingStatusEnum

logger = setup_logging()


class MockEprocScraper(EprocScraper):
    """
    Mock version of EprocScraper that doesn't need real eProc credentials.
    Returns simulated filings for testing.
    """

    # Simulated filing templates
    MOCK_FILINGS = {
        "motion": "MOÇÃO DE {description} - Requerimento para {details}",
        "order": "DESPACHO - {description}. Determina-se {details}",
        "petition": "PETIÇÃO - {description}. Solicita-se {details}",
        "response": "RESPOSTA À {description} - Impugnação ao pedido de {details}",
        "appeal": "AGRAVO DE {description} - Recurso contra {details}",
    }

    FILING_DESCRIPTIONS = {
        "motion": [
            "suspensão de prazo",
            "prorrogação de prazo",
            "conversão em diligência",
            "julgamento antecipado",
        ],
        "order": [
            "Intimação para pronunciamento em 5 dias",
            "Condenação em honorários sucumbenciais",
            "Arquivamento do processo",
            "Remessa ao tribunal superior",
        ],
        "petition": [
            "medida cautelar",
            "tutela antecipada",
            "assistência judiciária",
            "acompanhamento processual",
        ],
        "response": [
            "Petição Inicial",
            "Moção de Suspensão",
            "Petição de Recurso",
            "Incidente de Execução",
        ],
        "appeal": [
            "sentença condenatória",
            "sentença absolutória",
            "despacho interlocutório",
            "decisão monocrática",
        ],
    }

    async def start_browser(self) -> None:
        """Mock: Don't actually start browser."""
        logger.info("Mock browser started (no real Playwright)")
        self.db_engine = create_engine(DATABASE_URL)
        self.SessionLocal = sessionmaker(bind=self.db_engine)

    async def stop_browser(self) -> None:
        """Mock: Nothing to stop."""
        logger.info("Mock browser stopped")

    async def get_new_filings(self, case: Case) -> List[RawFiling]:
        """
        Mock: Generate realistic simulated filings.
        Returns 2-5 random filings with recent dates.
        """
        from random import choice, randint

        logger.info(f"Mock scraping case {case.case_number}")

        # Generate 2-5 random filings
        num_filings = randint(2, 5)
        filings = []

        for i in range(num_filings):
            # Random filing type
            filing_type = choice(list(self.MOCK_FILINGS.keys()))

            # Random description
            descriptions = self.FILING_DESCRIPTIONS.get(filing_type, ["Test"])
            description = choice(descriptions)

            # Random details
            details_options = [
                "mantém a decisão anterior",
                "acolhe o pedido",
                "nega o pedido",
                "dá provimento ao recurso",
                "nega provimento ao recurso",
            ]
            details = choice(details_options)

            # Generate content
            content = self.MOCK_FILINGS[filing_type].format(
                description=description, details=details
            )

            # Random date (last 7 days)
            days_ago = randint(0, 7)
            filing_date = datetime.now() - timedelta(days=days_ago)

            filings.append(
                RawFiling(
                    date=filing_date,
                    content=content,
                    filing_type=filing_type.upper(),
                )
            )

            logger.debug(f"Generated mock filing: {filing_type} - {description[:50]}")

        # Filter out existing (same logic as real scraper)
        new_filings = await self._filter_existing_filings(case.id, filings)

        logger.info(f"Mock: {len(new_filings)} new filings generated for {case.case_number}")
        return new_filings

    async def _search_and_extract_filings(self, page, case_number):
        """Mock: Not used in mock scraper."""
        pass

    async def _extract_docket_entries(self, page):
        """Mock: Not used in mock scraper."""
        pass

    async def scrape_case(self, case: Case) -> Tuple[int, int]:
        """
        Mock: Full scraping pipeline without real eProc.
        Returns (new_filings_count, error_count).
        """
        logger.info(f"Mock scraping case: {case.case_number}")

        try:
            filings = await self.get_new_filings(case)

            if filings:
                count = await self.save_filings(case.id, filings)
                logger.info(
                    f"Saved {count} mock filings for case {case.case_number}"
                )
                return count, 0
            else:
                logger.info(f"No new filings for case {case.case_number}")
                return 0, 0

        except Exception as e:
            logger.error(f"Mock scraper error: {str(e)}", exc_info=True)
            return 0, 1


async def main(case_id: int = None, num_filings: int = 3):
    """
    Main mock scraping orchestration.

    Args:
        case_id: Optional specific case ID to scrape
        num_filings: Number of mock filings to generate per case
    """
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        if case_id:
            cases = session.query(Case).filter(
                Case.id == case_id, Case.active == True
            ).all()
        else:
            cases = session.query(Case).filter(Case.active == True).all()

        if not cases:
            logger.warning("No active cases found to scrape")
            return

        logger.info(f"Starting mock scraper for {len(cases)} case(s)")

    finally:
        session.close()

    scraper = MockEprocScraper()
    await scraper.start_browser()

    total_filings = 0
    total_errors = 0

    try:
        for case in cases:
            logger.info(f"Processing case: {case.case_number}")

            try:
                filings = await scraper.get_new_filings(case)

                if filings:
                    count = await scraper.save_filings(case.id, filings)
                    total_filings += count
                    logger.info(f"✓ Saved {count} filings for {case.case_number}")
                else:
                    logger.info(f"No new filings for {case.case_number}")

            except Exception as e:
                logger.error(
                    f"Error scraping case {case.case_number}: {str(e)}",
                    exc_info=True,
                )
                total_errors += 1

    finally:
        await scraper.stop_browser()

    logger.info(
        f"Mock scraping complete: {total_filings} filings saved, {total_errors} errors"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mock eProc Scraper (No credentials needed)")
    parser.add_argument(
        "--case-id",
        type=int,
        help="Scrape specific case ID",
    )
    parser.add_argument(
        "--num-filings",
        type=int,
        default=3,
        help="Number of mock filings to generate per case",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Mock eProc Scraper Started (No Real Credentials Needed)")
    logger.info("=" * 60)

    try:
        asyncio.run(main(case_id=args.case_id, num_filings=args.num_filings))
    except KeyboardInterrupt:
        logger.info("Mock scraper interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Mock eProc Scraper Finished")
    logger.info("=" * 60)
