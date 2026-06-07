import { Mic } from "lucide-react";
import { useRef, useState } from "react";
import { useToast } from "../toast";

// Speech-to-text using the Web Speech API when the webview supports it.
export function VoiceButton({ onTranscript }: { onTranscript: (text: string) => void }): JSX.Element {
  const toast = useToast();
  const [listening, setListening] = useState(false);
  const recRef = useRef<{ stop: () => void } | null>(null);

  const start = (): void => {
    const w = window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };
    const SR = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as
      | (new () => {
          lang: string;
          interimResults: boolean;
          onresult: (e: { results: { [i: number]: { [j: number]: { transcript: string } } } }) => void;
          onerror: () => void;
          onend: () => void;
          start: () => void;
          stop: () => void;
        })
      | undefined;
    if (!SR) {
      toast.push("Voice input isn't supported in this window", "error");
      return;
    }
    const rec = new SR();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => onTranscript(e.results[0][0].transcript + " ");
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    rec.start();
    recRef.current = rec;
    setListening(true);
  };

  return (
    <button
      className={`icon-btn ${listening ? "recording" : ""}`}
      title={listening ? "Stop dictation" : "Voice input"}
      onClick={() => (listening ? recRef.current?.stop() : start())}
    >
      <Mic size={18} />
    </button>
  );
}
