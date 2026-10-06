# AI TrafficOS — Web Platform (Phase 1)

This package contains the **Phase 1: Foundation & Architecture** web track implementation for **AI TrafficOS**, an AI-powered intelligent traffic management system.

## 🚀 Overview

AI TrafficOS is designed to coordinate multi-modal sensor perception, adaptive signal control, and urban flow optimization. Phase 1 establishes the verified architecture, strict design system tokens, accessible component library, API integration client, and placeholder extension points for upcoming operational phases.

### 🛡️ Iron Integrity Rules
1. **Phase 1 Foundation Only**: Implements strictly the foundation layer without mock statistics or fake live traffic data.
2. **Honest Extension Points**: Future dashboards (such as the live operations screen scheduled for Phase 6) are structured as documented skeleton shells.

---

## 🛠️ Technology Stack

- **Framework**: Next.js 15 (App Router, Turbopack)
- **Runtime**: React 19
- **Language**: TypeScript
- **Styling**: Tailwind CSS v4 with `@theme` token definitions
- **Typography**: Google Fonts (`Space Grotesk` display + `Inter` body)
- **Animation**: Framer Motion
- **Icons**: Lucide React & Semantic SVG

---

## 📁 Directory Structure

```text
web/
├── public/                 # Static assets & icons
├── src/
│   ├── app/
│   │   ├── globals.css     # Tailwind CSS v4 @theme tokens & base styles
│   │   ├── layout.tsx      # Root layout wiring font variables (Space Grotesk & Inter)
│   │   ├── page.tsx        # Landing page with hero, honest stats, roadmap grid & architecture strip
│   │   └── platform/
│   │       └── page.tsx    # Operations dashboard placeholder shell (Phase 6 extension point)
│   ├── components/
│   │   ├── SystemStatus.tsx # Client component monitoring FastAPI health
│   │   └── ui/             # Reusable accessible UI components
│   │       ├── Badge.tsx   # Small pill badge (teal, amber, muted, danger, success)
│   │       ├── Button.tsx  # Pill button (primary, secondary, ghost; sm, md, lg)
│   │       ├── Card.tsx    # 14px rounded surface card with border
│   │       ├── Footer.tsx  # Global footer with copyright, repository link, and Phase 1 note
│   │       ├── Navbar.tsx  # Header navigation with mobile menu and route highlights
│   │       ├── SectionHeading.tsx # Section titles with eyebrow and subcopy
│   │       └── Stat.tsx    # Static honest metrics display
│   └── lib/
│       ├── api.ts          # Typed fetch client with timeout and getHealth()
│       └── tokens.ts       # Typed design tokens const (ink, surface, accent, etc.)
├── .env.example            # Environment variables template
├── next.config.ts          # Next.js configuration
├── package.json            # Project dependencies and scripts
└── tsconfig.json           # TypeScript configuration
```

---

## 🎨 Design System Tokens

The application strictly implements the design system specification:

| Token | Value | Role |
| :--- | :--- | :--- |
| `--color-ink` | `#0B1020` | Page background |
| `--color-surface` | `#131A2E` | Card / surface background |
| `--color-accent` | `#00D9A8` | Brand teal accent |
| `--color-amber` | `#FFB800` | Warning / in-progress indicator |
| `--color-danger` | `#FF4D6D` | Critical alerts |
| `--color-success` | `#22C55E` | Online / success status |
| `--color-text` | `#EAF0FF` | Primary body text |
| `--color-muted` | `#8B93B0` | Muted secondary text |
| `--radius-card` | `14px` | Card corner radius |
| Button Radius | Pill (`rounded-full`) | Button corner radius |

Tokens are exported as a typed constant in [`src/lib/tokens.ts`](src/lib/tokens.ts) and configured as Tailwind v4 tokens in [`src/app/globals.css`](src/app/globals.css).

---

## ⚙️ Environment Variables

Create a `.env.local` file in `web/` based on [`.env.example`](.env.example):

```bash
cp .env.example .env.local
```

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Target FastAPI backend URL for health probes |

---

## 🚦 Getting Started

### 1. Install dependencies
From the `/home/hatch/workspace/AI-TrafficOS/web` directory:
```bash
npm install
```

### 2. Type-check
```bash
npx tsc --noEmit
```

### 3. Build for production
```bash
npm run build
```

### 4. Run the development server
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to view the landing page, or [http://localhost:3000/platform](http://localhost:3000/platform) to view the operations dashboard shell.

---

## 🗺️ Roadmap Progression

- **Phase 1 (Current)**: Foundation, architecture scaffolding, design system, typed API client, and extension shells.
- **Phase 2**: Backend FastAPI integration, PostgreSQL persistence, and initial health endpoints.
- **Phase 3**: Vehicle detection models & computer vision pipelines.
- **Phase 4**: Redis message broker & WebSocket real-time sensor streams.
- **Phase 5**: Signal detection & automated traffic light status analysis.
- **Phase 6**: Live operations dashboard canvas (activating the `/platform` extension point).
- **Phases 7–11**: Route guidance, incident detection, signal reinforcement learning optimization, city-wide analytics, and conversational AI assistant.
