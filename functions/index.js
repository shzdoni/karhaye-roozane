/**
 * توابع سرور «کارهای روزانه» — منبع مرجع؛ در این نسخه مستقر نشده است.
 *
 * فعال‌سازی: پلن Blaze + Firebase CLI + Node 20، سپس
 *   cd functions && npm install && firebase deploy --only functions
 * سپس قوانین stage2 (firebase-rules/firestore.rules.stage2) را منتشر کن تا
 * نوشتن مستقیم XP از مرورگر بسته شود. تا آن زمان امتیاز فقط با قوانین
 * محدودکننده‌ی سمت کلاینت کنترل می‌شود و تضمین کامل ضدتقلب ندارد.
 */
const { onCall, HttpsError } = require("firebase-functions/v2/https");
const { onSchedule } = require("firebase-functions/v2/scheduler");
const admin = require("firebase-admin");

admin.initializeApp();
const db = admin.firestore();

// هزینه‌ی هر عملیات فقط اینجا تعیین می‌شود؛ کلاینت هیچ عددی نمی‌فرستد.
const ACTION_COSTS = {
  taskDone: 5,
  fullDay: 20,
  gameWin: 10,
  riddleSolved: 8,
  catCare: 4,
  missionDone: 10,
};
const ACTION_COINS = {
  taskDone: 1,
  fullDay: 5,
  gameWin: 3,
  riddleSolved: 2,
  catCare: 1,
  missionDone: 3,
};
const DAILY_CAP = 300;
const WEEKLY_CAP = 500;
const ENFORCE_APPCHECK = process.env.ENFORCE_APPCHECK === "true";

function dayKeyUTC(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}
function weekKeyUTC(ms) {
  const d = new Date(ms);
  const day = (d.getUTCDay() + 6) % 7; // دوشنبه = 0
  const mon = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day));
  return mon.toISOString().slice(0, 10);
}

// پاداش اتمیک با شناسه‌ی یکتا؛ تکرار همان txId پاداش دوباره نمی‌دهد.
exports.awardPoints = onCall({ enforceAppCheck: ENFORCE_APPCHECK, region: "us-central1" }, async (req) => {
  if (!req.auth) throw new HttpsError("unauthenticated", "ورود لازم است");
  const uid = req.auth.uid;
  const action = String((req.data && req.data.action) || "");
  const txId = String((req.data && req.data.txId) || "");
  if (!Object.prototype.hasOwnProperty.call(ACTION_COSTS, action)) {
    throw new HttpsError("invalid-argument", "عملیات نامعتبر");
  }
  if (!/^[a-zA-Z0-9_-]{8,64}$/.test(txId)) {
    throw new HttpsError("invalid-argument", "شناسه تراکنش نامعتبر");
  }
  const now = admin.firestore.Timestamp.now().toMillis(); // ساعت سرور
  const day = dayKeyUTC(now);
  const week = weekKeyUTC(now);
  const cost = ACTION_COSTS[action];
  const coins = ACTION_COINS[action];
  const userRef = db.doc(`users/${uid}`);
  const txRef = db.doc(`pointTransactions/${uid}/items/${day}_${txId}`);

  return db.runTransaction(async (tx) => {
    const [dup, snap] = await Promise.all([tx.get(txRef), tx.get(userRef)]);
    if (!snap.exists) throw new HttpsError("not-found", "کاربر پیدا نشد");
    const u = snap.data();
    const xp = Math.max(0, Number(u.xp) || 0);
    const coinsBal = Math.max(0, Number(u.coins) || 0);
    const dayTotal = u.xpDayStart === day ? Math.max(0, Number(u.xpDayTotal) || 0) : 0;
    const weekTotal = u.weekStart === week ? Math.max(0, Number(u.weekTotal) || 0) : 0;
    if (dup.exists) {
      return { ok: true, dup: true, awarded: 0, coins: 0, xp, dayTotal, weekTotal };
    }
    const room = Math.max(0, Math.min(cost, DAILY_CAP - dayTotal, WEEKLY_CAP - weekTotal));
    if (room <= 0) {
      throw new HttpsError("resource-exhausted", "سقف امتیاز روز/هفته پر شده");
    }
    const newDay = dayTotal + room;
    const newWeek = weekTotal + room;
    tx.set(userRef, {
      xp: xp + room,
      coins: coinsBal + Math.round((coins * room) / cost),
      xpDayStart: day,
      xpDayTotal: newDay,
      weekStart: week,
      weekTotal: newWeek,
      updated: admin.firestore.FieldValue.serverTimestamp(),
    }, { merge: true });
    tx.set(txRef, { uid, action, cost: room, coins, day, week, at: now });
    return { ok: true, dup: false, awarded: room, coins: Math.round((coins * room) / cost), xp: xp + room, dayTotal: newDay, weekTotal: newWeek };
  });
});

