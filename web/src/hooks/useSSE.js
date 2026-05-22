import { useEffect, useRef, useState } from "react";
import { getApiBaseUrl } from "../api/client";

const RECONNECT_MS = 3000;

export default function useSSE(path = "/api/events") {
  const [lastEvent, setLastEvent] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [status, setStatus] = useState("connecting");
  const retryRef = useRef(null);
  const sourceRef = useRef(null);

  useEffect(() => {
    const connect = () => {
      const source = new EventSource(`${getApiBaseUrl()}${path}`);
      sourceRef.current = source;
      setStatus("connecting");

      source.onopen = () => {
        setIsConnected(true);
        setStatus("connected");
      };

      source.onmessage = (event) => {
        setIsConnected(true);
        setStatus("connected");
        try {
          setLastEvent(JSON.parse(event.data));
        } catch {
          setLastEvent({ type: "raw", payload: event.data });
        }
      };

      source.onerror = () => {
        setIsConnected(false);
        setStatus("reconnecting");
        source.close();
        retryRef.current = window.setTimeout(connect, RECONNECT_MS);
      };
    };

    connect();

    return () => {
      if (retryRef.current) {
        window.clearTimeout(retryRef.current);
      }
      if (sourceRef.current) {
        sourceRef.current.close();
      }
      setIsConnected(false);
      setStatus("disconnected");
    };
  }, [path]);

  return { lastEvent, isConnected, status };
}
