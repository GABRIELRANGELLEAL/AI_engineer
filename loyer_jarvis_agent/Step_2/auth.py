import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from playwright.async_api import Browser, Page, BrowserContext
from logging_config import get_logger
from config import (
    EPROC_BASE_URL,
    AUTH_METHOD,
    EPROC_USERNAME,
    EPROC_PASSWORD,
    CERTIFICATE_PATH,
    CERTIFICATE_PASSWORD,
    SAVE_SESSION_PATH,
    SESSION_COOKIE_DURATION_DAYS,
    EPROC_TIMEOUT_MS,
)

logger = get_logger()


class SessionManager:
    """Manages authentication sessions and cookies."""

    def __init__(self):
        self.session_path = Path(SAVE_SESSION_PATH)
        self.session_path.mkdir(parents=True, exist_ok=True)

    def session_file_path(self, lawyer_id: int) -> Path:
        """Get the session file path for a lawyer."""
        return self.session_path / f"session_{lawyer_id}.json"

    def is_session_valid(self, lawyer_id: int) -> bool:
        """Check if a stored session is still valid."""
        session_file = self.session_file_path(lawyer_id)
        if not session_file.exists():
            return False

        file_time = datetime.fromtimestamp(session_file.stat().st_mtime)
        expiry_time = file_time + timedelta(days=SESSION_COOKIE_DURATION_DAYS)

        if datetime.now() > expiry_time:
            logger.info(f"Session expired for lawyer {lawyer_id}, removing")
            session_file.unlink()
            return False

        return True

    def save_session(self, context: BrowserContext, lawyer_id: int) -> None:
        """Save browser context cookies to file."""
        try:
            cookies = context.cookies()
            session_file = self.session_file_path(lawyer_id)
            import json

            with open(session_file, "w") as f:
                json.dump(cookies, f)
            logger.info(f"Session saved for lawyer {lawyer_id}")
        except Exception as e:
            logger.error(f"Failed to save session: {str(e)}")

    def load_session(self, context: BrowserContext, lawyer_id: int) -> bool:
        """Load cookies from saved session."""
        try:
            session_file = self.session_file_path(lawyer_id)
            if not session_file.exists():
                return False

            import json

            with open(session_file, "r") as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            logger.info(f"Session loaded for lawyer {lawyer_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to load session: {str(e)}")
            return False


class AuthenticatorUsername:
    """Authenticates via username/password."""

    async def authenticate(self, page: Page) -> bool:
        """Authenticate using username and password."""
        try:
            logger.info("Attempting username/password authentication")

            await page.goto(EPROC_BASE_URL, timeout=EPROC_TIMEOUT_MS, wait_until="load")

            # Click login button (selector may vary by portal version)
            login_selectors = [
                'a[href*="login"]',
                'button:has-text("Entrar")',
                'button:has-text("Login")',
            ]

            for selector in login_selectors:
                try:
                    await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("load", timeout=EPROC_TIMEOUT_MS)
                    break
                except:
                    continue

            # Fill username and password
            username_selectors = [
                'input[name="username"]',
                'input[name="cpf"]',
                'input[id="username"]',
            ]
            password_selectors = [
                'input[name="password"]',
                'input[type="password"]',
            ]

            username_filled = False
            for selector in username_selectors:
                try:
                    await page.fill(selector, EPROC_USERNAME, timeout=5000)
                    username_filled = True
                    break
                except:
                    continue

            if not username_filled:
                logger.error("Could not find username field")
                return False

            for selector in password_selectors:
                try:
                    await page.fill(selector, EPROC_PASSWORD, timeout=5000)
                    break
                except:
                    continue

            # Submit form
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Entrar")',
                'button:has-text("Login")',
            ]

            for selector in submit_selectors:
                try:
                    await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("load", timeout=EPROC_TIMEOUT_MS)
                    break
                except:
                    continue

            logger.info("Username/password authentication successful")
            return True

        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}", exc_info=True)
            return False


class AuthenticatorCertificate:
    """Authenticates via digital certificate (A1/A3)."""

    async def authenticate(self, page: Page) -> bool:
        """Authenticate using digital certificate."""
        logger.info("Certificate authentication not yet implemented")
        logger.info("Please use AUTH_METHOD=username for now")
        return False


class AuthenticationManager:
    """Manages the authentication flow."""

    def __init__(self):
        self.session_manager = SessionManager()
        self.username_auth = AuthenticatorUsername()
        self.certificate_auth = AuthenticatorCertificate()

    async def authenticate(
        self, context: BrowserContext, lawyer_id: int
    ) -> bool:
        """
        Authenticate user, trying to reuse session first.
        Returns True if authenticated successfully.
        """
        # Try to load existing session
        if self.session_manager.is_session_valid(lawyer_id):
            page = await context.new_page()
            if self.session_manager.load_session(context, lawyer_id):
                await page.close()
                return True

        # Create new session
        page = await context.new_page()

        try:
            if AUTH_METHOD == "certificate":
                success = await self.certificate_auth.authenticate(page)
            else:
                success = await self.username_auth.authenticate(page)

            if success:
                self.session_manager.save_session(context, lawyer_id)

            return success

        finally:
            await page.close()
