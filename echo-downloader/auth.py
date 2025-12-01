from threading import Event
from typing import Optional, Tuple
import logging
import getpass
import time
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
import base64

from selenium.webdriver.common.by import By

import requests
from colorama import Style

import selenium_controller as controller
from utils import Loader

import pickle


logger = logging.getLogger(__name__)

def prompt_till_yn(prompt: str) -> bool:
    while True:
        if (opt := input(prompt).strip().lower()) in ("y", "yes", "n", "no"):
            break
    return opt in ("y", "yes")

def encrypt(data: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    fernet = Fernet(key)
    encrypted_data = fernet.encrypt(data)
    return salt + encrypted_data

def decrypt(data: bytes, password: str) -> bytes:
    salt = data[:16]
    encrypted_data = data[16:]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    fernet = Fernet(key)
    decrypted_data = fernet.decrypt(encrypted_data)
    return decrypted_data

def save_session_cookies(session: requests.Session, filename: str) -> None:
    if not prompt_till_yn("Save session to prevent having to reloggin (y/n): "):
        return
    password = getpass.getpass("Enter a password to encrypt the session file (leave blank for no encryption): ")

    unencrypted_cookies = session.cookies.get_dict()
    if password != "":
        encrypted_cookies = encrypt(pickle.dumps(unencrypted_cookies), password)
        with open(filename, "wb") as f:
            pickle.dump((True, encrypted_cookies), f)
    else:
        with open(filename, "wb") as f:
            pickle.dump((False, unencrypted_cookies), f)

def load_session_cookies(session: requests.Session, filename: str) -> bool:
    if not os.path.exists(filename):
        return False 

    with open(filename, "rb") as f:
        is_encrypted, cookies_data = pickle.load(f)
    if not is_encrypted:
        cookies = cookies_data
    else:
        password = getpass.getpass("Enter the password to decrypt the session file: ")
        try:
            decrypted_data = decrypt(cookies_data, password)
            cookies = pickle.loads(decrypted_data)
        except Exception as e:
            logger.error(f"Failed to decrypt session file: {e}")
            return False
    
    # Add cookies with proper domain scope
    # cookies is a dict {name: value} from get_dict()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain='echo360.org.uk')
    return True

def auth_echo360(session: requests.Session, base_url: str) -> bool:
    if load_session_cookies(session, "echo360.cookies"):
        logger.debug("Loaded session cookies from file.")
        # Verify if session is still valid by accessing base_url
        resp = session.get(base_url)
        if resp.url.startswith("https://echo360.org.uk"):
            logger.debug("Session cookies are still valid.")
            return True
        else:
            print("Session cookies are stale, need to relogin.")
    

    res = login_to_ms()
    if res is None: return False

    username, driver = res
    logger.debug(f"Authenticated as: {username}")
    if not username:
        return False
    print("Authenticating with Echo360...")
    driver.get(base_url)
    logger.debug(f"Navigated to base URL: {driver.current_url}")
    # Extract appId from the login page
    
    logger.debug(f"Redirected to [{driver.current_url}] for login")
    if "login.echo360.org.uk/login" not in driver.current_url:
        logger.fatal(f"Unexpected login URL, expected Echo360 login page.")
        return False
    
    # write username+ed.ac.uk to <input name="email" class="email" id="email" value="" placeholder="Enter your Email Address" type="email" autocomplete="on">
    driver.find_element(By.CLASS_NAME,"email").send_keys(username + "@ed.ac.uk")
    # then click submit <button id="submitBtn" type="submit" value="submit" class="echo-btn primary submit-btn raspberry-btn">
    driver.find_element(By.ID,"submitBtn").click()
    
    # Wait for SAML flow to complete and end up at base_url
    timeout = 30
    end_time = time.time() + timeout
    logger.debug(f"Waiting up to {timeout}s for SAML flow to complete...")
    last_url = ""
    while time.time() < end_time:
        current_url = driver.current_url

        if current_url != last_url:
            logger.debug(f"URL changed: {current_url}")
            last_url = current_url

        if current_url.startswith("https://echo360.org.uk"):
            logger.debug(f"Reached base URL!")
            break
        time.sleep(0.2)
    
    logger.debug(f"Final URL: {driver.current_url}")
    logger.debug(f"Page title: {driver.title}")

    if driver.current_url.startswith("https://echo360.org.uk"):
        print("Successfully logged into Echo360!")
        echo_cookies = controller.retrieve_cookie(driver, "https://echo360.org.uk")
        if echo_cookies is None:
            logger.fatal("Could not retrieve Echo360 cookies after login.")
            return False

        controller.copy_cookies_to_session(
            echo_cookies,
            session
        )
        save_session_cookies(session, "echo360.cookies")
        return True
    logger.fatal("Could not log into Echo360.")
    return False

def login_to_ms() -> Optional[Tuple[str, controller.WebDriver]]:
    try:
        res = perform_interactive_microsoft_login(logger)
        logger.debug(f"login_to_ms result: {res}")
        if res is None:
            logger.fatal("Could not log into Microsoft (invalid credentials?).")
            return None
        username, driver = res
    except Exception as e:
        logger.fatal("Failed to log into Microsoft: " + str(e))
        return None

    return (username, driver)

def perform_interactive_microsoft_login(logger: logging.Logger) -> Optional[Tuple[str, controller.WebDriver]]:
    logger.debug("Initialising Selenium")

    print("Starting browser for Microsoft login...")
    ready = Event()
    return_values: controller.SeleniumLauncherReturnValues = {}
    try:
        controller.initialise_selenium(return_values, ready)
    except Exception as e:
        logger.fatal(f"Failed to start browser: {e}")
        return None

    logger.debug("Prompting for EASE credentials")
    print(
        Style.BRIGHT
        + "This script requires authentication. Please provide your EASE credentials.",
        Style.RESET_ALL,
    )
    time.sleep(0.2)  # wait for the Selenium thread to initialize so we dont overlap prints
    username = input("EASE Username: ")
    password = getpass.getpass("     Password: ")

    logger.debug("Waiting for Selenium initialisation to become ready")
    loader = Loader("Navigating to Microsoft login page...")

    # Wait for initialise_selenium to signal readiness (should already be set by call)
    ready.wait()
    if "error" in return_values:
        logger.fatal(f"Failed to start browser: {return_values["error"]}")
        return None

    if "driver" not in return_values:
        logger.fatal(f"Failed to start browser for unknown reason")
        return None

    driver = return_values["driver"]
    loader.desc = "Sending credentials to Microsoft login page..."
    if not controller.submit_validate_username_password(
        driver, username, password
    ):
        logger.fatal("Invalid credentials")
        loader.cancel("Invalid credentials")
        return None

    loader.stop()
    loader.desc = "Waiting for 2FA prompt..."
    prompt_type = controller.wait_for_2fa_prompt(driver)

    if not prompt_type:
        logger.fatal("Browser behaved unexpectedly when waiting for 2FA")
        loader.cancel("Failed for unknown reason.")
        return None

    loader.stop()

    if prompt_type[0] == controller.TWO_FACTOR_TYPE.APPROVE_NUMBER:
        logger.debug("Prompting user to approve a number")
        print(f"Please use your app to approve this sign-in request: {prompt_type[1]}")
        #print(f"Please use your app to approve this sign-in request: {prompt_type[1]}")
        
        #loader = Loader("Waiting for Microsoft to accept the 2FA auth...")

    elif prompt_type[0] == controller.TWO_FACTOR_TYPE.SIX_DIGIT_CODE:
        logger.debug("Prompting user for 6-digit code")
        otp = input("Please input your 2FA 6-digit code: ").strip()
        loader = Loader("Waiting for Microsoft to accept the 2FA auth...")
        controller.input_2fa_otp(driver, otp)

    if not controller.wait_for_2fa_completion(driver):
        logger.fatal("2FA completion timeout failed")
        loader.cancel("2FA failed!")
        return None

    name = controller.retrieve_logged_in_name(driver)
    loader.stop(f"Logged in as {name}!")

    return (username, driver)

