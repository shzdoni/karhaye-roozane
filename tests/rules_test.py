#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تست قوانین Firestore با REST (بدون Node/Firebase CLI).
اجرا:  python tests/rules_test.py
پیش‌نیاز: قوانین firebase-rules/firestore.rules در کنسول منتشر شده باشد.
هشدار: چند حساب تستی موقت می‌سازد و در پایان داده‌ها و حساب‌ها را پاک می‌کند.
"""
import json
import random
import string
import sys
import time
import urllib.error
import urllib.request

PROJECT = "karhaye-roozane"
API_KEY = "AIzaSyBOehoq13MT296i41UMbd0d39hnQHwZ6FI"
BASE = "https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents" % PROJECT
AUTH = "https://identitytoolkit.googleapis.com/v1/accounts:"
PASSED = []
FAILED = []
CLEANUP = []


def http(url, body=None, token=None, method=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            j = json.loads(raw) if raw else {}
        except ValueError:
            j = {"raw": raw}
        return e.code, j


def fv(x):
    if x is None:
        return {"nullValue": None}
    if isinstance(x, bool):
        return {"booleanValue": x}
    if isinstance(x, int):
        return {"integerValue": str(x)}
    if isinstance(x, float):
        return {"doubleValue": x}
    if isinstance(x, str):
        return {"stringValue": x}
    if isinstance(x, dict):
        return {"mapValue": {"fields": {k: fv(v) for k, v in x.items()}}}
    if isinstance(x, list):
        return {"arrayValue": {"values": [fv(v) for v in x]}}
    raise TypeError(type(x))


def fields(d):
    return {k: fv(v) for k, v in d.items()}


def sign_up(tag):
    email = "rltest%s%s@example.com" % (int(time.time()), random.randint(1000, 9999))
    st, j = http(AUTH + "signUp?key=" + API_KEY, {"email": email, "password": "T3st!pass", "returnSecureToken": True})
    if st != 200:
        print("SIGNUP FAILED", st, j)
        sys.exit(1)
    return {"email": email, "token": j["idToken"], "uid": j["localId"]}


def create(coll, data, token, docid=None):
    url = BASE + "/" + coll + (("?documentId=" + docid) if docid else "")
    st, j = http(url, {"fields": fields(data)}, token)
    return st, j


def doc_id(name):
    return name.split("/")[-1]


def get_doc(path, token):
    return http(BASE + "/" + path, None, token)


def commit(writes, token):
    return http(BASE + ":commit", {"writes": writes}, token)


def update_fields(path, data, token):
    w = {
        "update": {
            "name": "projects/%s/databases/(default)/documents/%s" % (PROJECT, path),
            "fields": fields(data),
        },
        "updateMask": {"fieldPaths": list(data.keys())},
    }
    return commit([w], token)


def delete(path, token):
    return http(BASE + "/" + path, None, token, method="DELETE")


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  PASS  " + name)
    else:
        FAILED.append(name + (" | " + detail if detail else ""))
        print("  FAIL  " + name + (" | " + detail if detail else ""))


def is_denied(st):
    return st in (403, 401, 400, 404)


def user_doc(name, invite, xp=0):
    return {
        "name": name, "av": "😺", "col": "#6366f1", "invite": invite,
        "friends": [], "xp": xp, "day": 0, "week": 0, "days": {},
        "privacy": {"share": True}, "created": int(time.time() * 1000),
    }


def main():
    print("== ساخت حساب‌های تستی ==")
    A = sign_up("A")
    B = sign_up("B")
    C = sign_up("C")
    U = {A["uid"]: A, B["uid"]: B, C["uid"]: C}
    inv = {}
    for u in (A, B, C):
        inv[u["uid"]] = "T" + "".join(random.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(5))

    print("== آماده‌سازی داده ==")
    for u in (A, B, C):
        st, _ = create("users", user_doc("کاربر " + u["uid"][:4], inv[u["uid"]]), u["token"], u["uid"])
        assert st == 200, "create user failed %s" % st
        CLEANUP.append(("users/" + u["uid"], u["token"]))
        st, _ = create("invites", {"uid": u["uid"], "exp": int(time.time() * 1000) + 86400000 * 30}, u["token"], inv[u["uid"]])
        assert st == 200, "create invite failed %s" % st
        CLEANUP.append(("invites/" + inv[u["uid"]], u["token"]))

    st, _ = create("publicProfiles", {
        "name": "B", "av": "😺", "col": "#6366f1", "day": 0, "week": 0, "days": {},
        "privacy": {"share": True, "name": True, "score": True, "medals": True, "cat": True, "feed": True, "online": False},
        "cat": None, "bd": 0, "seen": 0,
    }, B["token"], B["uid"])
    assert st == 200, "create publicProfile failed %s" % st
    CLEANUP.append(("publicProfiles/" + B["uid"], B["token"]))

    st, _ = create("friendships", {"links": {A["uid"]: True}}, B["token"], B["uid"])
    assert st == 200, "create friendship failed %s" % st
    CLEANUP.append(("friendships/" + B["uid"], B["token"]))

    print("== users ==")
    check("A سند خودش را می‌خواند", get_doc("users/" + A["uid"], A["token"])[0] == 200)
    check("A سند B را نمی‌خواند", is_denied(get_doc("users/" + B["uid"], A["token"])[0]))
    check("A لیست users را نمی‌گیرد", is_denied(http(BASE + "/users", None, A["token"])[0]))
    check("A برای B سند نمی‌سازد", is_denied(create("users", user_doc("x", "ABC234"), A["token"])[0]))
    check("افزایش +۱۰۰ XP مجاز", update_fields("users/" + A["uid"], {"xp": 100}, A["token"])[0] == 200)
    check("افزایش +۱۰۱ XP رد می‌شود", is_denied(update_fields("users/" + A["uid"], {"xp": 201}, A["token"])[0]))
    check("تغییر invite ممنوع", is_denied(update_fields("users/" + A["uid"], {"invite": "HACK99"}, A["token"])[0]))
    check("تغییر created ممنوع", is_denied(update_fields("users/" + A["uid"], {"created": 1}, A["token"])[0]))
    check("blocked غیر-map رد می‌شود", is_denied(update_fields("users/" + A["uid"], {"blocked": "x"}, A["token"])[0]))
    check("blocked map مجاز است", update_fields("users/" + A["uid"], {"blocked": {"zzz": True}, "blockedNames": {"zzz": "x"}}, A["token"])[0] == 200)
    check("blocked بیش از ۲۰۰ رد می‌شود", is_denied(update_fields("users/" + A["uid"], {"blocked": {("k%d" % i): True for i in range(201)}}, A["token"])[0]))

    print("== publicProfiles ==")
    check("A پروفایل B را نمی‌نویسد", is_denied(http(BASE + "/publicProfiles/" + B["uid"], {"fields": fields({"name": "hack"})}, A["token"], method="PATCH")[0]))
    check("B پروفایل خودش را می‌نویسد", http(BASE + "/publicProfiles/" + B["uid"], {"fields": fields({
        "name": "B", "av": "😺", "col": "#6366f1", "day": 0, "week": 0, "days": {},
        "privacy": {"share": True, "name": True, "score": True, "medals": True, "cat": True, "feed": True, "online": False},
        "cat": None, "bd": 0, "seen": 0})}, B["token"], method="PATCH")[0] == 200)

    print("== friendships ==")
    check("A سند friendships خودش را می‌سازد", create("friendships", {"links": {B["uid"]: True}}, A["token"], A["uid"])[0] == 200)
    CLEANUP.append(("friendships/" + A["uid"], A["token"]))
    check("A سند friendships مربوط به B را تغییر نمی‌دهد", is_denied(http(BASE + "/friendships/" + B["uid"], {"fields": fields({"links": {A["uid"]: False}})}, A["token"], method="PATCH")[0]))

    print("== invite ==")
    check("تمدید invite با exp ۳۰ روزه", http(BASE + "/invites/" + inv[A["uid"]], {"fields": fields({"uid": A["uid"], "exp": int(time.time() * 1000) + 86400000 * 30})}, A["token"], method="PATCH")[0] == 200)
    check("invite با exp بیش از ۴۰ روز رد می‌شود", is_denied(http(BASE + "/invites/" + inv[A["uid"]], {"fields": fields({"uid": A["uid"], "exp": int(time.time() * 1000) + 86400000 * 60})}, A["token"], method="PATCH")[0]))

    print("== فید و واکنش ==")
    st, j = create("feed/%s/posts" % B["uid"], {"uid": B["uid"], "name": "B", "av": "😺", "col": "#6366f1", "txt": "سلام", "t": int(time.time() * 1000), "re": {}}, B["token"])
    assert st == 200, "post create failed %s" % st
    pid = doc_id(j["name"])
    CLEANUP.append(("feed/%s/posts/%s" % (B["uid"], pid), B["token"]))
    check("A پست B را می‌خواند (دوستی دوطرفه)", get_doc("feed/%s/posts/%s" % (B["uid"], pid), A["token"])[0] == 200)
    check("C پست B را نمی‌خواند", is_denied(get_doc("feed/%s/posts/%s" % (B["uid"], pid), C["token"])[0]))
    check("A واکنش مجاز می‌زند", commit([{
        "update": {"name": "projects/%s/databases/(default)/documents/feed/%s/posts/%s" % (PROJECT, B["uid"], pid),
                   "fields": fields({"re": {A["uid"]: "🔥"}})},
        "updateMask": {"fieldPaths": ["re"]}}, ], A["token"])[0] == 200)
    check("واکنش غیرمجاز رد می‌شود", is_denied(commit([{
        "update": {"name": "projects/%s/databases/(default)/documents/feed/%s/posts/%s" % (PROJECT, B["uid"], pid),
                   "fields": fields({"re": {A["uid"]: "😈"}})},
        "updateMask": {"fieldPaths": ["re"]}}, ], A["token"])[0]))
    check("واکنش برای دیگری رد می‌شود", is_denied(commit([{
        "update": {"name": "projects/%s/databases/(default)/documents/feed/%s/posts/%s" % (PROJECT, B["uid"], pid),
                   "fields": fields({"re": {C["uid"]: "🔥"}})},
        "updateMask": {"fieldPaths": ["re"]}}, ], A["token"])[0]))
    check("C واکنش نمی‌زند", is_denied(commit([{
        "update": {"name": "projects/%s/databases/(default)/documents/feed/%s/posts/%s" % (PROJECT, B["uid"], pid),
                   "fields": fields({"re": {C["uid"]: "🔥"}})},
        "updateMask": {"fieldPaths": ["re"]}}, ], C["token"])[0]))
    check("A پست B را حذف نمی‌کند", is_denied(delete("feed/%s/posts/%s" % (B["uid"], pid), A["token"])[0]))
    check("A در فید B پست نمی‌گذارد", is_denied(create("feed/%s/posts" % B["uid"], {"uid": B["uid"], "name": "A", "av": "😺", "col": "#6366f1", "txt": "x", "t": 1, "re": {}}, A["token"])[0]))

    print("== بلاک ==")
    check("B، A را بلاک می‌کند", update_fields("users/" + B["uid"], {"blocked": {A["uid"]: True}, "blockedNames": {A["uid"]: "A"}}, B["token"])[0] == 200)
    check("بعد از بلاک، A پست B را نمی‌خواند", is_denied(get_doc("feed/%s/posts/%s" % (B["uid"], pid), A["token"])[0]))
    check("بعد از بلاک، A واکنش نمی‌زند", is_denied(commit([{
        "update": {"name": "projects/%s/databases/(default)/documents/feed/%s/posts/%s" % (PROJECT, B["uid"], pid),
                   "fields": fields({"re": {A["uid"]: "❤️"}})},
        "updateMask": {"fieldPaths": ["re"]}}, ], A["token"])[0]))

    print("== گزارش ==")
    st, jr = create("reports", {"by": C["uid"], "target": B["uid"], "pid": pid, "reason": "تست گزارش", "t": int(time.time() * 1000)}, C["token"])
    check("گزارش معتبر ساخته می‌شود", st == 200, str(st))
    if st == 200:
        CLEANUP.append(("reports/" + doc_id(jr["name"]), C["token"]))
    check("گزارش بدون دلیل رد می‌شود", is_denied(create("reports", {"by": C["uid"], "target": B["uid"], "pid": pid, "reason": "", "t": 1}, C["token"])[0]))
    check("گزارش خودبه‌خود برای دیگری رد می‌شود", is_denied(create("reports", {"by": A["uid"], "target": B["uid"], "pid": pid, "reason": "x", "t": 1}, C["token"])[0]))
    check("خواندن گزارش‌ها توسط A ممنوع", is_denied(http(BASE + "/reports", None, A["token"])[0]))

    print("== اتاق‌ها ==")
    now = int(time.time() * 1000)
    st, jroom = create("rooms", {"h": A["uid"], "hn": "A", "hav": "😺", "type": "day", "t": now, "exp": now + 7 * 86400000, "s": {A["uid"]: 0}, "g": None}, A["token"])
    assert st == 200, "room create failed %s" % st
    rid = doc_id(jroom["name"])
    CLEANUP.append(("rooms/" + rid, A["token"]))
    check("اتاق بدون exp رد می‌شود", is_denied(create("rooms", {"h": A["uid"], "hn": "A", "hav": "😺", "type": "day", "t": now, "s": {A["uid"]: 0}, "g": None}, A["token"])[0]))
    check("اتاق با exp بیش از ۸ روز رد می‌شود", is_denied(create("rooms", {"h": A["uid"], "hn": "A", "hav": "😺", "type": "day", "t": now, "exp": now + 9 * 86400000, "s": {A["uid"]: 0}, "g": None}, A["token"])[0]))
    check("B قبل از پیوستن اتاق را نمی‌خواند", is_denied(get_doc("rooms/" + rid, B["token"])[0]))
    check("C اتاق را نمی‌خواند", is_denied(get_doc("rooms/" + rid, C["token"])[0]))
    check("B با update اتمی می‌پیوندد", update_fields("rooms/" + rid, {"g": B["uid"], "gnn": "B", "gav": "😺"}, B["token"])[0] == 200)
    check("B بعد از پیوستن می‌خواند", get_doc("rooms/" + rid, B["token"])[0] == 200)
    check("B امتیاز A را تغییر نمی‌دهد", is_denied(commit([{
        "update": {"name": "projects/%s/databases/(default)/documents/rooms/%s" % (PROJECT, rid),
                   "fields": fields({"s": {A["uid"]: 9999}})},
        "updateMask": {"fieldPaths": ["s"]}}, ], B["token"])[0]))
    check("C هنوز اتاق را نمی‌خواند", is_denied(get_doc("rooms/" + rid, C["token"])[0]))
    check("B از اتاق خارج می‌شود", update_fields("rooms/" + rid, {"g": None, "gnn": "", "gav": ""}, B["token"])[0] == 200)
    check("میزبان اتاق را حذف می‌کند", delete("rooms/" + rid, A["token"])[0] == 200)

    print("== انقضای اتاق ==")
    exp_soon = int(time.time() * 1000) + 6000
    st, jexp = create("rooms", {"h": A["uid"], "hn": "A", "hav": "😺", "type": "day", "t": now, "exp": exp_soon, "s": {A["uid"]: 0}, "g": None}, A["token"])
    check("اتاق کوتاه‌عمر ساخته می‌شود", st == 200, str(st))
    if st == 200:
        xid = doc_id(jexp["name"])
        CLEANUP.append(("rooms/" + xid, A["token"]))
        check("قبل از انقضا عضو می‌خواند", get_doc("rooms/" + xid, A["token"])[0] == 200)
        time.sleep(7.0)
        check("بعد از انقضا خواندن رد می‌شود", is_denied(get_doc("rooms/" + xid, A["token"])[0]))
        check("بعد از انقضا پیوستن رد می‌شود", is_denied(update_fields("rooms/" + xid, {"g": B["uid"], "gnn": "B", "gav": "😺"}, B["token"])[0]))
        check("بعد از انقضا امتیازنویسی رد می‌شود", is_denied(update_fields("rooms/" + xid, {"s": {A["uid"]: 50}}, A["token"])[0]))
        check("میزبان اتاق منقضی را حذف می‌کند", delete("rooms/" + xid, A["token"])[0] == 200)

    print("== همگام‌سازی رمزدار ==")
    st, _ = create("sync", {"blob": "ENC1:x|y|z", "rev": 1, "t": now, "dv": "dtest"}, A["token"], A["uid"])
    check("سند sync خودم ساخته می‌شود", st == 200, str(st))
    CLEANUP.append(("sync/" + A["uid"], A["token"]))
    check("خواندن sync دیگران ممنوع", is_denied(get_doc("sync/" + B["uid"], A["token"])[0]))
    check("نوشتن sync دیگری ممنوع", is_denied(http(BASE + "/sync/" + B["uid"], {"fields": fields({"blob": "x", "rev": 1, "t": 1, "dv": "d"})}, A["token"], method="PATCH")[0]))
    check("sync بدون rev رد می‌شود", is_denied(create("sync", {"blob": "x", "t": 1, "dv": "d"}, A["token"], A["uid"])[0]))
    check("sync بزرگ‌تر از سقف رد می‌شود", is_denied(http(BASE + "/sync/" + A["uid"], {"fields": fields({"blob": "x" * 900001, "rev": 2, "t": 1, "dv": "d"})}, A["token"], method="PATCH")[0]))
    check("لیست sync ممنوع", is_denied(http(BASE + "/sync", None, A["token"])[0]))

    print("== پشتیبان و مجموعه‌های رزرو ==")
    check("backup بزرگ‌تر از سقف رد می‌شود", is_denied(create("backups", {"blob": "x" * 900001, "t": 1, "v": 2}, A["token"], A["uid"])[0]))
    check("نوشتن نقطه‌تراکنش ممنوع", is_denied(create("pointTransactions/%s/items" % A["uid"], {"amt": 9999}, A["token"])[0]))
    check("خواندن نقطه‌تراکنش دیگران ممنوع", is_denied(http(BASE + "/pointTransactions/" + B["uid"] + "/items", None, A["token"])[0]))

    print("== پاک‌سازی ==")
    for path, tok in reversed(CLEANUP):
        delete(path, tok)
    for u in U.values():
        http(AUTH + "delete?key=" + API_KEY, {"idToken": u["token"]})

    print("\n%d PASSED, %d FAILED" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("FAILED:", f)
    sys.exit(0 if not FAILED else 1)


if __name__ == "__main__":
    main()
