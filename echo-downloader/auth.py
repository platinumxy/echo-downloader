import json
import logging
import getpass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
import base64
import requests
import requests.cookies
import uoe_ms_auth

import pickle


logger = logging.getLogger(__name__)


class AutoSubmitFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = attributes.get("action")
        elif tag == "input" and attributes.get("name"):
            self.fields[attributes["name"]] = attributes.get("value", "")


def submit_auto_form(session: requests.Session, response: requests.Response) -> requests.Response:
    parser = AutoSubmitFormParser()
    parser.feed(response.text)
    if not parser.action or not parser.fields:
        return response

    action = urljoin(response.url, parser.action)
    logger.debug(f"Submitting SAML form to [{action}]")
    return session.post(
        action,
        data=parser.fields,
        headers={"Referer": response.url},
        allow_redirects=True,
        timeout=30,
    )

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
    
    for name, value in cookies.items():
        session.cookies.set(name, value, domain='echo360.org.uk')
    return True

def login_to_ms(email: str, password: str, session: requests.Session) -> bool: 
    cookies = uoe_ms_auth.authenticate(
        username=email,
        password=password,
        otp_callback=lambda: input("Please provide an OTP code from your microsoft authenticator: "),
        approval_callback=lambda code: print(f"Please approve the following signin code: {code}\r", end=""),
    )
    if cookies is None:
        return False 
    session.cookies.update(create_cookie_jar(json.loads(cookies)))
    return True 

def create_cookie_jar(cookies_list):
    jar = requests.cookies.RequestsCookieJar()
    for cookie in cookies_list:
        jar.set(
            name=cookie['name'],
            value=cookie['value'],
            domain=cookie.get('domain', ''),
            path=cookie.get('path', '/'),
            secure=cookie.get('secure', False),
            rest={'HttpOnly': cookie.get('httpOnly', False)}
        )
    return jar

def get_email() -> str:
    while True:
        email = input("Please enter your university email: ")
        if email.endswith("@ed.ac.uk"):
            return email 
        print("Please enter email in the format s1234567@ed.ac.uk")

def auth_echo360(session: requests.Session, base_url: str) -> bool:
    if load_session_cookies(session, "echo360.cookies"):
        logger.debug("Loaded session cookies from file.")
        resp = session.get(base_url)
        if resp.url.startswith("https://echo360.org.uk"):
            logger.debug("Session cookies are still valid.")
            return True
        else:
            logger.debug("Session cookies are stale, need to relogin.")
            print("Session cookies are stale, need to relogin.")
   

    email = get_email()
    password = getpass.getpass()
    if not login_to_ms(email, password, session):
        return False
    
    print("Authenticating with Echo360...")
    try:
        login_page = session.get(base_url, allow_redirects=True, timeout=30)
    except requests.RequestException as e:
        logger.error(f"Failed to open Echo360 login page: {e}")
        return False

    login_url = login_page.url
    logger.debug(f"Redirected to [{login_url}] for login")
    login_parts = urlsplit(login_url)
    if login_parts.netloc != "login.echo360.org.uk" or login_parts.path != "/login":
        logger.error(f"Unexpected login URL, expected Echo360 login page. Got: {login_url}")
        return False

    query = parse_qs(login_parts.query)
    app_id = query.get("appId", [""])[0]
    if not app_id:
        logger.error(f"Echo360 login URL did not contain an appId: {login_url}")
        return False

    form_data = {
        "email": email,
        "appId": app_id,
        "role": query.get("role", [""])[0],
        "requestedResource": query.get("requestedResource", [""])[0],
    }
    logger.debug(f"Submitting Echo360 institution login for {email}")
    try:
        login_result = session.post(
            "https://login.echo360.org.uk/login/institutions",
            data=form_data,
            headers={"Referer": login_url},
            allow_redirects=True,
            timeout=30,
        )
    except requests.RequestException as e:
        logger.error(f"Echo360 institution login failed: {e}")
        return False

    final_response = login_result
    while "name=\"hiddenform\"" in final_response.text or "name='hiddenform'" in final_response.text:
        try:
            next_response = submit_auto_form(session, final_response)
        except requests.RequestException as e:
            logger.error(f"Echo360 SAML form submission failed: {e}")
            return False
        if next_response is final_response:
            break
        final_response = next_response

    final_url = final_response.url
    logger.debug(f"Echo360 login flow ended at [{final_url}]")
    if final_url.startswith("https://echo360.org.uk") and "login" not in urlsplit(final_url).path:
        print("Successfully logged into Echo360!")
        save_session_cookies(session, "echo360.cookies")
        return True
    logger.error(f"Could not log into Echo360. Final URL was: {final_url}")
    return False

