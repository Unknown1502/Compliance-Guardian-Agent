// Firebase / Firestore initialization.
//
// The dashboard reads Firestore in real time (onSnapshot) for live task/check
// updates, and uses the API Gateway for all writes/actions. In local dev it
// connects to the Firestore emulator; in production it uses real Firestore with
// security rules (see infra: firestore.rules) enforcing tenant isolation.

import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  connectFirestoreEmulator,
  getFirestore,
  type Firestore,
} from "firebase/firestore";
import { getAuth, type Auth } from "firebase/auth";
import { FIREBASE_CONFIG, FIRESTORE_EMULATOR_HOST, GCP_PROJECT } from "./config";

let app: FirebaseApp | null = null;
let db: Firestore | null = null;
let authInstance: Auth | null = null;

export function firebaseApp(): FirebaseApp {
  if (!app) {
    app = initializeApp({
      apiKey: FIREBASE_CONFIG.apiKey || "dev-key",
      authDomain: FIREBASE_CONFIG.authDomain || `${GCP_PROJECT}.firebaseapp.com`,
      projectId: FIREBASE_CONFIG.projectId || GCP_PROJECT,
    });
  }
  return app;
}

export function firestore(): Firestore {
  if (!db) {
    db = getFirestore(firebaseApp());
    if (FIRESTORE_EMULATOR_HOST) {
      const [host, port] = FIRESTORE_EMULATOR_HOST.split(":");
      connectFirestoreEmulator(db, host, Number(port));
    }
  }
  return db;
}

export function firebaseAuth(): Auth {
  if (!authInstance) {
    authInstance = getAuth(firebaseApp());
  }
  return authInstance;
}
