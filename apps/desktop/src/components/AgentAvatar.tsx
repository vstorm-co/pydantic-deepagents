import { Bot } from "lucide-react";

// Renders an avatar image (data URL / http / path with an image extension).
// When no image is set it falls back to a clean coloured tile with a glyph —
// emojis are no longer used as avatars.

function isImage(avatar: string): boolean {
  return (
    avatar.startsWith("data:") ||
    avatar.startsWith("http") ||
    avatar.startsWith("blob:") ||
    /\.(png|jpe?g|gif|webp|svg)$/i.test(avatar)
  );
}

export function AgentAvatar({
  avatar,
  color = "#4493f8",
  size = 28,
  radius,
  className = "",
}: {
  avatar: string;
  color?: string;
  size?: number;
  radius?: number;
  className?: string;
}): JSX.Element {
  const img = isImage(avatar);
  return (
    <span
      className={`avatar ${className}`}
      style={{
        width: size,
        height: size,
        flex: `0 0 ${size}px`,
        borderRadius: radius ?? Math.round(size * 0.28),
        background: img ? "var(--bg-3)" : color,
        color: "#fff",
        fontSize: Math.round(size * 0.5),
        overflow: "hidden",
      }}
    >
      {img ? (
        <img src={avatar} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ) : (
        <Bot size={Math.round(size * 0.56)} />
      )}
    </span>
  );
}
