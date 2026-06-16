#!/usr/bin/env python
"""
Main execution script for eProc scraper.
Iterates over all active cases and scrapes new filings.

Usage:
    python scraper_run.py                 # Run once
    python scraper_run.py --case-id 123   # Scrape specific case
    python scraper_run.py --dry-run       # Test without saving
"""

import asyncio
import sys
from pathlib import Path
from argparse import ArgumentParser

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scraper import EprocScraper
from logging_config import setup_logging, get_logger
from config import DATABASE_URL

# Import models from Step 1
sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))
from models import Case

logger = setup_logging()


async def main(case_id: int = None, dry_run: bool = False):
    """
    Main scraping orchestration.

    Args:
        case_id: Optional specific case ID to scrape
        dry_run: If True, extract filings but don't save
    """
    # Initialize database connection
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Get active cases
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

        logger.info(f"Starting scraper for {len(cases)} case(s)")

    finally:
        session.close()

    # Initialize scraper
    scraper = EprocScraper()
    await scraper.start_browser()

    total_filings = 0
    total_errors = 0

    try:
        # Authenticate once
        sample_case = cases[0]
        authenticated = await scraper.auth_manager.authenticate(
            scraper.context, sample_case.lawyer_id
        )

        if not authenticated:
            logger.error("Failed to authenticate with eProc")
            return

        logger.info("Successfully authenticated with eProc")

        # Scrape each case
        for case in cases:
            logger.info(f"Scraping case {case.case_number}")

            try:
                filings = await scraper.get_new_filings(case)

                if dry_run:
                    logger.info(f"[DRY RUN] Would save {len(filings)} filings")
                else:
                    count = await scraper.save_filings(case.id, filings)
                    total_filings += count

            except Exception as e:
                logger.error(f"Error scraping case {case.case_number}: {str(e)}")
                total_errors += 1

    finally:
        await scraper.stop_browser()

    logger.info(f"Scraping complete: {total_filings} filings saved, {total_errors} errors")


def cli():
    """Command-line interface."""
    parser = ArgumentParser(description="eProc Scraper")
    parser.add_argument(
        "--case-id",
        type=int,
        help="Scrape specific case ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract filings but don't save to database",
    )

    args = parser.parse_args()

    logger.info("eProc Scraper started")

    try:
        asyncio.run(main(case_id=args.case_id, dry_run=args.dry_run))
    except KeyboardInterrupt:
        logger.info("Scraper interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)

    logger.info("eProc Scraper finished")


if __name__ == "__main__":
    cli()
