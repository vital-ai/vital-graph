import { useCallback, useRef } from 'react';

/**
 * Guard against an older in-flight request overwriting a newer one.
 *
 * List pages refetch whenever a control changes — space, graph, search, sort,
 * page. Change two in quick succession and both requests are in flight; if the
 * OLDER one resolves last it overwrites the newer result, and the table is left
 * showing stale data with nothing to trigger another fetch. It is not a
 * theoretical race: it was traced repeatedly, with margins as small as 3 ms.
 *
 * ```
 *   const beginRequest = useLatestRequest();
 *
 *   const load = useCallback(async () => {
 *     const isStale = beginRequest();
 *     try {
 *       const data = await api.fetch(...);
 *       if (isStale()) return;          // a newer request already answered
 *       setRows(data);
 *     } catch (e) {
 *       if (isStale()) return;          // do not report a superseded failure
 *       setError(e);
 *     } finally {
 *       if (!isStale()) setLoading(false);
 *     }
 *   }, [deps, beginRequest]);
 * ```
 *
 * Note `isStale()` is checked in `finally` too: a superseded request must not
 * clear the loading flag, or the UI shows "done" while the current request is
 * still running.
 *
 * This deliberately does not abort the HTTP request. Aborting would be a larger
 * change (every service call would need to thread an AbortSignal) and does not
 * fix the bug — discarding the response is what makes the newest write win.
 *
 * @returns `beginRequest`, called at the start of each fetch. It claims the
 *          latest slot and returns an `isStale()` predicate for that request.
 */
export function useLatestRequest(): () => () => boolean {
  const seq = useRef(0);

  return useCallback(() => {
    const mine = ++seq.current;
    return () => mine !== seq.current;
  }, []);
}

export default useLatestRequest;
