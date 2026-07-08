// Generic real-time Firestore listener, tenant-scoped. Returns live documents
// for a collection filtered by tenant_id, ordered by created_at when present.

import { useEffect, useState } from "react";
import {
  collection,
  onSnapshot,
  query,
  where,
  type QueryConstraint,
} from "firebase/firestore";
import { firestore } from "../firebase";

export function useTenantCollection<T>(
  collectionName: string,
  tenantId: string | undefined,
  extraConstraints: QueryConstraint[] = [],
): { data: T[]; error: string | null } {
  const [data, setData] = useState<T[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId) {
      setData([]);
      return;
    }
    const q = query(
      collection(firestore(), collectionName),
      where("tenant_id", "==", tenantId),
      ...extraConstraints,
    );
    const unsub = onSnapshot(
      q,
      (snap) => {
        setData(snap.docs.map((d) => d.data() as T));
        setError(null);
      },
      (err) => setError(err.message),
    );
    return () => unsub();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectionName, tenantId]);

  return { data, error };
}
