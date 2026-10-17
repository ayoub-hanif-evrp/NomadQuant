"use client";

import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/cn";

export type CrewId =
  | "copilot"
  | "scout"
  | "researcher"
  | "skeptic"
  | "reviewer"
  | "verifier"
  | "risk";

export type CrewMood = "idle" | "working" | "success" | "concern" | "failed" | "replay" | "offline";

const ACCENT: Record<CrewId, { fill: string; glow: string; name: string }> = {
  copilot: { fill: "#f2d58a", glow: "rgba(242,213,138,0.45)", name: "Nomad Copilot" },
  scout: { fill: "#7ec8a3", glow: "rgba(126,200,163,0.4)", name: "News Scout" },
  researcher: { fill: "#7ec8e8", glow: "rgba(126,200,232,0.4)", name: "Researcher" },
  skeptic: { fill: "#e7a35c", glow: "rgba(231,163,92,0.4)", name: "Skeptic" },
  reviewer: { fill: "#9fb3c8", glow: "rgba(159,179,200,0.4)", name: "Reviewer" },
  verifier: { fill: "#d4a73c", glow: "rgba(212,167,60,0.35)", name: "Verifier" },
  risk: { fill: "#c9604f", glow: "rgba(201,96,79,0.4)", name: "Risk Guard" },
};

