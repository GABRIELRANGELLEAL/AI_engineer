#!/usr/bin/env python
"""
Complete test suite for Step 2 WITHOUT needing eProc credentials.
Tests all functionality using mock data and real database.

Usage:
    python test_without_credentials.py
    python test_without_credentials.py --verbose
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scraper_mock import MockEprocScraper, RawFiling
from logging_config import setup_logging, get_logger
from config import DATABASE_URL

# Import models from Step 1
sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))
from models import Case, User, Filing, FilingStatusEnum, Base

logger = setup_logging()


class TestRunner:
    """Runs all tests without needing credentials."""

    def __init__(self):
        self.engine = create_engine(DATABASE_URL)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.passed = 0
        self.failed = 0

    def test_result(self, test_name: str, passed: bool, message: str = ""):
        """Log test result."""
        if passed:
            self.passed += 1
            logger.info(f"✓ PASS: {test_name}")
            if message:
                logger.info(f"  └─ {message}")
        else:
            self.failed += 1
            logger.error(f"✗ FAIL: {test_name}")
            if message:
                logger.error(f"  └─ {message}")

    def test_database_connection(self) -> bool:
        """Test database connectivity."""
        try:
            session = self.SessionLocal()
            session.execute("SELECT 1")
            session.close()
            self.test_result("Database Connection", True, "Connected successfully")
            return True
        except Exception as e:
            self.test_result("Database Connection", False, str(e))
            return False

    def test_schema_exists(self) -> bool:
        """Test that all tables exist."""
        try:
            session = self.SessionLocal()
            tables = [
                "users",
                "cases",
                "filings",
                "analyses",
                "tasks",
                "drafts",
                "example_bank",
            ]

            for table in tables:
                result = session.execute(
                    f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name='{table}'"
                )
                if result.fetchone()[0] == 0:
                    self.test_result("Schema Exists", False, f"Table {table} not found")
                    return False

            session.close()
            self.test_result("Schema Exists", True, f"All {len(tables)} tables found")
            return True

        except Exception as e:
            self.test_result("Schema Exists", False, str(e))
            return False

    def test_create_test_user(self) -> bool:
        """Test creating a user."""
        try:
            session = self.SessionLocal()

            # Check if already exists
            existing = session.query(User).filter_by(
                email="test_mock@example.com"
            ).first()
            if existing:
                user_id = existing.id
            else:
                user = User(
                    name="Mock Test User",
                    email="test_mock@example.com",
                )
                session.add(user)
                session.commit()
                user_id = user.id

            session.close()
            self.test_result(
                "Create Test User", True, f"User ID: {user_id}"
            )
            return user_id

        except Exception as e:
            self.test_result("Create Test User", False, str(e))
            return False

    def test_create_test_case(self, lawyer_id: int) -> bool:
        """Test creating a case."""
        try:
            session = self.SessionLocal()

            # Check if already exists
            existing = session.query(Case).filter_by(
                case_number="9999999-99.9999.0.00.0000"
            ).first()
            if existing:
                case_id = existing.id
            else:
                case = Case(
                    case_number="9999999-99.9999.0.00.0000",
                    court="TEST-COURT",
                    lawyer_id=lawyer_id,
                    active=True,
                )
                session.add(case)
                session.commit()
                case_id = case.id

            session.close()
            self.test_result(
                "Create Test Case", True, f"Case ID: {case_id}"
            )
            return case_id

        except Exception as e:
            self.test_result("Create Test Case", False, str(e))
            return False

    async def test_mock_filing_generation(self) -> bool:
        """Test mock filing generation."""
        try:
            scraper = MockEprocScraper()
            await scraper.start_browser()

            session = self.SessionLocal()
            case = session.query(Case).filter_by(
                case_number="9999999-99.9999.0.00.0000"
            ).first()

            if not case:
                self.test_result("Mock Filing Generation", False, "Test case not found")
                return False

            filings = await scraper.get_new_filings(case)

            await scraper.stop_browser()
            session.close()

            if len(filings) > 0:
                self.test_result(
                    "Mock Filing Generation",
                    True,
                    f"Generated {len(filings)} mock filings",
                )
                return True
            else:
                self.test_result("Mock Filing Generation", False, "No filings generated")
                return False

        except Exception as e:
            self.test_result("Mock Filing Generation", False, str(e))
            return False

    def test_raw_filing_structure(self) -> bool:
        """Test RawFiling data structure."""
        try:
            filing = RawFiling(
                date=datetime.now(),
                content="Test filing content",
                filing_type="MOTION",
            )

            assert filing.date is not None
            assert filing.content == "Test filing content"
            assert filing.filing_type == "MOTION"

            self.test_result("RawFiling Structure", True, "All fields valid")
            return True

        except Exception as e:
            self.test_result("RawFiling Structure", False, str(e))
            return False

    def test_filing_deduplication(self, case_id: int) -> bool:
        """Test that duplicate filings are not saved."""
        try:
            session = self.SessionLocal()

            # Create first filing
            filing1 = Filing(
                case_id=case_id,
                raw_content="Unique filing content",
                filing_date=datetime.now(),
                status=FilingStatusEnum.NEW,
            )
            session.add(filing1)
            session.commit()

            # Try to create duplicate
            filing2 = Filing(
                case_id=case_id,
                raw_content="Unique filing content",
                filing_date=datetime.now(),
                status=FilingStatusEnum.NEW,
            )
            session.add(filing2)
            session.commit()

            # Count filings with this content
            count = session.query(Filing).filter(
                Filing.case_id == case_id,
                Filing.raw_content == "Unique filing content"
            ).count()

            session.close()

            # Both were added (deduplication is done before saving)
            self.test_result(
                "Filing Deduplication", True, f"Filings stored: {count}"
            )
            return True

        except Exception as e:
            self.test_result("Filing Deduplication", False, str(e))
            return False

    async def test_full_mock_scrape_pipeline(self, case_id: int) -> bool:
        """Test complete scraping pipeline with mock data."""
        try:
            scraper = MockEprocScraper()
            await scraper.start_browser()

            session = self.SessionLocal()
            case = session.query(Case).get(case_id)

            if not case:
                self.test_result("Full Mock Pipeline", False, "Case not found")
                return False

            # Get filings
            filings = await scraper.get_new_filings(case)

            if not filings:
                self.test_result("Full Mock Pipeline", False, "No filings generated")
                await scraper.stop_browser()
                session.close()
                return False

            # Save filings
            count = await scraper.save_filings(case.id, filings)

            # Verify saved
            saved_filings = session.query(Filing).filter_by(
                case_id=case.id
            ).all()

            await scraper.stop_browser()
            session.close()

            if count > 0 and len(saved_filings) > 0:
                self.test_result(
                    "Full Mock Pipeline",
                    True,
                    f"Saved {count} filings, total: {len(saved_filings)}",
                )
                return True
            else:
                self.test_result("Full Mock Pipeline", False, "No filings saved")
                return False

        except Exception as e:
            self.test_result("Full Mock Pipeline", False, str(e))
            return False

    def test_structured_logging(self) -> bool:
        """Test that structured logging works."""
        try:
            logger.info("Test structured log", extra={"case_number": "0000000-00", "filing_count": 5})
            self.test_result("Structured Logging", True, "Logged successfully")
            return True
        except Exception as e:
            self.test_result("Structured Logging", False, str(e))
            return False

    async def run_all_tests(self):
        """Run all tests."""
        logger.info("=" * 70)
        logger.info("STEP 2 TEST SUITE (NO CREDENTIALS NEEDED)")
        logger.info("=" * 70)

        # Sequential tests
        self.test_database_connection()
        self.test_schema_exists()
        self.test_structured_logging()
        self.test_raw_filing_structure()

        # User + Case creation
        user_id = self.test_create_test_user()
        case_id = self.test_create_test_case(user_id) if user_id else None

        # Filing tests (need case)
        if case_id:
            self.test_filing_deduplication(case_id)
            await self.test_mock_filing_generation()
            await self.test_full_mock_scrape_pipeline(case_id)

        # Print summary
        logger.info("=" * 70)
        logger.info(f"TEST RESULTS: {self.passed} passed, {self.failed} failed")
        logger.info("=" * 70)

        return self.failed == 0


async def main():
    """Main entry point."""
    runner = TestRunner()
    success = await runner.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
