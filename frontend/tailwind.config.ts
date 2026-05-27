import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Stage palette — play surface
        midnight: "#101421",
        midnightHover: "#273048",
        night: "#22283a",
        stagegold: "#f7c948",
        stagegoldHover: "#ffd95e",
        electric: "#3564ff",
        magenta: "#e83a8e",
        aqua: "#72e0b3",
        aquaHover: "#8ef1c8",
        coral: "#f05d5e",
        champagne: "#e8c87a",
        inviteError: "#ffb7a1",
        // Booth palette — authoring surface
        paper: "#f3f4f8",
        pale: "#eef1f6",
        chip: "#f2f4f8",
        chipHover: "#e3e7ef",
        softline: "#d5d8df",
        steel: "#5d6575",
        softblue: "#cbd8ff",
      },
      fontFamily: {
        display: ['"Anton"', "Inter", "system-ui", "sans-serif"],
        sans: ['"Inter"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        panel: "0 18px 50px rgba(16, 20, 33, 0.10)",
        stage: "0 24px 60px rgba(16, 20, 33, 0.35)",
      },
      keyframes: {
        shake: {
          "0%, 100%": { transform: "translateX(0)" },
          "20%": { transform: "translateX(-6px)" },
          "40%": { transform: "translateX(6px)" },
          "60%": { transform: "translateX(-3px)" },
          "80%": { transform: "translateX(3px)" },
        },
        pulseScale: {
          "0%, 100%": { transform: "scale(1)" },
          "50%": { transform: "scale(1.08)" },
        },
      },
      animation: {
        shake: "shake 250ms ease-out",
        pulseScale: "pulseScale 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
