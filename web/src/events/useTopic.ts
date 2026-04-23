import { useEffect, useState } from "react";
import { useEventStream } from "./EventStream";
import type { SseEnvelope } from "./connection";

export function useTopic(topic: string, type?: string) {
  const { subscribe } = useEventStream();
  const [last, setLast] = useState<SseEnvelope | null>(null);
  useEffect(() => {
    return subscribe(topic, (e) => {
      if (!type || e.type === type) setLast(e);
    });
  }, [subscribe, topic, type]);
  return last;
}

export function useTopicCounter(topic: string) {
  const { subscribe } = useEventStream();
  const [count, setCount] = useState(0);
  useEffect(() => subscribe(topic, () => setCount((c) => c + 1)), [subscribe, topic]);
  return count;
}
