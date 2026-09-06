import argparse
import http.cookiejar
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ADMINS = ("admin", "emartinez", "epinto", "lhernandez", "dcanache", "cmoron")
CSRF_PATTERN = re.compile(r'id="visitorLoginCsrf"[^>]*value="([^"]+)"')


def client():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request(opener, url, *, payload=None, form=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=headers)) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def csrf_from_home(opener, base_url):
    status, html = request(opener, f"{base_url}/")
    if status != 200:
        raise RuntimeError(f"GET / returned {status}")
    match = CSRF_PATTERN.search(html)
    if not match:
        raise RuntimeError("CSRF token was not rendered")
    return match.group(1)


def login(opener, base_url, username, password, token):
    status, body = request(
        opener,
        f"{base_url}/api/visitor-session",
        payload={"name": username, "password": password, "csrf_token": token},
    )
    if status != 200:
        raise RuntimeError(f"admin login returned {status}: {body[:160]}")
    data = json.loads(body)
    if not data.get("admin") or data.get("role") != "ADMIN":
        raise RuntimeError("admin role missing from login response")
    return data["csrf_token"], body


def logout(opener, base_url, token):
    status, body = request(
        opener,
        f"{base_url}/api/visitor-session/end",
        payload={"csrf_token": token},
    )
    if status != 200:
        raise RuntimeError(f"logout returned {status}: {body[:160]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5001")
    parser.add_argument("--cycles", type=int, default=100)
    args = parser.parse_args()
    password = os.environ.get("ADMIN_SMOKE_PASSWORD")
    if not password:
        raise RuntimeError("ADMIN_SMOKE_PASSWORD is required")
    base_url = args.url.rstrip("/")
    db_path = os.path.join(os.path.dirname(__file__), "..", "instance", "app.db")
    with sqlite3.connect(db_path) as connection:
        admins_before = connection.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        visitor_admins_before = connection.execute(
            "SELECT COUNT(*) FROM visitor_sessions WHERE lower(trim(normalized_name)) IN "
            "('emartinez','hpinto','lhernandez','dcanache','cmoron')"
        ).fetchone()[0]

    login_ok = protected_ok = logout_ok = 0
    variants = (str.upper, str.capitalize, lambda value: f"  {value}  ")
    for username in ADMINS:
        for index in range(args.cycles):
            opener = client()
            token = csrf_from_home(opener, base_url)
            variant = variants[index % len(variants)](username)
            token, body = login(opener, base_url, variant, password, token)
            if password in body:
                raise RuntimeError("password appeared in login response")
            login_ok += 1
            status, _ = request(opener, f"{base_url}/admin/players")
            if status != 200:
                raise RuntimeError(f"protected route returned {status}")
            protected_ok += 1
            logout(opener, base_url, token)
            logout_ok += 1

    simultaneous = []
    for _ in range(2):
        opener = client()
        token = csrf_from_home(opener, base_url)
        token, _ = login(opener, base_url, "cmoron", password, token)
        simultaneous.append((opener, token))
    if any(request(opener, f"{base_url}/admin/pairs")[0] != 200 for opener, _ in simultaneous):
        raise RuntimeError("simultaneous admin sessions failed")

    stamp = str(int(time.time()))[-7:]
    for index, username in enumerate(ADMINS):
        opener = client()
        token = csrf_from_home(opener, base_url)
        token, _ = login(opener, base_url, username.swapcase(), password, token)
        if request(opener, f"{base_url}/api/game/start", payload={})[0] != 200:
            raise RuntimeError(f"{username}: game start failed")
        if request(opener, f"{base_url}/api/game/result")[0] != 200:
            raise RuntimeError(f"{username}: result failed")
        if request(opener, f"{base_url}/api/game/start", payload={})[0] != 200:
            raise RuntimeError(f"{username}: replay failed")
        guest_name = f"Load{index}{stamp}"
        status, _ = request(
            opener,
            f"{base_url}/admin/players/new",
            form={"name": guest_name, "csrf_token": token},
        )
        if status != 200:
            raise RuntimeError(f"{username}: player create failed ({status})")
        with sqlite3.connect(db_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM player_profiles WHERE name = ?", (guest_name,)
            ).fetchone()[0]
        edited_name = f"Edit{index}{stamp}"
        status, _ = request(
            opener,
            f"{base_url}/admin/players/{player_id}/edit",
            form={"name": edited_name, "csrf_token": token},
        )
        if status != 200:
            raise RuntimeError(f"{username}: player edit failed ({status})")
        status, _ = request(
            opener,
            f"{base_url}/admin/players/{player_id}/delete",
            form={"csrf_token": token},
        )
        if status != 200:
            raise RuntimeError(f"{username}: player delete failed ({status})")
        logout(opener, base_url, token)

    case_name = f"Case{stamp}"
    lower_name = f"case{stamp}"
    for guest_name in (case_name, lower_name):
        opener = client()
        status, _ = request(
            opener,
            f"{base_url}/api/visitor-session",
            payload={"name": guest_name},
        )
        if status != 201:
            raise RuntimeError(f"case-sensitive guest create failed ({status})")
    duplicate = client()
    status, _ = request(
        duplicate,
        f"{base_url}/api/visitor-session",
        payload={"name": case_name},
    )
    if status != 409:
        raise RuntimeError(f"exact guest duplicate returned {status}")
    invalid = client()
    status, _ = request(
        invalid,
        f"{base_url}/api/visitor-session",
        payload={"name": "Invalid_Name"},
    )
    if status != 400:
        raise RuntimeError(f"invalid guest name returned {status}")

    cleanup = client()
    token = csrf_from_home(cleanup, base_url)
    token, _ = login(cleanup, base_url, "lhernandez", password, token)
    with sqlite3.connect(db_path) as connection:
        guest_ids = [
            row[0] for row in connection.execute(
                "SELECT id FROM player_profiles WHERE name IN (?, ?)",
                (case_name, lower_name),
            )
        ]
    for player_id in guest_ids:
        status, _ = request(
            cleanup,
            f"{base_url}/admin/players/{player_id}/delete",
            form={"csrf_token": token},
        )
        if status != 200:
            raise RuntimeError(f"guest cleanup failed ({status})")
    logout(cleanup, base_url, token)

    with sqlite3.connect(db_path) as connection:
        admins_after = connection.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        visitor_admins_after = connection.execute(
            "SELECT COUNT(*) FROM visitor_sessions WHERE lower(trim(normalized_name)) IN "
            "('emartinez','hpinto','lhernandez','dcanache','cmoron')"
        ).fetchone()[0]
        hashes = [row[0] for row in connection.execute("SELECT password_hash FROM admin_users")]
    if (
        admins_before != 5
        or admins_after != 5
        or visitor_admins_after != visitor_admins_before
    ):
        raise RuntimeError("admin identity counts changed")
    if any(value == password for value in hashes):
        raise RuntimeError("plaintext password found")
    print(
        f"logins={login_ok}/{len(ADMINS) * args.cycles} "
        f"protected={protected_ok}/{len(ADMINS) * args.cycles} "
        f"logouts={logout_ok}/{len(ADMINS) * args.cycles} "
        f"admins_before={admins_before} admins_after={admins_after} "
        f"legacy_visitors_before={visitor_admins_before} "
        f"legacy_visitors_after={visitor_admins_after} "
        "simultaneous=2 gameplay_crud=5 guest_case_policy=ok"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FAILED: {error}", file=sys.stderr)
        raise
