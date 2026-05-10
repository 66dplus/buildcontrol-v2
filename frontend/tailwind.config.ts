import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#ffffff",
        bg: "#fafaf9",
        ink: "#0c0a09",
        muted: "#78716c",
        accent: "#3ba6f1",
        "accent-soft": "#3ba6f110",
        border: "#e5e7eb",
        warning: "#e07c3e",
        success: "#22c55e",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        heading: ["roobert", "Inter", "system-ui", "sans-serif"],
      },
      borderRadius: {
        input: "4px",
        card: "10px",
        pill: "9999px",
        "card-lg": "16px",
      },
      boxShadow: {
        card: "0 1px 3px rgba(0,0,0,0.05)",
      },
      fontSize: {
        kpi: ["28px", { lineHeight: "32px", fontWeight: "700" }],
      },
    },
  },
  plugins: [],
} satisfies Config;