export function CrewAvatar({
  id,
  mood = "idle",
  size = 64,
  className,
}: {
  id: CrewId;
  mood?: CrewMood;
  size?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const palette = ACCENT[id];
  const working = mood === "working";
  const failed = mood === "failed";
  const float = reduce || mood === "offline" ? 0 : working ? 3 : 2;
  return (
    <motion.div
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
      animate={reduce ? undefined : { y: [0, -float, 0] }}
      transition={{ duration: working ? 1.1 : 3.4, repeat: Infinity, ease: "easeInOut" }}
      aria-label={`${palette.name}, ${mood}`}
      role="img"
    >
      <span
        className="absolute inset-0 rounded-full"
        style={{ boxShadow: working ? `0 0 22px ${palette.glow}` : undefined }}
      />
      <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden>
        {id === "copilot" ? <CopilotBody mood={mood} /> : null}
        {id === "scout" ? <ScoutBody mood={mood} /> : null}
        {id === "researcher" ? <ResearcherBody mood={mood} /> : null}
        {id === "skeptic" ? <SkepticBody mood={mood} /> : null}
        {id === "reviewer" ? <ReviewerBody mood={mood} /> : null}
        {id === "verifier" ? <VerifierBody mood={mood} /> : null}
        {id === "risk" ? <RiskBody mood={mood} /> : null}
        {failed ? <line x1="14" y1="14" x2="50" y2="50" stroke="#e07a6a" strokeWidth="3" /> : null}
        {mood === "replay" ? (
          <text x="32" y="60" textAnchor="middle" fill="#f2d58a" fontSize="7">
            REPLAY
          </text>
        ) : null}
      </svg>
    </motion.div>
  );
}

function Face({
  cx = 32,
  cy = 30,
  mood,
  eye = "#140e02",
}: {
  cx?: number;
  cy?: number;
  mood: CrewMood;
  eye?: string;
}) {
  const worried = mood === "concern" || mood === "failed";
  const happy = mood === "success";
  const working = mood === "working";
  return (
    <g>
      <motion.circle
        cx={cx - 6}
        cy={cy}
        r={mood === "offline" ? 1.2 : 2.2}
        fill={eye}
        animate={working ? { cx: [cx - 6, cx - 4, cx - 6] } : undefined}
        transition={{ duration: 1.6, repeat: Infinity }}
      />
      <motion.circle
        cx={cx + 6}
        cy={cy}
        r={mood === "offline" ? 1.2 : 2.2}
        fill={eye}
        animate={working ? { cx: [cx + 6, cx + 8, cx + 6] } : undefined}
        transition={{ duration: 1.6, repeat: Infinity }}
      />
      <path
        d={
          worried
            ? `M${cx - 7} ${cy + 10} Q ${cx} ${cy + 6} ${cx + 7} ${cy + 10}`
            : happy
              ? `M${cx - 7} ${cy + 8} Q ${cx} ${cy + 14} ${cx + 7} ${cy + 8}`
              : working
                ? `M${cx - 5} ${cy + 9} H ${cx + 5}`
                : `M${cx - 6} ${cy + 9} Q ${cx} ${cy + 11} ${cx + 6} ${cy + 9}`
        }
        fill="none"
        stroke={eye}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </g>
  );
}

function CopilotBody({ mood }: { mood: CrewMood }) {
  return (
    <g>
      <ellipse cx="32" cy="33" rx="18" ry="20" fill="#f2d58a" />
      <ellipse cx="32" cy="28" rx="14" ry="12" fill="#f7e3a6" />
      <circle cx="18" cy="18" r="3" fill="#e0b84f" />
      <circle cx="46" cy="16" r="2" fill="#fff4c8" />
      <Face mood={mood} />
    </g>
  );
}

function ScoutBody({ mood }: { mood: CrewMood }) {
  return (
    <g>
      <circle cx="48" cy="16" r="8" fill="none" stroke="#7ec8a3" strokeWidth="2" />
      <path d="M48 8 v4 M48 20 v4 M40 16 h4 M52 16 h4" stroke="#7ec8a3" strokeWidth="1.5" />
      <ellipse cx="32" cy="36" rx="16" ry="18" fill="#1c3d32" />
      <path d="M16 28 Q32 14 48 28" fill="#7ec8a3" />
      <Face mood={mood} cy={36} eye="#e8fff4" />
    </g>
  );
}

function ResearcherBody({ mood }: { mood: CrewMood }) {
  return (
    <g>
      <rect x="14" y="16" width="36" height="36" rx="16" fill="#123246" />
      <circle cx="24" cy="30" r="8" fill="none" stroke="#7ec8e8" strokeWidth="2" />
      <circle cx="40" cy="30" r="8" fill="none" stroke="#7ec8e8" strokeWidth="2" />
      <path d="M32 30 H36" stroke="#7ec8e8" strokeWidth="2" />
      <Face mood={mood} eye="#7ec8e8" />
    </g>
  );
}

function SkepticBody({ mood }: { mood: CrewMood }) {
  return (
    <g>
      <path d="M18 54 L32 10 L46 54 Z" fill="#3a2414" />
      <path d="M24 24 L32 14 L40 24" fill="#e7a35c" />
      <Face mood={mood} cy={32} eye="#f6d7b0" />
    </g>
  );
}

function ReviewerBody({ mood }: { mood: CrewMood }) {
  return (
    <g>
      <ellipse cx="32" cy="34" rx="18" ry="20" fill="#1c2733" />
      <rect x="20" y="14" width="24" height="8" rx="3" fill="#9fb3c8" />
      <Face mood={mood} cy={34} eye="#d5e4f2" />
    </g>
  );
}

function VerifierBody({ mood }: { mood: CrewMood }) {
  const color = mood === "failed" ? "#e07a6a" : mood === "success" ? "#e0b84f" : "#d4a73c";
  return (
    <g>
      <polygon points="32,8 54,20 54,44 32,56 10,44 10,20" fill="#1a1408" stroke={color} strokeWidth="2" />
      <text x="32" y="28" textAnchor="middle" fill={color} fontSize="6">
        RULES
      </text>
      <Face mood={mood} cy={38} />
    </g>
  );
}

function RiskBody({ mood }: { mood: CrewMood }) {
  const color = mood === "success" ? "#e0b84f" : mood === "failed" ? "#e07a6a" : "#c9604f";
  return (
    <g>
      <path d="M32 8 L54 18 V34 C54 46 32 56 32 56 C32 56 10 46 10 34 V18 Z" fill="#2a1210" stroke={color} strokeWidth="2" />
      <text x="32" y="22" textAnchor="middle" fill={color} fontSize="6">
        RISK
      </text>
      <Face mood={mood} cy={36} eye="#f7d0c8" />
    </g>
  );
}