// حذف آبشاری و قابل‌ادامه‌ی همه‌ی داده‌های وابسته به UID؛ Auth آخر کار.
// پیشرفت در deletions/{uid} ذخیره می‌شود تا اجرای نیمه‌کاره از همان‌جا ادامه یابد.
exports.accountDelete = onCall({ enforceAppCheck: ENFORCE_APPCHECK, region: "us-central1", timeoutSeconds: 540 }, async (req) => {
  if (!req.auth) throw new HttpsError("unauthenticated", "ورود لازم است");
  const uid = req.auth.uid;
  const progressRef = db.doc(`deletions/${uid}`);
  const counts = { posts: 0, legacyPosts: 0, reactions: 0, reports: 0, rooms: 0, roomsLeft: 0, invites: 0, sync: 0 };
  const bump = (k, n) => { counts[k] += n || 0; };

  async function eachPage(query, fn, size = 200) {
    for (;;) {
      const qs = await query.limit(size).get();
      if (qs.empty) return;
      for (const d of qs.docs) await fn(d);
      if (qs.size < size) return;
    }
  }

  await progressRef.set({ status: "running", startedAt: admin.firestore.FieldValue.serverTimestamp(), uid }, { merge: true });

  try {
    // واکنش‌های من روی پست دیگران (بدون Admin SDK ممکن نیست)
    await eachPage(
      db.collectionGroup("posts").where(`re.${uid}`, "!=", null),
      async (d) => {
        const patch = {};
        patch[`re.${uid}`] = admin.firestore.FieldValue.delete();
        await d.ref.update(patch);
        bump("reactions");
      }
    );
    await eachPage(db.collection("feed").doc(uid).collection("posts"), async (d) => { await d.ref.delete(); bump("posts"); });
    await eachPage(db.collection("feed").where("uid", "==", uid), async (d) => { await d.ref.delete(); bump("legacyPosts"); });
    await eachPage(db.collection("reports").where("by", "==", uid), async (d) => { await d.ref.delete(); bump("reports"); });
    await eachPage(db.collection("rooms").where("h", "==", uid), async (d) => { await d.ref.delete(); bump("rooms"); });
    await eachPage(db.collection("rooms").where("g", "==", uid), async (d) => {
      await d.ref.update({ g: null, gnn: "", gav: "" }); bump("roomsLeft");
    });
    await eachPage(db.collection("invites").where("uid", "==", uid), async (d) => { await d.ref.delete(); bump("invites"); });
    if ((await db.doc(`sync/${uid}`).get()).exists) { bump("sync", 1); }
    const singles = ["users", "publicProfiles", "friendships", "backups", "sync"];
    for (const c of singles) {
      try { await db.doc(`${c}/${uid}`).delete(); } catch (e) { /* سند نبود */ }
    }
    await progressRef.set({ status: "done", finishedAt: admin.firestore.FieldValue.serverTimestamp(), counts }, { merge: true });
    await admin.auth().deleteUser(uid); // فقط بعد از موفقیت پاک‌سازی
    return { ok: true, counts };
  } catch (e) {
    await progressRef.set({ status: "partial", error: String(e && e.message || e), counts }, { merge: true });
    throw new HttpsError("internal", "پاک‌سازی کامل نشد؛ دوباره تلاش کن");
  }
});

// پاک‌سازی زمان‌بندی‌شده‌ی اتاق‌های منقضی و اتاق‌های قدیمی بدون exp
// هر اجرا حداکثر ۵ دسته‌ی ۴۰۰تایی (سقف batch فایربیس ۵۰۰ عملیات است) و قابل تکرار/idempotent.
exports.expireRooms = onSchedule({ schedule: "every 60 minutes", region: "us-central1", timeoutSeconds: 300 }, async () => {
  const now = Date.now();
  let deleted = 0, rounds = 0;
  async function sweep(query, filter) {
    while (rounds < 5) {
      rounds++;
      const qs = await query.limit(400).get();
      if (qs.empty) return;
      const docs = filter ? qs.docs.filter(filter) : qs.docs;
      if (!docs.length) return;
      const batch = db.batch();
      docs.forEach((d) => batch.delete(d.ref));
      await batch.commit();
      deleted += docs.length;
      if (qs.size < 400) return;
    }
  }
  await sweep(db.collection("rooms").where("exp", "<", now));
  await sweep(db.collection("rooms").where("t", "<", now - 8 * 86400000), (d) => !d.data().exp);
  return { deleted };
});
