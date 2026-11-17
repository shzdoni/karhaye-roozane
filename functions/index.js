/**
 * منبع مرجع امتیازدهی سمت سرور — «مستقر نشده».
 *
 * این فایل در این مخزن فقط به‌عنوان پیاده‌سازی مرجع نگه داشته می‌شود و کلاینت
 * به آن وصل نیست. برای فعال‌سازی واقعی: پروژه باید پلن Blaze داشته باشد،
 * Firebase CLI و Node نصب باشد، سپس:
 *   cd functions && npm install && firebase deploy --only functions
 * تا آن زمان امتیازها در Firestore با قوانین محدودکننده‌ی سمت کلاینت کنترل
 * می‌شوند (سقف XP هر آپدیت، سقف روز/هفته) و «صحت کامل امتیاز» تضمین‌شده نیست.
 */
const functions = require("firebase-functions");
const admin = require("firebase-admin");

admin.initializeApp();
const db = admin.firestore();

// هزینه‌ی ثابت هر عملیات؛ کلاینت هیچ عددی نمی‌فرستد
const ACTION_COSTS = {
  taskDone: 5,
  fullDay: 20,
  gameWin: 10,
  riddleSolved: 8,
  catCare: 4,
};
const DAILY_CAP = 300;
const WEEKLY_CAP = 500;

function dayKeyUTC(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

exports.awardPoints = functions.https.onCall(async (data, context) => {
  if (!context.auth) {
    throw new functions.https.HttpsError("unauthenticated", "ورود لازم است");
  }
  const uid = context.auth.uid;
  const action = String(data && data.action || "");
  const txId = String(data && data.txId || "");
  const cost = ACTION_COSTS[action];
  if (!cost) {
    throw new functions.https.HttpsError("invalid-argument", "عملیات نامعتبر");
  }
  if (!/^[a-zA-Z0-9_-]{8,64}$/.test(txId)) {
    throw new functions.https.HttpsError("invalid-argument", "شناسه تراکنش نامعتبر");
  }
  const now = Date.now();
  const day = dayKeyUTC(now);
  const week = dayKeyUTC(now - ((now % 604800000)));

  const dayRef = db.doc(`pointTransactions/${uid}/items/${day + "_" + txId}`);
  return db.runTransaction(async (tx) => {
    const userRef = db.doc(`users/${uid}`);
    const [dup, userSnap] = await Promise.all([tx.get(dayRef), tx.get(userRef)]);
    if (dup.exists) {
      throw new functions.https.HttpsError("already-exists", "این پاداش قبلاً ثبت شده");
    }
    if (!userSnap.exists) {
      throw new functions.https.HttpsError("not-found", "کاربر پیدا نشد");
    }
    const u = userSnap.data();
    const xp = Number(u.xp) || 0;
    const xpDay = u.xpDayStart === day ? (Number(u.xpDayTotal) || 0) : 0;
    const weekTotal = u.weekStart === week ? (Number(u.weekTotal) || 0) : 0;
    if (xpDay + cost > DAILY_CAP || weekTotal + cost > WEEKLY_CAP) {
      throw new functions.https.HttpsError("resource-exhausted", "سقف امتیاز روز/هفته پر شده");
    }
    tx.set(userRef, {
      xp: xp + cost,
      xpDayStart: day,
      xpDayTotal: xpDay + cost,
      weekStart: week,
      weekTotal: weekTotal + cost,
    }, { merge: true });
    tx.set(dayRef, { action, cost, at: now, uid, day, week });
    return { ok: true, awarded: cost, xp: xp + cost, dayTotal: xpDay + cost };
  });
});
