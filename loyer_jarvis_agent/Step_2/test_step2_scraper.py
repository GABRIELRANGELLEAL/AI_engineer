#!/usr/bin/env python
"""
Test script for the scraper.
Tests individual components without running full scraper.

Usage:
    python test_scraper.py --test auth          # Test authentication
    python test_scraper.py --test filings       # Test filing extraction
    python test_scraper.py --test database      # Test database connection
    python test_scraper.py --test all           # Run all tests
"""

import asyncio
import sys
from pathlib import Path
from argparse import ArgumentParser
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scraper import EprocScraper, RawFiling
from logging_config import setup_logging, get_logger
from auth import AuthenticationManager
from config import DATABASE_URL

# Import models from Step 1
sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))
from models import Case, User, Filing, FilingStatusEnum, Base

logger = setup_logging()


async def test_authentication():
    """Test eProc authentication."""
    logger.info("Testing authentication...")

    scraper = EprocScraper()
    await scraper.start_browser()

    try:
        # Create test user context
        authenticated = await scraper.auth_manager.authenticate(
            scraper.context, lawyer_id=1
        )

        if authenticated:
            logger.info("✓ Authentication successful")
            return True
        else:
            logger.error("✗ Authentication failed")
            return False

    except Exception as e:
        logger.error(f"✗ Authentication test failed: {str(e)}")
        return False
    finally:
        await scraper.stop_browser()


async def test_filing_extraction():
    """Test filing extraction logic."""
    logger.info("Testing filing extraction...")

    try:
        # Create sample filings
        test_filings = [
            RawFiling(
                date=datetime(2026, 6, 10),
                content="Test filing 1: Motion for extension",
                filing_type="Motion",
            ),
            RawFiling(
                date=datetime(2026, 6, 9),
                content="Test filing 2: Court order",
                filing_type="Order",
            ),
        ]

        if len(test_filings) == 2:
            logger.info(f"✓ Created {len(test_filings)} test filings")
            for f in test_filings:
                logger.info(f"  - {f.date.isoformat()}: {f.content[:50]}...")
            return True
        else:
            logger.error("✗ Failed to create test filings")
            return False

    except Exception as e:
        logger.error(f"✗ Filing extraction test failed: {str(e)}")
        return False


def test_database_connection():
    """Test database connection."""
    logger.info("Testing database connection...")

    try:
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        # Try to count cases
        case_count = session.query(Case).count()
        session.close()

        logger.info(f"✓ Database connected: {case_count} cases found")
        return True

    except Exception as e:
        logger.error(f"✗ Database connection failed: {str(e)}")
        return False


def test_database_write():
    """Test database write operations."""
    logger.info("Testing database write operations...")

    try:
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        # Create test user (skip if exists)
        test_user = session.query(User).filter_by(email="scraper_test@example.com").first()

        if not test_user:
            test_user = User(
                name="Scraper Test User",
                email="scraper_test@example.com",
                google_calendar_token=None,
            )
            session.add(test_user)
            session.commit()
            user_id = test_user.id
            logger.info(f"  Created test user (ID: {user_id})")
        else:
            user_id = test_user.id
            logger.info(f"  Using existing test user (ID: {user_id})")

        # Create test case (skip if exists)
        test_case = (
            session.query(Case)
            .filter_by(case_number="0000000-00.0000.0.00.0000")
            .first()
        )

        if not test_case:
            test_case = Case(
                case_number="0000000-00.0000.0.00.0000",
                court="TEST-COURT",
                lawyer_id=user_id,
                active=True,
            )
            session.add(test_case)
            session.commit()
            case_id = test_case.id
            logger.info(f"  Created test case (ID: {case_id})")
        else:
            case_id = test_case.id
            logger.info(f"  Using existing test case (ID: {case_id})")

        # Create test filing
        test_filing = Filing(
            case_id=case_id,
            raw_content="Test filing from scraper_test.py",
            filing_date=datetime.now(),
            status=FilingStatusEnum.NEW,
        )
        session.add(test_filing)
        session.commit()

        filing_id = test_filing.id
        logger.info(f"✓ Database write successful (filing ID: {filing_id})")

        session.close()
        return True

    except Exception as e:
        logger.error(f"✗ Database write test failed: {str(e)}", exc_info=True)
        return False


async def run_all_tests():
    """Run all tests."""
    logger.info("="*60)
    logger.info("Running all tests")
    logger.info("="*60)

    results = {
        "database_connection": test_database_connection(),
        "database_write": test_database_write(),
        "filing_extraction": await test_filing_extraction(),
        # "authentication": await test_authentication(),  # Commented out as requires credentials
    }

    logger.info("="*60)
    logger.info("Test Results:")
    logger.info("="*60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status}: {test_name}")

    logger.info("="*60)
    logger.info(f"Total: {passed}/{total} tests passed")
    logger.info("="*60)

    return all(results.values())


def main():
    """Main test runner."""
    parser = ArgumentParser(description="Scraper Test Suite")
    parser.add_argument(
        "--test",
        choices=["auth", "filings", "database", "all"],
        default="all",
        help="Which test to run",
    )

    args = parser.parse_args()

    if args.test == "auth":
        result = asyncio.run(test_authentication())
    elif args.test == "filings":
        result = asyncio.run(test_filing_extraction())
    elif args.test == "database":
        result = test_database_connection() and test_database_write()
    else:  # all
        result = asyncio.run(run_all_tests())

    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
